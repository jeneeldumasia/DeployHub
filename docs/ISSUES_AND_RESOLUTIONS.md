# ShipZen Issue Tracker & Resolutions

This document serves as a historical record of all bugs, architectural hurdles, and operational issues faced while building ShipZen. It details what the problem was, how it was overcome, whether the solution was successful, and outlines the current technical debt that remains outstanding.

---

## 🟢 Resolved Issues (Historical)

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

---

## 🔴 Current Outstanding Issues (Technical Debt)

These issues are currently active in the codebase and pose significant risks to production stability.

### 1. Database Connection Leaks in API
* **Issue:** The FastAPI application does not use a connection pool. Every request calls `psycopg2.connect()` and the context manager only commits the transaction, it does **not** close the connection.
* **Risk:** Under high load, PostgreSQL will rapidly hit its `max_connections` limit, causing total platform outage.
* **Proposed Fix:** Implement `psycopg2.pool.ThreadedConnectionPool` or migrate to `asyncpg` with a proper connection pool.

### 2. Controller Cannot Update Existing Deployments
* **Issue:** The Controller's reconciliation loop uses a function that only *creates* Kubernetes resources. If a resource already exists (e.g., when deploying a newer image tag for an existing project), the Kubernetes API returns a 409 Conflict which the controller silently ignores.
* **Risk:** Rolling updates do not work. Users cannot update an existing deployment's image, port, or environment variables.
* **Proposed Fix:** Modify the Controller to apply a `patch` on 409 Conflict instead of failing silently.

### 3. Environment Variables (Secrets Manager) Path Mismatch
* **Issue:** The API saves user environment variables to AWS Secrets Manager under the path `shipzen/{project_name}/`. However, the Controller provisions `ExternalSecret` manifests that look for `shipzen/{project_name}/{deployment_uuid}`.
* **Risk:** Environment variables are completely broken and will never be injected into tenant pods.
* **Proposed Fix:** Align the paths. The Controller should read from the project-level secret instead of the deployment-level secret.

### 4. ECR Pull Token is Never Rotated
* **Issue:** The Terraform configuration provisions an AWS Secrets Manager secret for the ECR pull token but hardcodes it to `"placeholder"`. AWS ECR tokens expire every 12 hours.
* **Risk:** After 12 hours of the platform being alive, tenant pods will fail to start or restart, throwing `ImagePullBackOff` errors because Kubernetes will no longer be authenticated to pull from ECR.
* **Proposed Fix:** Implement a cronjob or AWS Lambda function to automatically rotate the token in Secrets Manager every 6-8 hours.

### 5. Builder Ignores Branch Parameter
* **Issue:** The `CreateDeploymentRequest` model accepts a `branch` parameter, but it is never passed through Redis to the Builder. The Builder always executes `git clone --depth=1 repo_url`, pulling the default branch.
* **Risk:** Users attempting to deploy from a specific staging or development branch will silently have their `main` branch deployed instead.
* **Proposed Fix:** Ensure the API includes `branch` in the Redis Stream payload and have the Builder use it during the `git clone` execution.

### 6. Redis Streams Lack End-to-End Guarantees
* **Issue:** The system uses two separate streams (`deploy_stream` and `builder_queue`). The Worker ACKs the message from the first stream *after* adding it to the second. If the Builder crashes and never ACKs the message from `builder_queue`, it gets stuck forever.
* **Risk:** Build tasks can be permanently lost if the Builder pod crashes unexpectedly.
* **Proposed Fix:** Implement a pending-message recovery loop (similar to the Worker) inside the Builder to re-claim stalled messages.
