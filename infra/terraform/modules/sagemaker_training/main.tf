variable "name_prefix" { type = string }
variable "training_role_arn" { type = string }
variable "artifacts_bucket" { type = string }
variable "kms_key_arn" { type = string }

# Training jobs are submitted programmatically via sagemaker_runner.py.
# This module only provisions supporting infrastructure:
#   - CloudWatch log group
#   - (optional) Model Package Group for registering trained models

resource "aws_cloudwatch_log_group" "training" {
  name              = "/aws/sagemaker/TrainingJobs/${var.name_prefix}"
  retention_in_days = 30
  kms_key_id        = var.kms_key_arn
}

resource "aws_sagemaker_model_package_group" "churn" {
  model_package_group_name        = "${var.name_prefix}-churn-predictor"
  model_package_group_description = "Churn predictor model lineage"
}

output "log_group_name"                { value = aws_cloudwatch_log_group.training.name }
output "model_package_group_name"      { value = aws_sagemaker_model_package_group.churn.model_package_group_name }
output "model_package_group_arn"       { value = aws_sagemaker_model_package_group.churn.arn }
output "training_role_arn_passthrough" { value = var.training_role_arn }
