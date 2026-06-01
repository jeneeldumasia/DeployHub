import redis
import time
from config import config
from metrics import deployhub_queue_depth, deployhub_dlq_depth

class QueueClient:
    def __init__(self):
        self.r = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT, decode_responses=True)
        self.stream = config.STREAM_NAME
        self.group = config.CONSUMER_GROUP
        self.consumer = config.CONSUMER_NAME
        self.dlq_stream = f"{self.stream}_dlq"
        
        self._ensure_group()
        
    def _ensure_group(self):
        try:
            self.r.xgroup_create(self.stream, self.group, id='0', mkstream=True)
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
                
    def get_messages(self, count=1, block_ms=5000):
        """Read from the stream for new messages (id='>')"""
        messages = self.r.xreadgroup(self.group, self.consumer, {self.stream: '>'}, count=count, block=block_ms)
        self.update_metrics()
        return messages
        
    def ack_message(self, message_id):
        self.r.xack(self.stream, self.group, message_id)
        
    def add_to_dlq(self, message_id, data):
        """Move message to DLQ and ACK it from main stream"""
        self.r.xadd(self.dlq_stream, data)
        self.ack_message(message_id)
        print(f"Message {message_id} moved to DLQ")
        
    def recover_pending_messages(self):
        """Pending Message Recovery: XPENDING and XCLAIM"""
        pending = self.r.xpending_range(self.stream, self.group, '-', '+', 100)
        for msg in pending:
            message_id = msg['message_id']
            consumer = msg['consumer']
            idle_time = msg['time_since_delivered']
            
            if idle_time > config.PENDING_MESSAGE_TIMEOUT_MS:
                print(f"Recovering pending message {message_id} from {consumer}")
                # Claim the message
                self.r.xclaim(self.stream, self.group, self.consumer, config.PENDING_MESSAGE_TIMEOUT_MS, [message_id])
                
    def update_metrics(self):
        try:
            # Note: exact queue depth might require custom tracking, but xlen gives stream length
            # A more accurate queue depth would subtract consumers' ACKs, but XLEN is a good proxy if trimmed.
            # We'll use xinfo_groups to find pending + unread.
            info = self.r.xinfo_groups(self.stream)
            for g in info:
                if g['name'] == self.group:
                    # Pending messages
                    deployhub_queue_depth.set(g['pending'])
                    
            dlq_len = self.r.xlen(self.dlq_stream)
            deployhub_dlq_depth.set(dlq_len)
        except Exception:
            pass
