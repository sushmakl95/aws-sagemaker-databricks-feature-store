terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
    databricks = {
      source                = "databricks/databricks"
      version               = "~> 1.40"
      configuration_aliases = [databricks.workspace]
    }
  }

  backend "s3" {}
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      Repo        = "aws-sagemaker-databricks-feature-store"
      CostCenter  = var.cost_center
    }
  }
}

provider "databricks" {
  alias = "workspace"
  host  = var.databricks_workspace_url
  token = var.databricks_token
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

module "vpc" {
  source             = "./modules/vpc"
  name_prefix        = local.name_prefix
  vpc_cidr_block     = var.vpc_cidr_block
  availability_zones = var.availability_zones
}

module "kms" {
  source      = "./modules/kms"
  name_prefix = local.name_prefix
}

module "s3" {
  source      = "./modules/s3"
  name_prefix = local.name_prefix
  kms_key_arn = module.kms.s3_key_arn
}

module "secrets" {
  source           = "./modules/secrets"
  name_prefix      = local.name_prefix
  kms_key_arn      = module.kms.secrets_key_arn
  databricks_token = var.databricks_token
  mlflow_db_password = var.mlflow_db_password
}

module "iam" {
  source             = "./modules/iam"
  name_prefix        = local.name_prefix
  s3_bucket_arns     = module.s3.all_bucket_arns
  kms_key_arns       = module.kms.all_key_arns
  feature_group_arns = module.sagemaker_feature_store.feature_group_arns
}

module "dynamodb" {
  source      = "./modules/dynamodb"
  name_prefix = local.name_prefix
  kms_key_arn = module.kms.dynamodb_key_arn
}

module "kinesis" {
  source      = "./modules/kinesis"
  name_prefix = local.name_prefix
  kms_key_arn = module.kms.kinesis_key_arn
  shard_count = var.kinesis_shard_count
}

module "glue" {
  source             = "./modules/glue"
  name_prefix        = local.name_prefix
  offline_bucket_arn = module.s3.feature_store_offline_bucket_arn
}

module "sagemaker_feature_store" {
  source              = "./modules/sagemaker_feature_store"
  name_prefix         = local.name_prefix
  offline_bucket_name = module.s3.feature_store_offline_bucket_name
  kms_key_arn         = module.kms.sagemaker_key_arn
  glue_database_name  = module.glue.database_name
  offline_role_arn    = module.iam.sagemaker_fs_offline_role_arn
}

module "sagemaker_training" {
  source            = "./modules/sagemaker_training"
  name_prefix       = local.name_prefix
  training_role_arn = module.iam.sagemaker_training_role_arn
  artifacts_bucket  = module.s3.artifacts_bucket_name
  kms_key_arn       = module.kms.sagemaker_key_arn
}

module "sagemaker_inference" {
  source             = "./modules/sagemaker_inference"
  name_prefix        = local.name_prefix
  inference_role_arn = module.iam.sagemaker_inference_role_arn
  artifacts_bucket   = module.s3.artifacts_bucket_name
  data_capture_bucket = module.s3.data_capture_bucket_name
  kms_key_arn        = module.kms.sagemaker_key_arn
  endpoint_instance_type = var.endpoint_instance_type
  endpoint_instance_count = var.endpoint_instance_count
}

module "sagemaker_model_monitor" {
  source              = "./modules/sagemaker_model_monitor"
  name_prefix         = local.name_prefix
  monitor_role_arn    = module.iam.sagemaker_monitor_role_arn
  data_capture_bucket = module.s3.data_capture_bucket_name
  monitor_reports_bucket = module.s3.monitor_reports_bucket_name
  endpoint_name       = module.sagemaker_inference.endpoint_name
  baseline_s3_uri     = "s3://${module.s3.artifacts_bucket_name}/baselines/"
}

module "lambda" {
  source                   = "./modules/lambda"
  name_prefix              = local.name_prefix
  subnet_ids               = module.vpc.private_subnet_ids
  security_group_id        = module.vpc.lambda_security_group_id
  execution_role_arn       = module.iam.lambda_role_arn
  kinesis_stream_arn       = module.kinesis.stream_arn
  state_table_name         = module.dynamodb.state_table_name
  feature_group_name       = module.sagemaker_feature_store.user_recency_feature_group_name
  sns_alerts_topic_arn     = module.monitoring.alerts_topic_arn
  monitor_reports_bucket   = module.s3.monitor_reports_bucket_name
  slack_webhook_url_secret = module.secrets.slack_webhook_secret_id
}

module "databricks" {
  source = "./modules/databricks"
  providers = {
    databricks = databricks.workspace
  }
  name_prefix                    = local.name_prefix
  offline_bucket                 = module.s3.feature_store_offline_bucket_name
  kinesis_stream_name            = module.kinesis.stream_name
  execution_instance_profile_arn = module.iam.databricks_instance_profile_arn
}

module "mlflow" {
  source             = "./modules/mlflow"
  name_prefix        = local.name_prefix
  vpc_id             = module.vpc.vpc_id
  subnet_ids         = module.vpc.private_subnet_ids
  artifacts_bucket   = module.s3.artifacts_bucket_name
  db_password_secret = module.secrets.mlflow_db_password_secret_id
}

module "apigw" {
  source                = "./modules/apigw"
  name_prefix           = local.name_prefix
  inference_endpoint_arn = module.sagemaker_inference.endpoint_arn
  api_invocation_role    = module.iam.apigw_sagemaker_role_arn
}

module "monitoring" {
  source                 = "./modules/monitoring"
  name_prefix            = local.name_prefix
  endpoint_name          = module.sagemaker_inference.endpoint_name
  feature_group_names    = module.sagemaker_feature_store.feature_group_names
  lambda_function_names  = module.lambda.all_function_names
  alarm_email_recipients = var.alarm_email_recipients
  monthly_budget_usd     = var.monthly_budget_usd
  log_retention_days     = var.log_retention_days
}
