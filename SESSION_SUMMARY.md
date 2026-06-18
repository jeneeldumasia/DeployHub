# ShipZen — Session Summary & Checkpoint

> **ATTENTION FOR NEXT SESSION:** Read this entire document before writing any code or making architectural changes.

---

## Project Context
- **Owner:** Jeneel (student)
- **Domain:** `jeneeldumasia.codes` — platform served at `shipzen.jeneeldumasia.codes`
- **DNS pattern:** `{dep-id}.{project}.shipzen.jeneeldumasia.codes` per deployment
- **AWS Credits:** ~$134 remaining. Infra torn down after every session.
- **Node type:** `m7i-flex.large` (EKS 1.36, AL2023). t3.medium caused lag.
- **Cost:** ~$0.40–0.50/hr base when cluster is live.
- **Repo:** `github.com/jeneeldumasia/ShipZen`
- **State backend:** HCP Terraform (`jeneel-shipzen` org, `shipzen-prod` workspace)

---

## What Has Been Built

### Backend Services
- **API** (`api/`) — FastAPI, 10 endpoints. User inputs repo URL only; platform auto-generates image URI.
- **Worker** (`worker/`) — Redis Streams consumer, state machine (Queued→Building→Deploying→Verifying→Running→Failed/DLQ), retry with exponential backoff.
- **Controller** (`controller/`) — Reconciliation loop, K8s namespace provisioning via Python client, drift detection.
- **Builder** (`builder/`) — Cloud Native Buildpacks (`pack --publish`). Kaniko removed (incompatible with rootless). Build logs streamed to S3.
- **Schema** (`api/schema.sql`) — PostgreSQL. Tables: `projects`, `deployments`, `builds`, `audit_logs`.

### Infrastructure
- **Terraform** provisions: VPC, EKS 1.36, EBS CSI addon (IRSA), ECR, S3 (build logs, encrypted), Karpenter, KEDA, ESO, cert-manager, ALB Controller, kube-prometheus-stack, ArgoCD, Redis (Bitnami), PostgreSQL (Bitnami).
- **ArgoCD** syncs `infra/` — controller, worker, API, builder, scale, secrets, schema Job.
- **Karpenter** — builder NodePool (tainted `shipzen.io/dedicated=builder`) + tenant NodePool (tainted `shipzen.io/dedicated=tenant`). Nodes are isolated.
- **Gateway** — Envoy Gateway, wildcard TLS on `*.shipzen.jeneeldumasia.codes`, HTTP→HTTPS redirect.
- **Observability** — PrometheusRules, Grafana ConfigMap dashboards, ServiceMonitors for all platform services.
- **CI/CD** — `deploy.yaml` (plan + apply), `destroy.yaml` (safe teardown), `auto-destroy.yaml` (4h deadman switch).

### UI (`ui/`)
- Next.js 14 App Router, Tailwind CSS, TypeScript, `lucide-react`, `clsx`/`tailwind-merge`
- Dark sidebar layout, custom design tokens, StatusBadge with animated dots, MetricCard, EmptyState, PageHeader
- Pages: Dashboard, Projects, New Project, Project Detail, Deploy Form, Deployment Detail (with visual pipeline tracker + 4s auto-refresh)
- Deploy form: user inputs repo URL + branch only. Port in collapsed Advanced section.

### Local testing
- `docker compose up --build` → postgres + redis + api at `localhost:8000`
- `npm run dev` in `ui/` → dashboard at `localhost:3000`
- All 13 API smoke tests pass

---

## Current Pipeline Status

**Last run: IN PROGRESS / SUCCESS**

**Issues Fixed This Session (June 18/19):**
- **GitHub Actions IAM Role:** Added `eks:DescribeCluster` permission to `ShipZenGitHubActionsRole` so the deployment pipeline can securely update `kubeconfig`.
- **UI Background Image:** Migrated from raw `<img>` to Next.js `<Image>` for `auth_bg.png` to fix hydration bugs and ensure priority loading.
- **Worker Crash on Pending Messages:** The queue consumer crashed because `redis-py`'s `xautoclaim` returns 3 elements instead of 2. Fixed python unpacking bug and synced the cluster to the latest `sha-88e93b4` image.
- **Builder IAM Permissions:** The builder pod crashed on `pack --publish` due to AWS `AccessDenied`. Patched `shipzen-builder-sa` ServiceAccount to set `automount_service_account_token = true` in `terraform/main.tf`, allowing the builder to assume the `ShipZenBuilderRole` via IRSA to push logs to S3 and images to ECR.

---

## Known Issues & Warnings

**Non-blocking warnings (safe to ignore):**
- `resolve_conflicts` deprecated on `aws_eks_addon` — this is from the upstream `terraform-aws-modules/eks` module, not our code. Will be fixed when the module releases a new version.

**Still outstanding (see `docs/TASKS.md` for full backlog):**

| ID | Priority | Issue |
|----|----------|-------|
| OBS-1 | P1 | Per-pod monitoring not wired up (PodMonitor per tenant namespace) |
| OBS-2 | P1 | Grafana dashboards reference non-existent metrics — need rewriting |
| OBS-3 | P1 | Missing `shipzen_deployment_success_total`, `_failure_total`, `build_duration_seconds` metrics |
| FEAT-3 | P2 | GitHub Webhook → auto-deploy not implemented |
| SEC-1 | P2 | Re-enable `node-exporter` by creating a fine-grained Kyverno `PolicyException`. |
| UI-1 | P2 | Deployment detail timeline doesn't visually indicate a `Failed` state, leaving it looking "stuck" on Queued or Building. |

---

## Next Session

1. **Test E2E Deployment** with a valid public repository to ensure builder succeeds end-to-end.
2. Implement Kyverno `PolicyException` for `node-exporter`.
3. Add a red "Failed" visual state to the UI timeline so failed builds are clearly visible.
4. Clean up scratch files (`check_db.*`, `republish_stuck.py`).

---

*Last updated: 2026-06-19. Resolved UI auth image, GitHub Actions IAM role, Redis xautoclaim unpacking bug, and Builder IRSA token mount.*
