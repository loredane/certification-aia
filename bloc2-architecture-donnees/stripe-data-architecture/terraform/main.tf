################################################################################
# Stripe Data Architecture — Terraform AWS Mirror (minimal)
# Bloc 2 AIA — Déploiement cloud pour démonstration scalabilité
#
# FIX v3-hauts :
#   - Security group dédié pour RDS (avant : SG default du VPC).
#   - AWS Secrets Manager pour le master password RDS
#     (avant : plaintext dans le state via var.postgres_password).
#   - VPC default toujours utilisé mais CLAIREMENT flaggé :
#     acceptable en démo trial, NON-CONFORME PCI-DSS en prod.
#     Un module VPC dédié est laissé en TODO explicite (phase 2).
#
# DAMA-DMBOK2 ch.6 §2.1 — Cloud storage
# DAMA-DMBOK2 ch.7 §1.4 — Encryption & Key management
################################################################################

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }

  # FIX v3-hauts: backend remote recommandé en prod (à décommenter + créer
  # préalablement le bucket + la table DynamoDB).
  # backend "s3" {
  #   bucket         = "stripe-tf-state-prod"
  #   key            = "data-architecture/terraform.tfstate"
  #   region         = "eu-west-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-locks"
  # }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "stripe-data-architecture"
      Environment = var.environment
      ManagedBy   = "Terraform"
      Compliance  = "GDPR-PCI-DSS"
    }
  }
}

################################################################################
# Variables
################################################################################

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-west-1"
}

variable "environment" {
  description = "Environment (dev/staging/prod)"
  type        = string
  default     = "dev"
}

variable "project" {
  description = "Project prefix"
  type        = string
  default     = "stripe"
}

# FIX v3-hauts: plus de variable postgres_password en plaintext.
# Le password est géré par AWS Secrets Manager (manage_master_user_password).
# Si besoin en dev de fournir un password explicite, décommenter la var ci-dessous
# et le bloc aws_db_instance correspondant.
# variable "postgres_password" {
#   type      = string
#   sensitive = true
# }

variable "allowed_cidr_blocks_postgres" {
  description = "CIDR blocks autorisés en ingress 5432 (bastion, VPC workers)"
  type        = list(string)
  default     = ["10.0.0.0/8"] # placeholder : à restreindre en prod
}

################################################################################
# Network (FIX v3-hauts: SG dédié au lieu de default)
#
# NOTE: l'utilisation du VPC default est conservée pour simplifier la démo.
# En prod PCI-DSS v4.0 Req 1.2 (segmentation réseau), il FAUT un VPC dédié.
# TODO phase 2 : module terraform-aws-modules/vpc/aws avec 3 AZ privées.
################################################################################

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "postgres" {
  name        = "${var.project}-postgres-${var.environment}"
  description = "RDS PostgreSQL — ingress 5432 depuis CIDRs autorises uniquement"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "PostgreSQL from allowed CIDRs"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks_postgres
  }

  egress {
    description = "Outbound all"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project}-postgres-${var.environment}"
  }
}

################################################################################
# S3 Data Lake — Medallion buckets
################################################################################

resource "aws_s3_bucket" "raw" {
  bucket        = "${var.project}-raw-${var.environment}"
  force_destroy = var.environment != "prod"
}

resource "aws_s3_bucket" "staging" {
  bucket        = "${var.project}-staging-${var.environment}"
  force_destroy = var.environment != "prod"
}

resource "aws_s3_bucket" "archive" {
  bucket        = "${var.project}-archive-${var.environment}"
  force_destroy = false
}

# Encryption at rest — AES-256 (PCI-DSS Req. 3.4)
resource "aws_s3_bucket_server_side_encryption_configuration" "encryption" {
  for_each = {
    raw     = aws_s3_bucket.raw.id
    staging = aws_s3_bucket.staging.id
    archive = aws_s3_bucket.archive.id
  }
  bucket = each.value
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data_key.arn
    }
    bucket_key_enabled = true
  }
}

# Versioning — immutability for audit
resource "aws_s3_bucket_versioning" "versioning" {
  for_each = {
    raw     = aws_s3_bucket.raw.id
    archive = aws_s3_bucket.archive.id
  }
  bucket = each.value
  versioning_configuration {
    status = "Enabled"
  }
}

# Public access block — security baseline
resource "aws_s3_bucket_public_access_block" "public_block" {
  for_each = {
    raw     = aws_s3_bucket.raw.id
    staging = aws_s3_bucket.staging.id
    archive = aws_s3_bucket.archive.id
  }
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle — archive/delete after retention
resource "aws_s3_bucket_lifecycle_configuration" "lifecycle_archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    id     = "glacier-after-90-days"
    status = "Enabled"
    filter {}
    transition {
      days          = 90
      storage_class = "GLACIER"
    }
    transition {
      days          = 365
      storage_class = "DEEP_ARCHIVE"
    }
    expiration {
      days = 2555 # 7 years PCI-DSS retention
    }
  }
}

################################################################################
# KMS keys for sensitive data
################################################################################

resource "aws_kms_key" "data_key" {
  description             = "KMS key for Stripe sensitive data encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true # PCI-DSS Req. 3.6.4
}

resource "aws_kms_alias" "data_key_alias" {
  name          = "alias/${var.project}-data-${var.environment}"
  target_key_id = aws_kms_key.data_key.key_id
}

################################################################################
# RDS PostgreSQL — OLTP
# FIX v3-hauts:
#   - vpc_security_group_ids (SG dédié au lieu de default)
#   - manage_master_user_password = true (AWS Secrets Manager auto)
#   - performance_insights_kms_key_id pour chiffrer Perf Insights
################################################################################

resource "aws_db_subnet_group" "rds" {
  name       = "${var.project}-rds-${var.environment}"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_db_instance" "postgres" {
  identifier        = "${var.project}-oltp-${var.environment}"
  engine            = "postgres"
  engine_version    = "16"
  instance_class    = "db.t3.medium"
  allocated_storage = 100
  storage_type      = "gp3"
  storage_encrypted = true
  kms_key_id        = aws_kms_key.data_key.arn

  db_name  = "stripe_oltp"
  username = "stripe_admin"

  # FIX v3-hauts: Secrets Manager géré par RDS (rotation auto)
  # Plus de password en plaintext dans le state Terraform.
  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.data_key.arn

  # FIX v3-hauts: SG dédié au lieu du default
  vpc_security_group_ids = [aws_security_group.postgres.id]
  db_subnet_group_name   = aws_db_subnet_group.rds.name
  publicly_accessible    = false
  multi_az               = var.environment == "prod"

  backup_retention_period = 14
  backup_window           = "03:00-04:00"
  maintenance_window      = "Sun:04:00-Sun:05:00"

  performance_insights_enabled    = true
  performance_insights_kms_key_id = aws_kms_key.data_key.arn

  deletion_protection = var.environment == "prod"
  skip_final_snapshot = var.environment != "prod"

  enabled_cloudwatch_logs_exports = ["postgresql"]
}

################################################################################
# MSK (Managed Kafka) — streaming
# Commenté pour la démo (coût trial) — à décommenter en prod
################################################################################
# resource "aws_msk_cluster" "kafka" {
#   cluster_name           = "${var.project}-kafka-${var.environment}"
#   kafka_version          = "3.7.x"
#   number_of_broker_nodes = 3
#   ...
# }

################################################################################
# Outputs
################################################################################

output "s3_raw_bucket" {
  value = aws_s3_bucket.raw.id
}

output "s3_staging_bucket" {
  value = aws_s3_bucket.staging.id
}

output "s3_archive_bucket" {
  value = aws_s3_bucket.archive.id
}

output "rds_endpoint" {
  value = aws_db_instance.postgres.endpoint
}

output "rds_master_secret_arn" {
  description = "ARN du secret AWS Secrets Manager contenant le master password RDS"
  value       = try(aws_db_instance.postgres.master_user_secret[0].secret_arn, null)
}

output "kms_key_arn" {
  value = aws_kms_key.data_key.arn
}

output "postgres_security_group_id" {
  value = aws_security_group.postgres.id
}
