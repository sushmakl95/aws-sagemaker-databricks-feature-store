variable "name_prefix" { type = string }
variable "kms_key_arn" { type = string }

resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  buckets = {
    feature_store_offline = "feature-store-offline"
    artifacts             = "artifacts"
    data_capture          = "data-capture"
    monitor_reports       = "monitor-reports"
  }
}

resource "aws_s3_bucket" "this" {
  for_each = local.buckets
  bucket   = "${var.name_prefix}-${each.value}-${random_id.suffix.hex}"
  tags     = { Name = "${var.name_prefix}-${each.value}" }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = aws_s3_bucket.this
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "offline_tiering" {
  bucket = aws_s3_bucket.this["feature_store_offline"].id
  rule {
    id     = "glacier-after-180d"
    status = "Enabled"
    filter {}
    transition {
      days          = 180
      storage_class = "GLACIER_IR"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data_capture_retention" {
  bucket = aws_s3_bucket.this["data_capture"].id
  rule {
    id     = "expire-after-90d"
    status = "Enabled"
    filter {}
    expiration {
      days = 90
    }
  }
}

output "feature_store_offline_bucket_name" { value = aws_s3_bucket.this["feature_store_offline"].id }
output "feature_store_offline_bucket_arn"  { value = aws_s3_bucket.this["feature_store_offline"].arn }
output "artifacts_bucket_name"             { value = aws_s3_bucket.this["artifacts"].id }
output "artifacts_bucket_arn"              { value = aws_s3_bucket.this["artifacts"].arn }
output "data_capture_bucket_name"          { value = aws_s3_bucket.this["data_capture"].id }
output "data_capture_bucket_arn"           { value = aws_s3_bucket.this["data_capture"].arn }
output "monitor_reports_bucket_name"       { value = aws_s3_bucket.this["monitor_reports"].id }
output "monitor_reports_bucket_arn"        { value = aws_s3_bucket.this["monitor_reports"].arn }
output "all_bucket_arns" {
  value = [for b in aws_s3_bucket.this : b.arn]
}
