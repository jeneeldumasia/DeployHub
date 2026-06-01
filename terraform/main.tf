terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.12"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# 1. VPC Configuration (Cost-optimized for student: single NAT gateway)
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "deployhub-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["${var.aws_region}a", "${var.aws_region}b"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = true # Crucial for saving cost

  tags = {
    Environment = "production"
    Project     = "DeployHub"
  }
}

# 2. EKS Cluster Configuration
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = "deployhub-cluster"
  cluster_version = "1.29"

  vpc_id                   = module.vpc.vpc_id
  subnet_ids               = module.vpc.private_subnets
  control_plane_subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access = true

  # Base Node Group for Control Plane and ArgoCD
  eks_managed_node_groups = {
    platform_nodes = {
      min_size     = 1
      max_size     = 3
      desired_size = 2
      instance_types = ["t3.medium"] # Cost effective instance
    }
  }

  enable_cluster_creator_admin_permissions = true
}

# 3. GitHub Actions OIDC Role Configuration
module "iam_github_oidc_role" {
  source    = "terraform-aws-modules/iam/aws//modules/iam-github-oidc-role"
  version   = "~> 5.0"

  subjects = ["repo:jeneeldumasia/DeployHub:*"]
  
  policies = {
    AdministratorAccess = "arn:aws:iam::aws:policy/AdministratorAccess"
  }
}

# 4. S3 Bucket for Build Logs
resource "aws_s3_bucket" "build_logs" {
  bucket_prefix = "deployhub-build-logs-"
  force_destroy = true # CRITICAL: Allows terraform destroy to delete the bucket even if it contains logs!
}
