import os

class Config:
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/deployhub")
    
    STREAM_NAME = os.getenv("STREAM_NAME", "deploy_stream")
    CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "worker_group")
    CONSUMER_NAME = os.getenv("HOSTNAME", "worker-1")  # Using hostname for unique consumer ID
    
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    PENDING_MESSAGE_TIMEOUT_MS = int(os.getenv("PENDING_MESSAGE_TIMEOUT_MS", "300000")) # 5 minutes

config = Config()
