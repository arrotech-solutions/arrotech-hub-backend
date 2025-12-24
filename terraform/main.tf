terraform {
  required_version = ">= 1.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "mini-hub-terraform-state"
    key            = "production/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "mini-hub-terraform-locks"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "Mini-Hub"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# ====================================
# NETWORKING
# ====================================
module "vpc" {
  source = "./modules/vpc"

  project_name = var.project_name
  environment  = var.environment
  vpc_cidr     = var.vpc_cidr
  
  availability_zones = var.availability_zones
  public_subnets     = var.public_subnets
  private_subnets    = var.private_subnets
  database_subnets   = var.database_subnets
}

# ====================================
# SECURITY GROUPS
# ====================================
module "security_groups" {
  source = "./modules/security"

  vpc_id       = module.vpc.vpc_id
  project_name = var.project_name
  environment  = var.environment
}

# ====================================
# APPLICATION LOAD BALANCER
# ====================================
module "alb" {
  source = "./modules/alb"

  project_name     = var.project_name
  environment      = var.environment
  vpc_id           = module.vpc.vpc_id
  public_subnets   = module.vpc.public_subnet_ids
  security_groups  = [module.security_groups.alb_sg_id]
  certificate_arn  = var.acm_certificate_arn
}

# ====================================
# ECS CLUSTER
# ====================================
module "ecs" {
  source = "./modules/ecs"

  project_name    = var.project_name
  environment     = var.environment
  vpc_id          = module.vpc.vpc_id
  private_subnets = module.vpc.private_subnet_ids
  security_groups = [module.security_groups.ecs_sg_id]
  
  target_group_arn = module.alb.target_group_arn
  
  # Task configuration
  task_cpu    = var.task_cpu
  task_memory = var.task_memory
  
  # Container configuration
  container_image = var.container_image
  container_port  = var.container_port
  
  # Auto scaling
  min_capacity = var.min_capacity
  max_capacity = var.max_capacity
}

# ====================================
# RDS POSTGRESQL
# ====================================
module "rds" {
  source = "./modules/rds"

  project_name     = var.project_name
  environment      = var.environment
  vpc_id           = module.vpc.vpc_id
  subnet_ids       = module.vpc.database_subnet_ids
  security_groups  = [module.security_groups.rds_sg_id]
  
  # Database configuration
  instance_class          = var.db_instance_class
  allocated_storage       = var.db_allocated_storage
  max_allocated_storage   = var.db_max_allocated_storage
  database_name           = var.db_name
  master_username         = var.db_username
  
  # Backup configuration
  backup_retention_period = var.db_backup_retention_period
  backup_window           = var.db_backup_window
  maintenance_window      = var.db_maintenance_window
  
  # High availability
  multi_az = var.db_multi_az
}

# ====================================
# ELASTICACHE REDIS
# ====================================
module "elasticache" {
  source = "./modules/elasticache"

  project_name    = var.project_name
  environment     = var.environment
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.private_subnet_ids
  security_groups = [module.security_groups.redis_sg_id]
  
  # Redis configuration
  node_type          = var.redis_node_type
  num_cache_nodes    = var.redis_num_cache_nodes
  parameter_group    = var.redis_parameter_group
  engine_version     = var.redis_engine_version
}

# ====================================
# S3 BUCKETS
# ====================================
module "s3" {
  source = "./modules/s3"

  project_name = var.project_name
  environment  = var.environment
  
  # Bucket configuration
  enable_versioning = true
  enable_encryption = true
}

# ====================================
# ECR REPOSITORY
# ====================================
resource "aws_ecr_repository" "app" {
  name                 = "${var.project_name}-${var.environment}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  lifecycle_policy {
    policy = jsonencode({
      rules = [{
        rulePriority = 1
        description  = "Keep last 30 images"
        selection = {
          tagStatus     = "any"
          countType     = "imageCountMoreThan"
          countNumber   = 30
        }
        action = {
          type = "expire"
        }
      }]
    })
  }
}

# ====================================
# CLOUDWATCH LOG GROUPS
# ====================================
resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.project_name}-${var.environment}"
  retention_in_days = var.log_retention_days

  kms_key_id = aws_kms_key.logs.arn
}

resource "aws_kms_key" "logs" {
  description             = "KMS key for CloudWatch Logs encryption"
  deletion_window_in_days = 10
  enable_key_rotation     = true
}

# ====================================
# ROUTE53 DNS
# ====================================
module "route53" {
  source = "./modules/route53"

  project_name = var.project_name
  environment  = var.environment
  domain_name  = var.domain_name
  alb_dns_name = module.alb.alb_dns_name
  alb_zone_id  = module.alb.alb_zone_id
}

# ====================================
# CLOUDFRONT CDN
# ====================================
module "cloudfront" {
  source = "./modules/cloudfront"

  project_name    = var.project_name
  environment     = var.environment
  domain_name     = var.domain_name
  alb_dns_name    = module.alb.alb_dns_name
  acm_certificate_arn = var.cloudfront_certificate_arn
}

# ====================================
# WAF
# ====================================
module "waf" {
  source = "./modules/waf"

  project_name = var.project_name
  environment  = var.environment
  alb_arn      = module.alb.alb_arn
}

# ====================================
# SECRETS MANAGER
# ====================================
resource "aws_secretsmanager_secret" "app_secrets" {
  name = "${var.project_name}-${var.environment}-secrets"
  
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "app_secrets" {
  secret_id = aws_secretsmanager_secret.app_secrets.id
  secret_string = jsonencode({
    DATABASE_URL          = module.rds.connection_string
    REDIS_URL            = module.elasticache.connection_string
    SECRET_KEY           = var.app_secret_key
    JWT_SECRET_KEY       = var.jwt_secret_key
    STRIPE_SECRET_KEY    = var.stripe_secret_key
    MPESA_CONSUMER_KEY   = var.mpesa_consumer_key
    MPESA_CONSUMER_SECRET = var.mpesa_consumer_secret
  })
}

# ====================================
# OUTPUTS
# ====================================
output "alb_dns_name" {
  value       = module.alb.alb_dns_name
  description = "DNS name of the Application Load Balancer"
}

output "rds_endpoint" {
  value       = module.rds.endpoint
  description = "RDS endpoint"
  sensitive   = true
}

output "redis_endpoint" {
  value       = module.elasticache.endpoint
  description = "ElastiCache Redis endpoint"
  sensitive   = true
}

output "ecr_repository_url" {
  value       = aws_ecr_repository.app.repository_url
  description = "ECR repository URL"
}

output "cloudfront_domain" {
  value       = module.cloudfront.domain_name
  description = "CloudFront distribution domain name"
}

