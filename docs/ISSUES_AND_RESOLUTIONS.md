# Issues and Resolutions

This document tracks recently encountered infrastructure, deployment, and UI issues along with their resolutions.

## Infrastructure & CI/CD

### 1. Manual Pod Restarts Required for GitOps Deployments
- **Issue:** ArgoCD was not detecting new Docker images pushed by the GitHub Actions pipeline because the deployment manifest was hardcoded to use the `latest` tag. The Git manifests themselves were never changing, meaning ArgoCD saw the cluster state as "Synced" and didn't trigger a rollout.
- **Resolution:** Modified `.github/workflows/build-push.yaml` to include an automated tagging step. The pipeline now extracts the `sha-xxxxxx` tag from the build, uses a Python script to rewrite `newTag` in `infra/kustomization.yaml`, and automatically commits the change back to the repository using a retry-rebase loop to avoid parallel matrix merge conflicts. ArgoCD now detects the commit and auto-syncs.

### 2. Builder Pods Stuck in "Building" (KEDA Autoscaling Failure)
- **Issue:** KEDA was failing to scale the `shipzen-builder` pods from `0` to `1`. The logs showed an error attempting to mount `shipzen-db-credentials` and `shipzen-s3-config`. Terraform created these secrets in `shipzen-system`, but the builder runs in the isolated `shipzen-build` namespace, triggering a cross-namespace secret mount failure.
- **Resolution:** Updated `terraform/postgres.tf` to provision duplicate `kubernetes_secret` resources injected directly into the `shipzen-build` namespace. For immediate recovery, used `kubectl` to manually copy the secrets over, unblocking the stuck pods instantly.

### 3. Terraform "gavinbunney/kubectl" 500 Internal Server Error
- **Issue:** The GitHub Actions infrastructure pipeline was crashing during `terraform init` with a 500 API rate-limit error when fetching the legacy `gavinbunney/kubectl` provider checksums.
- **Resolution:** Investigated the Terraform configuration and confirmed that `kubectl_manifest` was completely unused (the project relies on `local-exec` bash provisioners for kubectl commands). Removed the unused legacy provider from `main.tf` entirely, allowing the pipeline to bypass the dependency block.

## Frontend & Observability

### 4. Grafana Dashboards Not Found (404 Error)
- **Issue:** Clicking "View Metrics" in the UI redirected to `/d/pod-health`, but Grafana showed a "Dashboard not found" error. The dashboard config map existed in `observability/dashboards` but was never applied by ArgoCD. Additionally, the dashboard JSON models were missing explicit `uid` fields, causing Grafana to auto-generate random UIDs instead.
- **Resolution:** Injected `"uid": "pod-health"` (and similar UIDs) into the JSON payloads in `grafana-dashboards.yaml`. Copied the ConfigMap into `infra/system/grafana-dashboards.yaml` and added it to the ArgoCD kustomization list so it automatically deploys to the cluster.

### 5. Invisible Brand Logo in Dark Mode
- **Issue:** The ShipZen rocket logo was hardcoded with `text-white` over `bg-brand`. In dark mode, `bg-brand` flips to white, making the logo completely invisible.
- **Resolution:** Replaced all instances of `text-white` placed over `bg-brand` with the semantic `text-canvas-bg` utility. This ensures the text color elegantly inverts to pure black when dark mode switches the background to white.

### 6. Default Vercel Favicon
- **Issue:** The website browser tab was displaying the default boilerplate Next.js/Vercel triangle logo.
- **Resolution:** Generated a new, minimalist white rocket icon on a solid black background using the image generator tool. Replaced `favicon.ico` with the new `icon.png` in `ui/src/app` to apply the ShipZen branding to the browser tab.
