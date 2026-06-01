from prometheus_client import Gauge, Summary, start_http_server

deployhub_drift_total = Gauge(
    'deployhub_drift_total',
    'Total number of detected drift incidents (missing or orphaned resources)'
)

deployhub_reconciliation_duration_seconds = Summary(
    'deployhub_reconciliation_duration_seconds',
    'Time spent in the reconciliation loop'
)

def start_metrics_server(port=8080):
    start_http_server(port)
