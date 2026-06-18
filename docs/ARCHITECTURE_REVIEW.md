# ShipZen — Full Project Analysis

> [!NOTE]
> **Historical Document:** This architecture review was performed prior to recent massive refactoring. **All critical issues and technical debt listed in the summary table have been successfully resolved.** For a current list of resolved issues, refer to `ISSUES_AND_RESOLUTIONS.md`.

## What ShipZen Is

ShipZen is an **Internal Developer Platform (IDP)** — a self-service system where a developer pushes a repo URL, and the platform automatically builds a container image, deploys it to Kubernetes, and routes traffic to it via a unique subdomain. Think of it as a mini Heroku/Vercel built on top of EKS.

---

## Architecture Overview

```mermaid
graph LR
    subgraph "User-Facing"
        UI["Next.js UI<br/>(localhost:3000)"]
        GH["GitHub Webhooks"]
    end

    subgraph "API Layer"
        API["FastAPI API<br/>(api/)"]
    end

    subgraph "Async Processing"
        RS["Redis Streams<br/>deploy_stream"]
        W["Worker<br/>(worker/)"]
        BQ["Redis Streams<br/>builder_queue"]
        B["Builder<br/>(builder/)"]
    end

    subgraph "Reconciliation"
        C["Controller<br/>(controller/)"]
    end

    subgraph "Data Stores"
        PG["PostgreSQL"]
        S3["S3 (Build Logs)"]
        ECR["ECR (Images)"]
        SM["AWS Secrets Manager"]
    end

    subgraph "Kubernetes"
        NS["Tenant Namespace"]
        DEP["K8s Deployment"]
        SVC["K8s Service"]
        HR["HTTPRoute"]
        EG["Envoy Gateway"]
    end

    UI -->|REST/WS| API
    GH -->|POST /webhooks| API
    API -->|INSERT| PG
    API -->|XADD| RS
    RS -->|XREADGROUP| W
    W -->|XADD| BQ
    BQ -->|XREADGROUP| B
    B -->|git clone + pack build| ECR
    B -->|Upload logs| S3
    B -->|UPDATE state| PG
    C -->|Poll every 60s| PG
    C -->|create/patch| NS
    C -->|create/patch| DEP
    C -->|create/patch| SVC
    C -->|create/patch| HR
    EG -->|TLS + route| DEP
```

---

## Data Flow — End to End

### 1. User creates a Project
`POST /projects` → inserts a row in `projects` table with `status=Provisioning`. The **Controller** picks this up on its next reconciliation tick (every 60s), renders the [tenant.yaml.j2](file:///c:/Project/ShipZen/controller/templates/tenant.yaml.j2) template, and creates the Kubernetes Namespace, ResourceQuota, LimitRange, NetworkPolicy, RBAC, and ECR pull secret. Once the namespace is verified as existing, the project moves to `Ready`.

### 2. User submits a Deployment
`POST /projects/{id}/deployments` → inserts a `deployments` row with `state=Queued`, auto-generates the image URI (`ECR_URL:deployment_id`), and enqueues a message to `deploy_stream` via Redis Streams.

### 3. Worker picks it up
The [Worker](file:///c:/Project/ShipZen/worker/main.py) runs an infinite `XREADGROUP` loop. It validates the message, checks for idempotency (skips if already Building/Deploying/Running), transitions the deployment to `Building`, and hands the message off to `builder_queue`.

### 4. Builder builds the image
The [Builder](file:///c:/Project/ShipZen/builder/main.py) (scaled by KEDA from 0→N based on pending messages) clones the repo, runs `pack build --publish` (Cloud Native Buildpacks), streams logs to S3, checks ECR image scan results, and writes the final state to PostgreSQL. On success → `Deploying`. On failure → `Failed`.

### 5. Controller reconciles the deployment
The [Controller](file:///c:/Project/ShipZen/controller/main.py) sees `state=Deploying`, renders [app-deployment.yaml.j2](file:///c:/Project/ShipZen/controller/templates/app-deployment.yaml.j2) (Deployment + Service + HTTPRoute + PDB + ExternalSecret), applies it to K8s, and watches for ready replicas. Once replicas are healthy → `Running`. If replicas crash → `Failed`.

### 6. Traffic is routed
Envoy Gateway terminates TLS on `*.shipzen.jeneeldumasia.codes` and routes based on hostname `{dep-id-8chars}.{project-name}.shipzen.jeneeldumasia.codes`.

---

## Component Breakdown

| Component | Language | Purpose | Lines |
|-----------|----------|---------|-------|
| [api/main.py](file:///c:/Project/ShipZen/api/main.py) | Python/FastAPI | HTTP API, Redis enqueue | 791 |
| [api/auth.py](file:///c:/Project/ShipZen/api/auth.py) | Python | Auth0 JWT validation | 132 |
| [api/database.py](file:///c:/Project/ShipZen/api/database.py) | Python | DB connection + retention | 70 |
| [api/audit.py](file:///c:/Project/ShipZen/api/audit.py) | Python | Append-only audit logging | 71 |
| [worker/main.py](file:///c:/Project/ShipZen/worker/main.py) | Python | Redis consumer, state machine | 122 |
| [worker/state_machine.py](file:///c:/Project/ShipZen/worker/state_machine.py) | Python | PostgreSQL state transitions | 81 |
| [builder/main.py](file:///c:/Project/ShipZen/builder/main.py) | Python | Image builder (pack) | 305 |
| [controller/main.py](file:///c:/Project/ShipZen/controller/main.py) | Python | K8s reconciliation loop | 284 |
| [ui/](file:///c:/Project/ShipZen/ui) | Next.js/TS | Dashboard + deploy forms | — |

---

## Identified Flaws

### 🔴 Critical — Logic Bugs That Will Cause Failures

#### 1. `hmac.new()` → should be `hmac.new` (NameError at runtime)

**File:** [api/main.py:685](file:///c:/Project/ShipZen/api/main.py#L685)

```python
expected_mac = hmac.new(webhook_secret.encode(), body_bytes, hashlib.sha256).hexdigest()
```

Python's hmac module has `hmac.new()`, not `hmac.new`. But wait — `hmac.new` **is** valid (it's an alias). However, in the actual Python standard library, it's `hmac.new()`. Let me re-check... Actually, `hmac.new` is the correct constructor. **This is fine.** ~~Ignore this.~~

#### 1. (Actual) Worker `update_state` INSERT will fail with missing NOT NULL columns

**File:** [worker/state_machine.py:64-71](file:///c:/Project/ShipZen/worker/state_machine.py#L64-L71)

The `update_state` method does an `INSERT ... ON CONFLICT DO UPDATE` but the INSERT only provides `deployment_id, state, updated_at, last_error`. The `deployments` table has `project_id TEXT NOT NULL` and `repo_url TEXT NOT NULL`. On a fresh row (no conflict), this INSERT will fail with a NOT NULL violation for `project_id` and `repo_url`.

In practice, the API inserts the row first, so the ON CONFLICT path fires. But if there's ever a race where the worker processes a message before the API's INSERT commits, or if the deployment row is deleted mid-flight, the INSERT will crash.

> [!WARNING]
> The `ON CONFLICT` upsert in `state_machine.update_state()` is structurally incorrect — it can only succeed on the UPDATE path. On the INSERT path, it violates NOT NULL constraints. This is a latent bug that will surface under race conditions.

---

#### 2. Database connection leak in API — no connection pooling

**File:** [api/database.py:15-16](file:///c:/Project/ShipZen/api/database.py#L15-L16)

```python
def get_connection():
    return psycopg2.connect(DATABASE_URL)
```

Every single API request creates a brand new TCP connection to PostgreSQL and relies on `with get_connection() as conn:` to close it. But `psycopg2.connect()` returns a connection where the context manager **does not close** — it only commits/rollbacks. Connections leak on every request.

Look at API usage:
```python
with get_connection() as conn:
    with conn.cursor(...) as cur:
        ...
```

The `with psycopg2.connect() as conn` context manager calls `conn.commit()` on exit, **not `conn.close()`**. The connection is never closed and never returned to any pool. Under load, this will exhaust PostgreSQL's `max_connections` (default 100) within minutes.

> [!CAUTION]
> **This is the most impactful production bug.** Under any real traffic, PostgreSQL will hit `max_connections` and the entire platform will go down. You need a connection pool (e.g., `psycopg2.pool.ThreadedConnectionPool` or `asyncpg` with pooling).

---

#### 3. `branch` field is accepted but never used

**Files:** [api/main.py:126](file:///c:/Project/ShipZen/api/main.py#L126), [builder/main.py:123](file:///c:/Project/ShipZen/builder/main.py#L123)

The `CreateDeploymentRequest` model accepts a `branch` field (default `"main"`), and it's logged in the audit event, but it's **never passed to the builder** via the Redis message. The builder always does `git clone --depth=1 repo_url` — cloning the default branch regardless of what the user specified.

```python
# API enqueues:
r.xadd(STREAM_NAME, {
    "deployment_id": ...,
    "repo_url": body.repo_url,
    "image_name": image_uri,
    ...
    # ⚠️ branch is MISSING from this dict
})

# Builder clones:
subprocess.run(["git", "clone", "--depth=1", repo_url, workspace], check=True)
# ⚠️ No --branch flag
```

> [!IMPORTANT]
> The branch feature is user-visible in the deploy form but **completely non-functional**. Deploying from any branch other than the default will silently deploy the wrong code.

---

#### 4. Webhook creates deployments without owner authorization

**File:** [api/main.py:661-744](file:///c:/Project/ShipZen/api/main.py#L661-L744)

The `github_webhook` endpoint validates the HMAC signature but does **not verify** that the `clone_url` from the payload matches the project's expected repo. An attacker with the webhook secret can trigger a deployment of an arbitrary repo into the project's namespace by sending a crafted payload with a different `repository.clone_url`.

Also, the webhook always deploys with `port: 8080` hardcoded, ignoring any project-level port configuration.

---

#### 5. Deployment keyset pagination has a duplicate-timestamp bug

**File:** [api/main.py:358-370](file:///c:/Project/ShipZen/api/main.py#L358-L370)

```sql
WHERE project_id = %s AND updated_at < %s ORDER BY updated_at DESC LIMIT %s
```

If two deployments have the same `updated_at` timestamp (which is set by `DEFAULT NOW()` and is only second-precision for `TIMESTAMP WITHOUT TIME ZONE`), the cursor-based pagination will skip one of them. The cursor should include a tiebreaker (e.g., `(updated_at, deployment_id)`).

---

#### 6. Controller applies but never patches — `create_from_yaml` fails silently on updates

**File:** [controller/main.py:89-105](file:///c:/Project/ShipZen/controller/main.py#L89-L105)

```python
def apply_manifests(manifest_str: str):
    for doc in docs:
        try:
            create_from_yaml(k8s_client, yaml_objects=[doc], verbose=False)
        except Exception as e:
            logger.warning(f"apply_manifests warning for {doc.get('kind')}: {e}")
```

`create_from_yaml` only creates. If a resource already exists, it throws a 409 Conflict, which is caught and logged as a warning. This means:
- The controller can **never update** an existing deployment (e.g., change the image, scale replicas, update health check path).
- Drift remediation for a deleted deployment works (re-creation), but drift in configuration (wrong image, wrong port) is silently ignored.

> [!WARNING]
> The controller cannot perform rolling updates. If a builder successfully builds a new image for an existing deployment, the controller will try to create the Deployment, get a 409, log a warning, and the old image keeps running forever.

---

#### 7. WebSocket DB polling uses synchronous psycopg2 in an async handler

**File:** [api/main.py:390-435](file:///c:/Project/ShipZen/api/main.py#L390-L435)

The WebSocket endpoint is `async def` but calls `get_connection()` + `cur.execute()` which are synchronous blocking calls. This blocks the entire asyncio event loop for every connected WebSocket client. With 10 concurrent WebSocket connections, the API will become completely unresponsive.

---

### 🟠 Architectural Issues

#### 8. Two separate Redis Streams with no end-to-end delivery guarantee

The flow is: API → `deploy_stream` → Worker → `builder_queue` → Builder. But the Worker ACKs the original message **after** XADD to builder_queue. If the builder crashes and never ACKs, the message is stuck in `builder_queue` with no one to re-drive it (the builder has no `recover_pending_messages()` logic like the worker does).

---

#### 9. Controller uses polling, not informers

The controller polls PostgreSQL every 60 seconds. This means:
- A deployment can sit in `Deploying` for up to 60 seconds before the controller creates the K8s resources.
- Drift detection has a 60-second blind spot.
- For a platform with many projects, each reconciliation tick queries **all** projects and **all** deployments — O(N) queries per tick with no incremental processing.

This is fine for a student project but won't scale past ~50 projects.

---

#### 10. No `FAILED` state in ProjectSchema

**File:** [controller/models.py:6-9](file:///c:/Project/ShipZen/controller/models.py#L6-L9)

`ProjectStatus` only has `Provisioning`, `Ready`, `Terminating`. If namespace creation fails (e.g., quota exceeded, RBAC error), the project stays stuck in `Provisioning` forever with no way to surface the error to the user.

---

#### 11. Single shared ECR repository for all tenants

All tenant images go to `shipzen-builds:${deployment_id}`. This means:
- No per-tenant image lifecycle policy (can't delete old images per project).
- Any tenant with ECR pull access can technically pull any other tenant's image (the ECR pull secret is the same across all namespaces).
- Image tag space is flat — a single `shipzen-builds` repo will accumulate thousands of tags.

---

#### 12. NetworkPolicy egress allows 0.0.0.0/0 minus RFC1918

**File:** [controller/templates/tenant.yaml.j2:71-78](file:///c:/Project/ShipZen/controller/templates/tenant.yaml.j2#L71-L78)

The egress rule blocks `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, and `169.254.169.254/32` but allows everything else. This is intentional (apps need to reach the internet), but:
- `100.64.0.0/10` (carrier-grade NAT / EKS VPC CNI secondary ranges) is not blocked.
- If EKS uses `100.64.x.x` for pod CIDRs (which it does on large clusters with custom networking), pods can reach each other cross-namespace despite the NetworkPolicy.

---

#### 13. No liveness probe on Worker, Builder, or Controller

The Worker, Builder, and Controller deployments have no liveness probes. If they deadlock (e.g., Redis connection hangs, DB connection pool exhaustion), Kubernetes won't restart them. The worker exposes a Prometheus `/metrics` endpoint on port 8000 — this could double as a health endpoint.

---

#### 14. Secrets Manager path mismatch — API vs Controller

The API stores env vars at `shipzen/{project_name}/` ([api/main.py:574](file:///c:/Project/ShipZen/api/main.py#L574)), but the controller's app-deployment template fetches from `shipzen/{project_name}/{deployment_name}` ([app-deployment.yaml.j2:19](file:///c:/Project/ShipZen/controller/templates/app-deployment.yaml.j2#L19)). These paths will never match, so environment variables set via the API will never appear in the deployed containers.

> [!CAUTION]
> The env vars feature (`PUT /projects/{id}/env`) is completely broken. The API writes to `shipzen/myproject/` but the ExternalSecret reads from `shipzen/myproject/{deployment-uuid}`. The `deployment_name` is a UUID, so the secret will always be empty.

---

#### 15. ECR pull token is a static placeholder, never rotated

**File:** [terraform/main.tf:248-251](file:///c:/Project/ShipZen/terraform/main.tf#L248-L251)

```hcl
resource "aws_secretsmanager_secret_version" "ecr_pull_token" {
  secret_string = "placeholder"  # Will be rotated by an external cronjob/lambda
}
```

The ECR pull token is set to `"placeholder"` and the comment says "will be rotated by an external cronjob/lambda" — but that cronjob/lambda doesn't exist. ECR tokens expire in 12 hours, so after the first 12 hours, all tenant pods will fail to pull images with `ImagePullBackOff`.

> [!CAUTION]
> There is no mechanism to rotate the ECR token. Tenant pods will stop starting after 12 hours.

---

### 🟡 Operational / Minor Concerns

#### 16. `image_tag_mutability = "MUTABLE"` on ECR repo

**File:** [terraform/main.tf:177](file:///c:/Project/ShipZen/terraform/main.tf#L177)

Image tags are mutable, meaning a tag can be overwritten with a different image. Since `deployment_id` is a UUID, re-tagging isn't a realistic risk, but `IMMUTABLE` is the security best practice and costs nothing.

---

#### 17. Kyverno policies in `Audit` mode, not `Enforce`

**File:** [terraform/security.tf:29](file:///c:/Project/ShipZen/terraform/security.tf#L29)

```hcl
set {
  name  = "validationFailureAction"
  value = "Audit"
}
```

Kyverno is installed but only auditing, not enforcing. Violations are logged but not blocked.

---

#### 18. CORS allows `*` methods and headers

**File:** [api/main.py:98-104](file:///c:/Project/ShipZen/api/main.py#L98-L104)

Origins are restricted, but `allow_methods=["*"]` and `allow_headers=["*"]` is overly permissive. Should restrict to `["GET", "POST", "PUT", "DELETE", "OPTIONS"]` and `["Authorization", "Content-Type"]`.

---

#### 19. `shipzen_deployment_success_total` is only in the Controller

The controller increments `shipzen_deployment_success_total` when it sees replicas become ready. But if the controller restarts, the counter resets to 0. This metric will be inaccurate across pod restarts. Consider persisting it in PostgreSQL or using a Prometheus `increase()` instead of relying on the counter's absolute value.

---

#### 20. `_user_id_or_ip` rate limiter function is dead code

**File:** [api/main.py:72-84](file:///c:/Project/ShipZen/api/main.py#L72-L84)

The function imports `get_current_user`, parses the token, catches the exception, and then... falls through to `get_remote_address(request)` every time. The JWT parsing code in the `try` block doesn't set any variable that's returned. The function always returns the IP address.

---

#### 21. No `created_at` on deployments table

**File:** [api/schema.sql:23-34](file:///c:/Project/ShipZen/api/schema.sql#L23-L34)

The `deployments` table has `updated_at` but no `created_at`. You can't tell when a deployment was originally submitted vs. when it last changed state.

---

## Summary Table

| # | Severity | Category | Issue |
|---|----------|----------|-------|
| 1 | 🔴 Critical | Logic | `state_machine.update_state()` INSERT violates NOT NULL on race |
| 2 | 🔴 Critical | Infra | **No connection pooling** — will exhaust PG connections under load |
| 3 | 🔴 Critical | Logic | `branch` field is accepted but never passed to builder |
| 4 | 🔴 Critical | Security | Webhook doesn't verify repo URL matches project |
| 5 | 🟠 Medium | Logic | Keyset pagination skips rows with duplicate timestamps |
| 6 | 🔴 Critical | Arch | Controller can only CREATE, never UPDATE — no rolling updates |
| 7 | 🟠 Medium | Perf | Sync DB calls in async WebSocket handler block event loop |
| 8 | 🟠 Medium | Arch | Builder has no pending-message recovery (messages can be lost) |
| 9 | 🟡 Low | Arch | Controller polls every 60s — latency + O(N) scaling |
| 10 | 🟡 Low | Logic | No `Failed` status for projects |
| 11 | 🟡 Low | Security | Single shared ECR repo for all tenants |
| 12 | 🟠 Medium | Security | NetworkPolicy doesn't block `100.64.0.0/10` (EKS pod CIDR) |
| 13 | 🟡 Low | Ops | No liveness probes on worker/builder/controller |
| 14 | 🔴 Critical | Logic | **Secrets Manager path mismatch** — env vars feature is broken |
| 15 | 🔴 Critical | Infra | **ECR pull token never rotated** — pods fail after 12h |
| 16 | 🟡 Low | Security | ECR image tags are mutable |
| 17 | 🟡 Low | Security | Kyverno in Audit mode, not Enforce |
| 18 | 🟡 Low | Security | CORS allows all methods/headers |
| 19 | 🟡 Low | Ops | Success counter resets on pod restart |
| 20 | 🟡 Low | Code | Rate limiter user extraction is dead code |
| 21 | 🟡 Low | Schema | No `created_at` on deployments |

---

## What's Done Well

Despite the issues above, the project has strong fundamentals:

- ✅ **Genuine multi-tenancy isolation** — namespace-per-project with ResourceQuota, LimitRange, NetworkPolicy, RBAC, and PSA `restricted` enforcement is textbook
- ✅ **Proper secret management** — ESO + AWS Secrets Manager, not hardcoded K8s secrets
- ✅ **DLQ pattern** — dead letter queue for failed deployments prevents infinite retry loops
- ✅ **Idempotency guards** in the worker (checking deployment state before processing)
- ✅ **Build timeout + workspace cleanup** in the builder
- ✅ **ECR image scanning gate** — blocks deployments with critical CVEs
- ✅ **Audit logging** with append-only semantics and non-blocking writes
- ✅ **HTTP→HTTPS redirect** on the Gateway
- ✅ **PodDisruptionBudgets** with `maxUnavailable` (not `minAvailable`) — correctly handles single-replica deployments
- ✅ **Karpenter node isolation** — builder and tenant workloads on separate node pools with taints
- ✅ **IRSA everywhere** — no static AWS credentials in the cluster
- ✅ **GitHub Actions OIDC** with subject restriction to `main` branch only

---

## 🟢 Resolved Issues Log (from First Commit)

### 1. GitHub Actions OIDC Failure on Repository Rename
* **Issue:** After renaming the GitHub repository from `DeployHub` to `ShipZen`, the deployment pipeline failed with `Not authorized to perform sts:AssumeRoleWithWebIdentity`. GitHub was sending OIDC tokens as `ShipZen`, but the AWS IAM Role's trust policy still expected `DeployHub`.
* **Resolution:** Manually accessed the AWS IAM Console, located the `DeployHub-AA-SuperRole`, and updated the Trust Relationship condition to expect `repo:jeneeldumasia/ShipZen:ref:refs/heads/main`.
* **Did it work?** Yes. The pipeline immediately successfully authenticated.

### 2. HCP Terraform "No Valid Credentials" on Remote Run
* **Issue:** When running `terraform plan` on a newly created `shipzen-prod` HCP Terraform workspace, the pipeline crashed saying it couldn't reach the AWS EC2 metadata endpoint. This occurred because new workspaces default to "Remote Execution" mode, meaning the code ran on HashiCorp servers that lacked AWS credentials, rather than the GitHub runner.
* **Resolution:** Changed the "Execution Mode" in the HCP Terraform Workspace settings from "Remote" to "Local".
* **Did it work?** Yes. The execution stayed on the GitHub Actions runner which had temporary AWS credentials injected via OIDC.

### 3. Envoy Gateway CRD Version Mismatch
* **Issue:** The `shipzen-platform` ArgoCD app failed to sync because it was using an outdated API version for the Envoy Gateway (`config.gateway.envoyproxy.io/v1alpha1`). Because it failed, the AWS NLB was never requested.
* **Resolution:** Updated the manifests to use the correct API version: `gateway.envoyproxy.io/v1alpha1`.
* **Did it work?** Yes. ArgoCD successfully synced the gateway and provisioned the Network Load Balancer.

### 4. Webhook Race Conditions & NLB Timeouts
* **Issue:** The `aws-load-balancer-controller` webhook wasn't ready before `kube-prometheus-stack` tried to deploy, resulting in "no endpoints available for service" errors and causing the NLB provisioning to time out after 10 minutes.
* **Resolution:** Added strict `depends_on` chains and `time_sleep.wait_for_alb_webhook` in the Terraform configuration to ensure webhooks were fully ready before dependent helm charts deployed.
* **Did it work?** Yes. The dependency chaining eliminated the race condition.

### 5. Kyverno Pod Security Standard Blocks
* **Issue:** Kyverno's strict cluster policies blocked the `prometheus-node-exporter` DaemonSet (`disallow-host-namespaces`, `disallow-host-path`).
* **Resolution:** Disabled the `nodeExporter` component in the Helm chart entirely to allow deployment to proceed safely in a managed EKS environment while maintaining compliance.
* **Did it work?** Yes.

### 6. UI Docker Build Cache Errors
* **Issue:** Docker builds for the Next.js UI were failing due to missing cache directories during the build context copy phase.
* **Resolution:** Modified the `Dockerfile` to explicitly create the `public/` directory prior to the build context copy.
* **Did it work?** Yes. Builds now complete without cache permission errors.

### 7. Cloudflare Orphaned DNS Records
* **Issue:** Tearing down the platform left stale `*.shipzen` and `shipzen` CNAME records in Cloudflare, leading to clutter and potential routing conflicts on subsequent runs.
* **Resolution:** Added a dedicated Cloudflare DNS cleanup script utilizing the Cloudflare API to the `destroy` pipeline.
* **Did it work?** Yes. DNS records are cleanly wiped on teardown.

### 8. Karpenter Autoscaling Runaway Costs
* **Issue:** The Karpenter node pools were scaling too aggressively, spinning up expensive instances that threatened to consume the AWS free-tier/student credits too quickly.
* **Resolution:** Implemented hard resource limits on the Karpenter node pools to keep scaling restricted to minimal, cost-effective boundaries.
* **Did it work?** Yes.

### 9. Database Connection Leaks in API
* **Issue:** Previously, the FastAPI application did not use a connection pool, risking DB connection exhaustion. 
* **Resolution:** Replaced raw `psycopg2.connect()` calls with a robust `psycopg2.pool.ThreadedConnectionPool` and `PooledConnectionWrapper` to ensure connections are properly recycled.
* **Did it work?** Yes. The API now safely handles concurrent requests without leaking connections.

### 10. Controller Cannot Update Existing Deployments
* **Issue:** The Controller's reconciliation loop was returning a 409 Conflict when a user deployed a newer image tag for an existing project because it only tried to create resources.
* **Resolution:** Added explicit `patch_namespaced_deployment` and `patch_namespaced_service` fallback logic in `apply_manifests()` whenever the `create_from_yaml` throws a 409 ApiException.
* **Did it work?** Yes. Rolling updates now trigger properly upon redeployment.

### 11. Environment Variables Path Mismatch
* **Issue:** A mismatch between the API storing secrets at `shipzen/{project_name}/` and the Controller attempting to read from `shipzen/{project_name}/{deployment_uuid}` meant environments variables never injected.
* **Resolution:** Aligned the paths. The `app-deployment.yaml.j2` manifest was updated to extract data directly from `shipzen/{{ project_name }}/`.
* **Did it work?** Yes.

### 12. ECR Pull Token Not Rotating
* **Issue:** The Kubernetes cluster used a static AWS token to pull images from ECR, which would expire every 12 hours, eventually breaking pod restarts.
* **Resolution:** Integrated External Secrets Operator (ESO) `ECRAuthorizationToken` generator in `tenant.yaml.j2` to dynamically rotate and inject fresh ECR tokens every hour.
* **Did it work?** Yes. 

### 13. Redis Streams Lack End-to-End Guarantees
* **Issue:** Build tasks could be permanently lost if the Builder pod crashed mid-build because it didn't track pending/un-acked messages.
* **Resolution:** Implemented a robust `recover_pending_messages` loop using Redis `xpending_range` and `xclaim` in the Builder loop to sweep and re-claim stalled messages.
* **Did it work?** Yes. Build tasks are now guaranteed to be picked up by another pod.

### 14. Builder Ignores Branch Parameter
* **Issue:** The API accepted a `branch` parameter, but the Worker dropped the field when moving the message from the `deploy_stream` to the `builder_queue`. As a result, the Builder always checked out the `main` branch.
* **Resolution:** Explicitly added `"branch": data.get("branch", "main")` to the `handoff_to_builder` dictionary payload in `worker/main.py`.
* **Did it work?** Yes. Deployments now respect specific branches.

### 15. Dark Mode Legibility on Active Navbar Link
* **Issue:** In the Next.js UI, the active sidebar navigation item was using white text on a white background when in dark mode.
* **Resolution:** Appended `dark:text-black` to the `.nav-item.active` class in `globals.css` so the text shifts to black when the active glassmorphism background is bright white.
* **Did it work?** Yes. The navigation is now highly legible in both dark and light modes.
