import os
import time
import uuid
import logging
import subprocess
import threading
import redis
import psycopg2
import boto3

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('builder')

REDIS_HOST = os.getenv("REDIS_HOST", "redis-master.deployhub-system.svc.cluster.local")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
BUILDER_QUEUE = os.getenv("BUILDER_QUEUE", "builder_queue")
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "builder_group")
CONSUMER_NAME = os.getenv("HOSTNAME", "builder-1")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/deployhub")
S3_LOG_BUCKET = os.getenv("S3_LOG_BUCKET", "deployhub-build-logs")

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
s3 = boto3.client('s3')

try:
    r.xgroup_create(BUILDER_QUEUE, CONSUMER_GROUP, id='0', mkstream=True)
except redis.exceptions.ResponseError as e:
    if "BUSYGROUP" not in str(e):
        raise

def update_db_state(deployment_id: str, state: str, error_msg: str = None):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE deployments 
                SET state = %s, last_error = %s, updated_at = NOW()
                WHERE deployment_id = %s;
            """, (state, error_msg, deployment_id))
        conn.close()
    except Exception as e:
        logger.error(f"Failed to update PostgreSQL state: {e}")

def record_build(deployment_id: str, s3_key: str, status: str):
    build_id = str(uuid.uuid4())
    s3_uri = f"s3://{S3_LOG_BUCKET}/{s3_key}"
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO builds (build_id, deployment_id, s3_log_uri, status)
                VALUES (%s, %s, %s, %s);
            """, (build_id, deployment_id, s3_uri, status))
        conn.close()
    except Exception as e:
        logger.error(f"Failed to record build in PostgreSQL: {e}")

def run_build(deployment_id: str, repo_url: str, image_name: str):
    workspace = f"/workspace/{deployment_id}"
    os.makedirs(workspace, exist_ok=True)
    
    logger.info(f"Cloning {repo_url} into {workspace}")
    subprocess.run(["git", "clone", repo_url, workspace], check=True)
    
    s3_log_key = f"logs/{deployment_id}/build.log"
    has_dockerfile = os.path.exists(os.path.join(workspace, "Dockerfile"))
    
    if has_dockerfile:
        logger.info("Dockerfile found. Using Kaniko executor.")
        # Kaniko natively pushes to the destination
        cmd = [
            "executor",
            "--context", workspace,
            "--dockerfile", os.path.join(workspace, "Dockerfile"),
            "--destination", image_name
        ]
    else:
        logger.info("No Dockerfile found. Using Cloud Native Buildpacks (pack).")
        # Pack uses --publish to push directly to registry
        cmd = [
            "pack", "build", image_name,
            "--path", workspace,
            "--builder", "paketobuildpacks/builder-jammy-base",
            "--publish"
        ]

    logger.info(f"Executing: {' '.join(cmd)}")
    
    # Execute the build process and stream logs directly to S3 without using local disk
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    
    try:
        # boto3 upload_fileobj reads natively from the stdout PIPE stream
        s3.upload_fileobj(process.stdout, S3_LOG_BUCKET, s3_log_key)
        process.wait()
        
        if process.returncode == 0:
            logger.info(f"Build {deployment_id} successful.")
            record_build(deployment_id, s3_log_key, "Success")
            update_db_state(deployment_id, "Deploying")
        else:
            logger.error(f"Build {deployment_id} failed with exit code {process.returncode}.")
            record_build(deployment_id, s3_log_key, "Failed")
            update_db_state(deployment_id, "Failed", "Build step failed.")
            
    finally:
        # Cleanup workspace
        subprocess.run(["rm", "-rf", workspace])

def main():
    logger.info(f"Builder {CONSUMER_NAME} started. Listening on {BUILDER_QUEUE}")
    while True:
        try:
            messages = r.xreadgroup(CONSUMER_GROUP, CONSUMER_NAME, {BUILDER_QUEUE: '>'}, count=1, block=5000)
            if messages:
                for stream, msg_list in messages:
                    for msg_id, data in msg_list:
                        deployment_id = data.get("deployment_id")
                        repo_url = data.get("repo_url")
                        image_name = data.get("image_name")
                        
                        logger.info(f"Processing build task for deployment {deployment_id}")
                        try:
                            run_build(deployment_id, repo_url, image_name)
                            r.xack(BUILDER_QUEUE, CONSUMER_GROUP, msg_id)
                        except Exception as e:
                            logger.error(f"Build task crashed: {e}")
                            update_db_state(deployment_id, "Retry", str(e))
                            # Depending on retry logic, we might not ACK to allow DLQ processing
        except Exception as e:
            logger.error(f"Error reading from queue: {e}")
            time.sleep(2)

if __name__ == "__main__":
    main()
