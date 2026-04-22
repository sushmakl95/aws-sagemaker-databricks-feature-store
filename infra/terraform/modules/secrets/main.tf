variable "name_prefix" { type = string }
variable "kms_key_arn" { type = string }
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

locals {
  secrets = {
    databricks_token   = { value = var.databricks_token, enabled = var.databricks_token != "" }
    mlflow_db_password = { value = var.mlflow_db_password, enabled = var.mlflow_db_password != "" }
    slack_webhook      = { value = "PLACEHOLDER_SET_AFTER_APPLY", enabled = true }
  }
  enabled = { for k, v in local.secrets : k => v if v.enabled }
}

resource "aws_secretsmanager_secret" "this" {
  for_each    = nonsensitive(toset(keys(local.enabled)))
  name        = "${var.name_prefix}/${each.value}"
  kms_key_id  = var.kms_key_arn
  description = "${each.value} for the feature platform"
}

resource "aws_secretsmanager_secret_version" "this" {
  for_each      = nonsensitive(toset(keys(local.enabled)))
  secret_id     = aws_secretsmanager_secret.this[each.value].id
  secret_string = local.enabled[each.value].value
}

output "secret_ids" {
  value = { for k, s in aws_secretsmanager_secret.this : k => s.id }
}
output "databricks_token_secret_id"   { value = try(aws_secretsmanager_secret.this["databricks_token"].id, "") }
output "mlflow_db_password_secret_id" { value = try(aws_secretsmanager_secret.this["mlflow_db_password"].id, "") }
output "slack_webhook_secret_id"      { value = aws_secretsmanager_secret.this["slack_webhook"].id }
