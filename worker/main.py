import time
import json
import logging
import random
from config import config
from queue_client import QueueClient
from state_machine import StateMachine, DeploymentState
from metrics import start_metrics_server, deployhub_retry_total, deployhub_queue_latency_seconds

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('worker')

def handoff_to_builder(queue: QueueClient, deployment_id: str, data: dict):
    """Enqueues a build task to the separate builder_queue."""
    build_data = {
        "deployment_id": deployment_id,
        "repo_url": data.get("repo_url", ""),
        "image_name": data.get("image_name", "")
    }
    queue.r.xadd("builder_queue", build_data)
    logger.info(f"Deployment {deployment_id} handed off to builder_queue")

def process_message(queue: QueueClient, state_machine: StateMachine, message_id: str, data: dict):
    deployment_id = data.get("deployment_id")
    if not deployment_id:
        logger.error(f"Message {message_id} missing deployment_id. Moving to DLQ.")
        queue.add_to_dlq(message_id, data)
        return

    queued_at = data.get("queued_at")
    if queued_at:
        latency = time.time() - float(queued_at)
        deployhub_queue_latency_seconds.observe(latency)

    retries = int(data.get("retries", "0"))
    
    # Duplicate Protection & Idempotent Deployments
    deployment = state_machine.get_deployment(deployment_id)
    if deployment and deployment.get("state") in [DeploymentState.RUNNING, DeploymentState.VERIFYING]:
        logger.info(f"Deployment {deployment_id} already processed. Acking message.")
        queue.ack_message(message_id)
        return

    logger.info(f"Processing deployment {deployment_id}, attempt {retries + 1}")
    
    try:
        # State: Building
        state_machine.update_state(deployment_id, DeploymentState.BUILDING)
        
        # Handoff to Builder Pool
        handoff_to_builder(queue, deployment_id, data)
        
        # Ack message from deployment queue
        queue.ack_message(message_id)
        logger.info(f"Deployment {deployment_id} successfully queued for building")
        
    except Exception as e:
        logger.error(f"Error processing {deployment_id}: {e}")
        retries += 1
        deployhub_retry_total.inc()
        
        if retries > config.MAX_RETRIES:
            logger.error(f"Max retries exceeded for {deployment_id}. Moving to DLQ.")
            state_machine.update_state(deployment_id, DeploymentState.DLQ, error_msg=str(e))
            queue.add_to_dlq(message_id, data)
        else:
            state_machine.update_state(deployment_id, DeploymentState.RETRY, error_msg=str(e))
            
            # Exponential backoff
            backoff = 2 ** retries
            logger.info(f"Backing off for {backoff} seconds before retry.")
            time.sleep(backoff)
            
            # Re-queue for retry by adding it back and acking the old one
            data["retries"] = str(retries)
            queue.r.xadd(queue.stream, data)
            queue.ack_message(message_id)

def main():
    start_metrics_server(port=8000)
    queue = QueueClient()
    state_machine = StateMachine()
    
    logger.info(f"Worker {config.CONSUMER_NAME} started. Listening on stream {config.STREAM_NAME}")
    
    while True:
        try:
            # Recover pending messages first
            queue.recover_pending_messages()
            
            # Read new messages
            messages = queue.get_messages(count=5, block_ms=2000)
            if messages:
                for stream_name, msg_list in messages:
                    for msg_id, data in msg_list:
                        process_message(queue, state_machine, msg_id, data)
        except Exception as e:
            logger.error(f"Queue read error: {e}")
            time.sleep(2)

if __name__ == "__main__":
    main()
