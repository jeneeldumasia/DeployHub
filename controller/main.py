import os
import time
import logging
import psycopg2
from psycopg2.extras import DictCursor
from jinja2 import Environment, FileSystemLoader
from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException
from models import ProjectStatus, ProjectSchema
from metrics import deployhub_drift_total, deployhub_reconciliation_duration_seconds, start_metrics_server

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('controller')

try:
    k8s_config.load_incluster_config()
except k8s_config.ConfigException:
    k8s_config.load_kube_config()

k8s_core_api = client.CoreV1Api()
k8s_apps_api = client.AppsV1Api()
k8s_custom_api = client.CustomObjectsApi()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/deployhub")
RECONCILIATION_INTERVAL = 60

jinja_env = Environment(loader=FileSystemLoader("templates"))

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn

def init_db():
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                namespace VARCHAR(255) NOT NULL,
                status VARCHAR(50) NOT NULL DEFAULT 'Provisioning',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                deleted_at TIMESTAMP
            );
        """)
    conn.close()

def apply_manifests(manifest_str: str):
    logger.info("Applying K8s manifests...")
    with open("/tmp/tenant-apply.yaml", "w") as f:
        f.write(manifest_str)
    # os.system("kubectl apply -f /tmp/tenant-apply.yaml")

def check_namespace_exists(namespace: str) -> bool:
    try:
        k8s_core_api.read_namespace(name=namespace)
        return True
    except ApiException as e:
        if e.status == 404:
            return False
        raise

def delete_namespace(namespace: str):
    try:
        k8s_core_api.delete_namespace(name=namespace)
    except ApiException as e:
        if e.status != 404:
            raise

@deployhub_reconciliation_duration_seconds.time()
def reconcile():
    logger.info("Starting reconciliation loop...")
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM projects;")
            projects = cur.fetchall()
            
            for row in projects:
                # Map to ProjectSchema
                project_data = dict(row)
                project_data["_id"] = project_data.pop("id")
                
                try:
                    project = ProjectSchema(**project_data)
                    
                    if project.status == ProjectStatus.PROVISIONING:
                        logger.info(f"Provisioning project: {project.name} ({project.namespace})")
                        template = jinja_env.get_template("tenant.yaml.j2")
                        manifests = template.render(
                            namespace=project.namespace,
                            project_id=project.id
                        )
                        apply_manifests(manifests)
                        
                        cur.execute("UPDATE projects SET status = %s WHERE id = %s;", 
                                  (ProjectStatus.READY.value, project.id))
                        logger.info(f"Project {project.name} provisioned and Ready.")
                        
                    elif project.status == ProjectStatus.TERMINATING:
                        logger.info(f"Terminating project: {project.name} ({project.namespace})")
                        if check_namespace_exists(project.namespace):
                            delete_namespace(project.namespace)
                            logger.info(f"Namespace {project.namespace} deletion triggered.")
                        else:
                            cur.execute("DELETE FROM projects WHERE id = %s;", (project.id,))
                            logger.info(f"Project {project.name} permanently cleaned up.")
                            
                    elif project.status == ProjectStatus.READY:
                        if not check_namespace_exists(project.namespace):
                            deployhub_drift_total.inc()
                            logger.warning(f"Drift detected! Namespace {project.namespace} missing for Ready project.")
                            cur.execute("UPDATE projects SET status = %s WHERE id = %s;", 
                                      (ProjectStatus.PROVISIONING.value, project.id))
                        else:
                            reconcile_deployments(cur, project)
                except Exception as e:
                    logger.error(f"Error reconciling project {row['id']}: {e}")
    finally:
        conn.close()

def reconcile_deployments(cur, project):
    """Reconciles Deployments, Services, and HTTPRoutes for a ready project namespace."""
    cur.execute("SELECT * FROM deployments WHERE project_id = %s;", (project.id,))
    db_deployments = {row['deployment_id']: dict(row) for row in cur.fetchall()}
    
    try:
        k8s_deps = k8s_apps_api.list_namespaced_deployment(namespace=project.namespace)
        k8s_dep_names = {d.metadata.name: d for d in k8s_deps.items}
        
        # 1. Missing or Drifted Deployments
        for d_id, db_dep in db_deployments.items():
            if db_dep['state'] in ['Running', 'Verifying', 'Deploying']:
                if d_id not in k8s_dep_names:
                    deployhub_drift_total.inc()
                    logger.warning(f"Drift: Deployment {d_id} missing in K8s. Recreating...")
                    
                    template = jinja_env.get_template("app-deployment.yaml.j2")
                    manifests = template.render(
                        deployment_name=d_id,
                        namespace=project.namespace,
                        project_name=project.name,
                        image_uri=db_dep.get('image_uri', 'nginx:latest'),
                        port=db_dep.get('port', 8080),
                        replicas=db_dep.get('replicas', 1)
                    )
                    apply_manifests(manifests)
                else:
                    # Check for Failed Deployment
                    k8s_dep = k8s_dep_names[d_id]
                    ready_replicas = k8s_dep.status.ready_replicas or 0
                    if ready_replicas == 0 and db_dep['state'] == 'Running':
                        deployhub_drift_total.inc()
                        logger.warning(f"Drift: Deployment {d_id} is failing in K8s.")
                        cur.execute("UPDATE deployments SET state = %s, last_error = %s WHERE deployment_id = %s;", 
                                  ('Failed', 'Kubernetes Deployment Failed/CrashLoopBackOff', d_id))
                        
        # 2. Orphan Resources Cleanup
        for k8s_name in k8s_dep_names.keys():
            if k8s_name not in db_deployments or db_deployments[k8s_name]['state'] not in ['Running', 'Verifying', 'Deploying']:
                deployhub_drift_total.inc()
                logger.warning(f"Drift: Orphan Deployment {k8s_name} found in K8s. Cleaning up...")
                k8s_apps_api.delete_namespaced_deployment(name=k8s_name, namespace=project.namespace)
                try:
                    k8s_core_api.delete_namespaced_service(name=f"{k8s_name}-svc", namespace=project.namespace)
                    k8s_custom_api.delete_namespaced_custom_object(
                        group="gateway.networking.k8s.io",
                        version="v1",
                        namespace=project.namespace,
                        plural="httproutes",
                        name=f"{k8s_name}-route"
                    )
                except ApiException:
                    pass
    except Exception as e:
        logger.error(f"Error reconciling deployments for {project.name}: {e}")

def main():
    start_metrics_server(port=8080)
    init_db()
    while True:
        reconcile()
        time.sleep(RECONCILIATION_INTERVAL)

if __name__ == "__main__":
    main()
