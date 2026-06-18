# Data Flow Diagram

```mermaid
flowchart LR
    User([User]) -->|Source Code| GitHub[GitHub Repo]
    User -->|Deploy Request| API[ShipZen API]
    API -->|Write Desired State| DB[(PostgreSQL)]
    API -->|Enqueue Event| Queue[Redis Streams]
    
    Queue -->|Consume Event| Worker[Worker Engine]
    Worker -->|Write Desired State (Building)| DB
    Worker -->|Enqueue Build Task| BuilderQueue[builder_queue (Redis Streams)]
    
    BuilderQueue -->|Consume Build Task| Builder[Builder Pool]
    Builder -->|Fetch Source| GitHub
    Builder -->|Push Image| Registry[(OCI Registry)]
    
    Controller[Reconciliation Engine] -->|Read Desired State| DB
    Controller -->|Update Actual State| K8s[Kubernetes]
```
