variable "name_prefix" { type = string }
variable "offline_bucket_arn" { type = string }

resource "aws_glue_catalog_database" "feature_store" {
  name        = replace("${var.name_prefix}_feature_store", "-", "_")
  description = "Glue database for SageMaker Feature Store offline store"
}

output "database_name" { value = aws_glue_catalog_database.feature_store.name }
output "database_arn"  { value = aws_glue_catalog_database.feature_store.arn }
