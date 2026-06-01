import psycopg2
from psycopg2.extras import DictCursor
from config import config
from datetime import datetime
import json

class DeploymentState:
    QUEUED = "Queued"
    BUILDING = "Building"
    DEPLOYING = "Deploying"
    VERIFYING = "Verifying"
    RUNNING = "Running"
    RETRY = "Retry"
    DLQ = "DLQ"

class StateMachine:
    def __init__(self):
        self.conn = psycopg2.connect(config.DATABASE_URL)
        self.conn.autocommit = True
        self._ensure_table()

    def _ensure_table(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS deployments (
                    deployment_id VARCHAR(255) PRIMARY KEY,
                    state VARCHAR(50) NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    last_error TEXT
                );
            """)

    def update_state(self, deployment_id: str, new_state: str, error_msg: str = None):
        """
        Idempotent state update.
        Kubernetes state is not authoritative; PostgreSQL is.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO deployments (deployment_id, state, updated_at, last_error)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (deployment_id) DO UPDATE 
                SET state = EXCLUDED.state,
                    updated_at = EXCLUDED.updated_at,
                    last_error = EXCLUDED.last_error;
            """, (deployment_id, new_state, datetime.utcnow(), error_msg))
        print(f"Deployment {deployment_id} transition -> {new_state}")
        
    def get_deployment(self, deployment_id: str):
        with self.conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM deployments WHERE deployment_id = %s;", (deployment_id,))
            row = cur.fetchone()
            return dict(row) if row else None
