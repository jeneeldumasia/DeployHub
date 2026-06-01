import os
import psycopg2
from psycopg2.extras import DictCursor
import logging

logger = logging.getLogger(__name__)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/deployhub")

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def get_deployments_paginated(project_id: str, limit: int = 20, cursor_updated_at: str = None):
    """
    Keyset Pagination (Cursor-based) for highly efficient listing APIs.
    Avoids OFFSET which degrades performance on large datasets.
    Projection: Explicitly selects only required fields.
    """
    query = """
        SELECT deployment_id, state, updated_at
        FROM deployments
        WHERE project_id = %s
    """
    params = [project_id]
    
    if cursor_updated_at:
        query += " AND updated_at < %s"
        params.append(cursor_updated_at)
        
    query += " ORDER BY updated_at DESC LIMIT %s;"
    params.append(limit)
    
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(query, tuple(params))
            return [dict(row) for row in cur.fetchall()]

def enforce_retention_policy():
    """
    Retention Policy: Delete failed builds older than 30 days, 
    and successful builds older than 90 days.
    (Deployment retention handled separately or cascaded).
    """
    logger.info("Running retention policy cleanup...")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM builds 
                WHERE (status = 'Failed' AND completed_at < NOW() - INTERVAL '30 days')
                   OR (status = 'Success' AND completed_at < NOW() - INTERVAL '90 days');
            """)
            deleted = cur.rowcount
            logger.info(f"Retention policy applied. Deleted {deleted} old builds.")
            conn.commit()
