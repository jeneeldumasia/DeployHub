import os
import pathlib

DOCS_DIR = pathlib.Path('c:/Project/DeployHub/docs')
ADR_DIR = DOCS_DIR / 'adr'
ARCH_DIR = DOCS_DIR / 'architecture'

os.makedirs(ADR_DIR, exist_ok=True)
os.makedirs(ARCH_DIR, exist_ok=True)

arch_files = {
    '01-target-architecture.md': '''# Target Architecture Diagram

```mermaid
graph TD
    Client[Client / Developer] -->|HTTPS| CF[Cloudflare]
    CF --> ALB[AWS ALB]
    ALB --> EG[Envoy Gateway - Gateway API]
    
    subgraph DeployHub Control Plane
        EG --> API[API Server]
        API --> Redis[Redis Streams - Queue]
        API --> Mongo[(MongoDB - Source of Truth)]
        
        Redis --> Worker[Deployment Worker]
        Worker --> Mongo
        Worker --> K8sAPI[Kubernetes API]
        
        Mongo --> Controller[Reconciliation Engine]
        Controller --> K8sAPI
    end
    
    subgraph Builder Pool
        Worker --> BuilderQueue[Builder Queue]
        BuilderQueue --> Builder[Cloud Native Buildpacks]
        Builder --> S3_Logs[S3 Build Logs]
        Builder --> Registry[Container Registry]
    end
    
    subgraph Multi-Tenant Runtime
        K8sAPI --> T1[Tenant Namespace 1]
        K8sAPI --> T2[Tenant Namespace 2]
    end
    
    subgraph Platform Services
        ESO[External Secrets Operator] --> AWS_SM[AWS Secrets Manager]
        Prometheus[Prometheus]
        Grafana[Grafana]
    end
```
''',
    '02-service-dependency-graph.md': '''# Service Dependency Graph

```mermaid
graph TD
    API[API Server] --> Mongo[MongoDB]
    API --> Redis[Redis Streams]
    Worker[Deployment Worker] --> Redis
    Worker --> Mongo
    Worker --> Builder[Builder Jobs]
    Controller[Reconciliation Engine] --> Mongo
    Controller --> K8s[Kubernetes API]
    Gateway[Envoy Gateway] --> API
    Gateway --> Workloads[Tenant Workloads]
```
''',
    '03-service-interaction-diagram.md': '''# Service Interaction Diagram

```mermaid
sequenceDiagram
    participant User
    participant API
    participant Mongo
    participant Redis
    participant Worker
    participant Builder
    participant K8s
    
    User->>API: POST /deploy
    API->>Mongo: Create Deployment Record (State: Queued)
    API->>Redis: XADD deploy_stream
    API-->>User: 202 Accepted (Deployment ID)
    
    Redis->>Worker: XREADGROUP
    Worker->>Mongo: Update State (Building)
    Worker->>Builder: Launch Buildpack Pod
    Builder-->>Worker: Build Complete (Image URI)
    Worker->>Mongo: Update State (Deploying)
    Worker->>K8s: Apply Manifests
    Worker->>Mongo: Update State (Running)
    Worker->>Redis: XACK deploy_stream
```
''',
    '04-data-flow-diagram.md': '''# Data Flow Diagram

```mermaid
flowchart LR
    User([User]) -->|Source Code| GitHub[GitHub Repo]
    User -->|Deploy Request| API[DeployHub API]
    API -->|Write Desired State| DB[(MongoDB)]
    API -->|Enqueue Event| Queue[Redis Streams]
    
    Queue -->|Consume Event| Worker[Worker Engine]
    Worker -->|Fetch Source| GitHub
    Worker -->|Push Image| Registry[(OCI Registry)]
    Worker -->|Read Desired State| DB
    
    Controller[Reconciliation Engine] -->|Read Desired State| DB
    Controller -->|Update Actual State| K8s[Kubernetes]
```
''',
    '05-security-boundary-diagram.md': '''# Security Boundary Diagram

```mermaid
graph TD
    subgraph Public Internet
        Users
    end
    
    subgraph DMZ
        Cloudflare --> AWS_ALB[AWS ALB]
    end
    
    subgraph DeployHub Platform [Namespace: deployhub-system]
        AWS_ALB --> Envoy[Envoy Gateway]
        Envoy --> API[API Server]
        API --> Mongo[(MongoDB)]
        API --> Redis[(Redis)]
        Controller[Reconciliation Engine]
        ESO[External Secrets Operator]
    end
    
    subgraph Builder Isolation [Namespace: deployhub-build]
        Worker --> Builder[Builder Pods]
        Builder -- IRSA --> ECR[AWS ECR]
        Builder -- NetworkPolicy --> ExternalGit[GitHub]
    end
    
    subgraph Tenant Isolation [Namespaces: tenant-*]
        Pod1[Tenant Pods]
        Pod1 -- Restricted by NetworkPolicy --> Public
    end
    
    ESO -- IRSA --> SecretsManager[AWS Secrets Manager]
```
''',
    '06-deployment-flow-diagram.md': '''# Deployment Flow Diagram

```mermaid
stateDiagram-v2
    [*] --> Queued: API Request
    Queued --> Building: Worker picks up
    Building --> Deploying: Build succeeds
    Deploying --> Verifying: Manifests applied
    Verifying --> Running: Pods ready
    
    Queued --> DLQ: Max retries
    Building --> Retry: Build fails
    Deploying --> Retry: Deploy fails
    Retry --> Queued: Backoff expired
    Retry --> DLQ: Max retries exceeded
```
''',
    '07-repository-structure-plan.md': '''# Repository Structure Plan

```text
DeployHub/
├── api/              # API server
├── worker/           # Deployment queue worker
├── builder/          # Build system (Buildpacks + Dockerfile fallback)
├── controller/       # Reconciliation engine
├── gateway/          # Gateway API config and HTTPRoute templates
├── infra/            # Kubernetes manifests, Helm charts, Karpenter config
├── observability/    # Prometheus rules, Grafana dashboards, SLO definitions
├── docs/             # ADRs, architecture diagrams, runbooks, threat model
│   ├── adr/
│   └── architecture/
└── scripts/          # Developer tooling, local setup
```
'''
}

adr_files = {
    '0001-queue-system.md': '''# ADR 0001: Queue System

**Status:** PROPOSED (Awaiting ACCEPTED)
**Context:** We need a robust queueing system to handle deployment requests asynchronously.
**Decision:** We will use Redis Streams. We will NOT use Redis Lists or BLPOP. Consumer groups will be utilized with explicit ACK support, retry handling, a Dead Letter Queue (DLQ), and pending message recovery. 
**Consequences:** 
- Ensures exactly-once behavior at the application level.
- Provides native support for consumer groups and failure tracking.
**Conflict Resolution Policy:** Any implementation attempting to use alternative queues or Redis Lists will be rejected.
''',
    '0002-database-design.md': '''# ADR 0002: Database Design

**Status:** PROPOSED (Awaiting ACCEPTED)
**Context:** We need a primary database to serve as the Source of Truth for desired state. 
**Decision:** We will use MongoDB. PostgreSQL or any other relational databases are explicitly forbidden. Schema will be designed to avoid BSON document limit (16MB). Build logs will be stored in S3, not MongoDB.
**Consequences:** 
- Allows flexible schema evolution for project configurations.
- Requires careful query design and projection to avoid excessive memory usage.
**Conflict Resolution Policy:** Implementations using embedded large documents (e.g. logs) will be rejected. 
''',
    '0003-networking-layer.md': '''# ADR 0003: Networking Layer

**Status:** PROPOSED (Awaiting ACCEPTED)
**Context:** We need to expose tenant workloads safely and dynamically.
**Decision:** We will use the Gateway API with Envoy Gateway. NodePort services will NOT be used under any circumstances. HTTPRoutes will be dynamically generated and cleaned up per deployment.
**Consequences:** 
- Adopts the modern standard for Kubernetes ingress routing.
- Eliminates port conflicts and improves security boundaries.
**Conflict Resolution Policy:** Any PR introducing Ingress objects or NodePort services will be rejected.
''',
    '0004-multi-tenancy-model.md': '''# ADR 0004: Multi-Tenancy Model

**Status:** PROPOSED (Awaiting ACCEPTED)
**Context:** The platform must host multiple distinct projects securely.
**Decision:** We adopt a strict Namespace-per-Project isolation model from day one. Shared namespaces will not be utilized. 
**Consequences:** 
- Requires automatic provisioning of Namespaces, ServiceAccounts, ResourceQuotas, LimitRanges, NetworkPolicies, and RBAC per project.
- Guarantees network and quota isolation.
**Conflict Resolution Policy:** Implementations placing multiple tenants in a single namespace will be rejected.
''',
    '0005-build-system.md': '''# ADR 0005: Build System

**Status:** PROPOSED (Awaiting ACCEPTED)
**Context:** We need to convert source code to OCI container images automatically.
**Decision:** We will use Cloud Native Buildpacks as the primary build engine. A Dockerfile build will be used exclusively as a fallback when no buildpack detects the project. 
**Consequences:** 
- Zero-configuration builds for supported runtimes (Node.js, Python, Go, Java, Rust, .NET, PHP).
- Prevents maintenance overhead of custom framework detection logic.
**Conflict Resolution Policy:** Custom detection scripts will be rejected. Fallback logic must only execute if buildpacks return zero matches.
''',
    '0006-reconciliation-engine.md': '''# ADR 0006: Reconciliation Engine

**Status:** PROPOSED (Awaiting ACCEPTED)
**Context:** We must ensure the runtime state in Kubernetes matches our intended state.
**Decision:** We will build a continuous reconciliation controller that treats MongoDB as the absolute source of truth. It will detect drift every 60 seconds and auto-correct it.
**Consequences:** 
- Kubernetes state is never authoritative. 
- Manual `kubectl` edits will be automatically reverted.
**Conflict Resolution Policy:** Any subsystem treating Kubernetes as the source of truth will be rejected.
''',
    '0007-observability-stack.md': '''# ADR 0007: Observability Stack

**Status:** PROPOSED (Awaiting ACCEPTED)
**Context:** The platform requires metrics, alerts, and dashboards.
**Decision:** We will use Prometheus for metrics, Grafana for visualization, and S3 for long-term log storage. High cardinality labels (e.g. dynamic paths or pod names) are strictly forbidden.
**Consequences:** 
- Ensures Prometheus remains performant at scale.
- Aggregated metrics will be used for SLO monitoring.
**Conflict Resolution Policy:** Any metrics containing unbound high cardinality labels will be rejected during code review.
''',
    '0008-secret-management.md': '''# ADR 0008: Secret Management

**Status:** PROPOSED (Awaiting ACCEPTED)
**Context:** Applications require sensitive configurations (API keys, DB credentials).
**Decision:** Centralized secret management via AWS Secrets Manager. External Secrets Operator (ESO) will sync these into per-tenant Kubernetes Secrets. 
**Consequences:** 
- Secrets are never hardcoded or stored in MongoDB.
- Provides a centralized audit trail via AWS.
**Conflict Resolution Policy:** Secrets passed as plaintext environment variables or embedded in Git will be rejected.
'''
}

for name, content in arch_files.items():
    with open(ARCH_DIR / name, 'w', encoding='utf-8') as f:
        f.write(content)

for name, content in adr_files.items():
    with open(ADR_DIR / name, 'w', encoding='utf-8') as f:
        f.write(content)

print("Created all Phase 0 architectural documents.")
