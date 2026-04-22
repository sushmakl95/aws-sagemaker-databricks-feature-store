variable "project_name" {
  type    = string
  default = "feature-platform"
}

variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod"
  }
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "cost_center" {
  type    = string
  default = "ml-platform"
}

variable "vpc_cidr_block" {
  type    = string
  default = "10.80.0.0/16"
}

variable "availability_zones" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "kinesis_shard_count" {
  type    = number
  default = 2
}

variable "endpoint_instance_type" {
  type    = string
  default = "ml.m5.xlarge"
}

variable "endpoint_instance_count" {
  type    = number
  default = 2
}

variable "databricks_workspace_url" {
  type    = string
  default = ""
}

variable "databricks_token" {
  type      = string
  sensitive = true
  default   = ""
}

variable "mlflow_db_password" {
  type      = string
  sensitive = true
  default   = ""
}

variable "alarm_email_recipients" {
  type    = list(string)
  default = []
}

variable "monthly_budget_usd" {
  type    = number
  default = 1500
}

variable "log_retention_days" {
  type    = number
  default = 30
}
