provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name]
    }
  }
}

resource "helm_release" "argocd" {
  name             = "argocd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  namespace        = "argocd"
  create_namespace = true
  version          = "5.51.6"

  depends_on = [module.eks]
}

# The GitOps Application: Instructs ArgoCD to sync the DeployHub repo into the cluster
resource "helm_release" "deployhub_gitops_app" {
  name      = "deployhub-gitops"
  chart     = "deployhub-gitops" # Dummy chart name if we were to build one, or raw manifests
  # For raw manifests, typically ArgoCD uses the `Application` CRD. 
  # We can deploy the Application CRD via helm or kubectl.
  
  repository = "https://argoproj.github.io/argo-helm" # Placeholder, we will use raw manifest for ArgoCD Application below
  
  depends_on = [helm_release.argocd]
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name]
  }
}

resource "kubernetes_manifest" "deployhub_argocd_app" {
  manifest = {
    apiVersion = "argoproj.io/v1alpha1"
    kind       = "Application"
    metadata = {
      name      = "deployhub-platform"
      namespace = "argocd"
    }
    spec = {
      project = "default"
      source = {
        repoURL        = "https://github.com/jeneeldumasia/DeployHub.git"
        targetRevision = "HEAD"
        path           = "infra" # Or wherever the main kustomization/helm chart lives
      }
      destination = {
        server    = "https://kubernetes.default.svc"
        namespace = "default"
      }
      syncPolicy = {
        automated = {
          prune    = true
          selfHeal = true
        }
      }
    }
  }

  depends_on = [helm_release.argocd]
}
