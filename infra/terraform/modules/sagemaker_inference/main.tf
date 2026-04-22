variable "name_prefix" { type = string }
variable "inference_role_arn" { type = string }
variable "artifacts_bucket" { type = string }
variable "data_capture_bucket" { type = string }
variable "kms_key_arn" { type = string }
variable "endpoint_instance_type" { type = string }
variable "endpoint_instance_count" { type = number }
variable "initial_model_s3_uri" {
  type    = string
  default = ""
  description = "S3 URI to model.tar.gz. If empty, a placeholder scikit-learn model is used."
}
variable "container_image_uri" {
  type        = string
  default     = "683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-scikit-learn:1.2-1"
  description = "ECR URI for the inference container"
}

# Bootstrap: a placeholder model.tar.gz to be replaced by CI after first training
resource "aws_s3_object" "placeholder_model" {
  count  = var.initial_model_s3_uri == "" ? 1 : 0
  bucket = var.artifacts_bucket
  key    = "models/placeholder/model.tar.gz"
  source = "${path.module}/placeholder-model.tar.gz"
  etag   = filemd5("${path.module}/placeholder-model.tar.gz")

  lifecycle {
    ignore_changes = [source, etag]
  }
}

locals {
  effective_model_s3_uri = var.initial_model_s3_uri != "" ? var.initial_model_s3_uri : "s3://${var.artifacts_bucket}/models/placeholder/model.tar.gz"
}

resource "aws_sagemaker_model" "this" {
  name               = "${var.name_prefix}-churn-model"
  execution_role_arn = var.inference_role_arn

  primary_container {
    image          = var.container_image_uri
    model_data_url = local.effective_model_s3_uri
    environment = {
      SAGEMAKER_PROGRAM          = "predictor.py"
      SAGEMAKER_SUBMIT_DIRECTORY = "/opt/ml/code"
      FEAST_REPO_PATH            = "/opt/ml/code/feast_repo"
    }
  }

  lifecycle {
    ignore_changes = [primary_container[0].model_data_url]
  }
}

resource "aws_sagemaker_endpoint_configuration" "this" {
  name = "${var.name_prefix}-churn-endpoint-config"

  production_variants {
    variant_name           = "AllTraffic"
    model_name             = aws_sagemaker_model.this.name
    initial_instance_count = var.endpoint_instance_count
    instance_type          = var.endpoint_instance_type
    initial_variant_weight = 1.0
  }

  data_capture_config {
    enable_capture              = true
    initial_sampling_percentage = 100
    destination_s3_uri          = "s3://${var.data_capture_bucket}/capture/"
    kms_key_id                  = var.kms_key_arn
    capture_options {
      capture_mode = "Input"
    }
    capture_options {
      capture_mode = "Output"
    }
  }

  kms_key_arn = var.kms_key_arn
}

resource "aws_sagemaker_endpoint" "this" {
  name                 = "${var.name_prefix}-churn-endpoint"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.this.name
}

output "endpoint_name" { value = aws_sagemaker_endpoint.this.name }
output "endpoint_arn"  { value = aws_sagemaker_endpoint.this.arn }
output "model_name"    { value = aws_sagemaker_model.this.name }
