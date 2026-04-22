variable "name_prefix" { type = string }
variable "offline_bucket_name" { type = string }
variable "kms_key_arn" { type = string }
variable "glue_database_name" { type = string }
variable "offline_role_arn" { type = string }

# --------------------------------------------------------------------
# User Recency feature group (streaming + online)
# --------------------------------------------------------------------
resource "aws_sagemaker_feature_group" "user_recency" {
  feature_group_name             = "${var.name_prefix}-user-recency"
  record_identifier_feature_name = "entity_id"
  event_time_feature_name        = "event_time"
  role_arn                       = var.offline_role_arn

  feature_definition {
    feature_name = "entity_id"
    feature_type = "String"
  }

  feature_definition {
    feature_name = "event_time"
    feature_type = "String"
  }

  feature_definition {
    feature_name = "events_last_5min"
    feature_type = "Integral"
  }
  feature_definition {
    feature_name = "events_last_1h"
    feature_type = "Integral"
  }
  feature_definition {
    feature_name = "distinct_products_last_1h"
    feature_type = "Integral"
  }
  feature_definition {
    feature_name = "avg_order_value_last_1h"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "seconds_since_last_event"
    feature_type = "Integral"
  }

  online_store_config {
    enable_online_store = true
    security_config {
      kms_key_id = var.kms_key_arn
    }
  }

  offline_store_config {
    s3_storage_config {
      s3_uri     = "s3://${var.offline_bucket_name}/feature_store/user_recency/"
      kms_key_id = var.kms_key_arn
    }
    data_catalog_config {
      catalog      = "AwsDataCatalog"
      database     = var.glue_database_name
      table_name   = "user_recency"
    }
    disable_glue_table_creation = false
  }
}

# --------------------------------------------------------------------
# User Lifetime feature group (batch)
# --------------------------------------------------------------------
resource "aws_sagemaker_feature_group" "user_lifetime" {
  feature_group_name             = "${var.name_prefix}-user-lifetime"
  record_identifier_feature_name = "entity_id"
  event_time_feature_name        = "event_time"
  role_arn                       = var.offline_role_arn

  feature_definition {
    feature_name = "entity_id"
    feature_type = "String"
  }
  feature_definition {
    feature_name = "event_time"
    feature_type = "String"
  }
  feature_definition {
    feature_name = "account_age_days"
    feature_type = "Integral"
  }
  feature_definition {
    feature_name = "total_orders"
    feature_type = "Integral"
  }
  feature_definition {
    feature_name = "total_spend"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "avg_order_value"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "distinct_products_purchased"
    feature_type = "Integral"
  }
  feature_definition {
    feature_name = "churn_risk_score"
    feature_type = "Fractional"
  }

  online_store_config {
    enable_online_store = true
    security_config {
      kms_key_id = var.kms_key_arn
    }
  }

  offline_store_config {
    s3_storage_config {
      s3_uri     = "s3://${var.offline_bucket_name}/feature_store/user_lifetime/"
      kms_key_id = var.kms_key_arn
    }
    data_catalog_config {
      catalog    = "AwsDataCatalog"
      database   = var.glue_database_name
      table_name = "user_lifetime"
    }
    disable_glue_table_creation = false
  }
}

output "user_recency_feature_group_name"  { value = aws_sagemaker_feature_group.user_recency.feature_group_name }
output "user_lifetime_feature_group_name" { value = aws_sagemaker_feature_group.user_lifetime.feature_group_name }
output "feature_group_names" {
  value = [
    aws_sagemaker_feature_group.user_recency.feature_group_name,
    aws_sagemaker_feature_group.user_lifetime.feature_group_name,
  ]
}
output "feature_group_arns" {
  value = [
    aws_sagemaker_feature_group.user_recency.arn,
    aws_sagemaker_feature_group.user_lifetime.arn,
  ]
}
