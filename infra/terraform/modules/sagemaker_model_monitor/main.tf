variable "name_prefix" { type = string }
variable "monitor_role_arn" { type = string }
variable "data_capture_bucket" { type = string }
variable "monitor_reports_bucket" { type = string }
variable "endpoint_name" { type = string }
variable "baseline_s3_uri" { type = string }
variable "schedule_expression" {
  type    = string
  default = "cron(0 * ? * * *)"
  description = "Hourly by default"
}

resource "aws_sagemaker_data_quality_job_definition" "this" {
  name     = "${var.name_prefix}-data-quality-job"
  role_arn = var.monitor_role_arn

  data_quality_app_specification {
    image_uri = "156813124566.dkr.ecr.us-east-1.amazonaws.com/sagemaker-model-monitor-analyzer:latest"
  }

  data_quality_baseline_config {
    constraints_resource {
      s3_uri = "${var.baseline_s3_uri}constraints.json"
    }
    statistics_resource {
      s3_uri = "${var.baseline_s3_uri}statistics.json"
    }
  }

  data_quality_job_input {
    endpoint_input {
      endpoint_name          = var.endpoint_name
      local_path             = "/opt/ml/processing/input/endpoint"
      s3_input_mode          = "File"
      s3_data_distribution_type = "FullyReplicated"
    }
  }

  data_quality_job_output_config {
    monitoring_outputs {
      s3_output {
        s3_uri     = "s3://${var.monitor_reports_bucket}/reports/"
        local_path = "/opt/ml/processing/output"
      }
    }
  }

  job_resources {
    cluster_config {
      instance_count    = 1
      instance_type     = "ml.m5.xlarge"
      volume_size_in_gb = 30
    }
  }

  stopping_condition {
    max_runtime_in_seconds = 3600
  }
}

resource "aws_sagemaker_monitoring_schedule" "data_quality" {
  name = "${var.name_prefix}-data-quality-schedule"

  monitoring_schedule_config {
    schedule_config {
      schedule_expression = var.schedule_expression
    }
    monitoring_job_definition_name = aws_sagemaker_data_quality_job_definition.this.name
    monitoring_type                = "DataQuality"
  }
}

output "schedule_name"       { value = aws_sagemaker_monitoring_schedule.data_quality.name }
output "schedule_arn"        { value = aws_sagemaker_monitoring_schedule.data_quality.arn }
output "job_definition_name" { value = aws_sagemaker_data_quality_job_definition.this.name }
