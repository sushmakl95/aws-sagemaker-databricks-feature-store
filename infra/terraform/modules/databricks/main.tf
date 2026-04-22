terraform {
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.40"
    }
  }
}

variable "name_prefix" { type = string }
variable "offline_bucket" { type = string }
variable "kinesis_stream_name" { type = string }
variable "execution_instance_profile_arn" { type = string }

resource "databricks_instance_profile" "this" {
  instance_profile_arn = var.execution_instance_profile_arn
}

resource "databricks_cluster_policy" "ml_runtime" {
  name = "${var.name_prefix}-ml-runtime-policy"
  definition = jsonencode({
    "spark_version" : {
      "type" : "fixed",
      "value" : "14.3.x-cpu-ml-scala2.12"
    },
    "node_type_id" : {
      "type" : "allowlist",
      "values" : ["i3.xlarge", "i3.2xlarge", "r5.xlarge", "r5.2xlarge"]
    },
    "aws_attributes.instance_profile_arn" : {
      "type" : "fixed",
      "value" : var.execution_instance_profile_arn
    },
    "aws_attributes.availability" : {
      "type" : "fixed",
      "value" : "SPOT_WITH_FALLBACK"
    },
    "autotermination_minutes" : {
      "type" : "fixed",
      "value" : 30
    },
    "custom_tags.Project" : {
      "type" : "fixed",
      "value" : var.name_prefix
    },
  })
}

resource "databricks_job" "feature_training" {
  name = "${var.name_prefix}-churn-training"

  job_cluster {
    job_cluster_key = "ml-cluster"
    new_cluster {
      policy_id     = databricks_cluster_policy.ml_runtime.id
      spark_version = "14.3.x-cpu-ml-scala2.12"
      node_type_id  = "i3.xlarge"
      num_workers   = 2
      aws_attributes {
        first_on_demand        = 1
        availability           = "SPOT_WITH_FALLBACK"
        instance_profile_arn   = var.execution_instance_profile_arn
        spot_bid_price_percent = 100
      }
      custom_tags = {
        Project = var.name_prefix
      }
    }
  }

  task {
    task_key        = "train_churn"
    job_cluster_key = "ml-cluster"
    max_retries     = 1
    notebook_task {
      notebook_path = "/Shared/feature-platform/02_databricks_ml_training"
      base_parameters = {
        training_label_table = "main.ml.churn_labels_train"
        model_name           = "main.ml.churn_predictor"
      }
    }
  }

  timeout_seconds     = 7200
  max_concurrent_runs = 1
}

output "training_job_id"    { value = tostring(databricks_job.feature_training.id) }
output "cluster_policy_id"  { value = databricks_cluster_policy.ml_runtime.id }
