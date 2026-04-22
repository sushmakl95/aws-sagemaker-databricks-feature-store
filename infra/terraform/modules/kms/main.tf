variable "name_prefix" { type = string }

resource "aws_kms_key" "s3" {
  description             = "${var.name_prefix} S3"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}
resource "aws_kms_alias" "s3" {
  name          = "alias/${var.name_prefix}-s3"
  target_key_id = aws_kms_key.s3.key_id
}

resource "aws_kms_key" "secrets" {
  description             = "${var.name_prefix} secrets"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}
resource "aws_kms_alias" "secrets" {
  name          = "alias/${var.name_prefix}-secrets"
  target_key_id = aws_kms_key.secrets.key_id
}

resource "aws_kms_key" "sagemaker" {
  description             = "${var.name_prefix} sagemaker"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}
resource "aws_kms_alias" "sagemaker" {
  name          = "alias/${var.name_prefix}-sagemaker"
  target_key_id = aws_kms_key.sagemaker.key_id
}

resource "aws_kms_key" "dynamodb" {
  description             = "${var.name_prefix} dynamodb"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}
resource "aws_kms_alias" "dynamodb" {
  name          = "alias/${var.name_prefix}-dynamodb"
  target_key_id = aws_kms_key.dynamodb.key_id
}

resource "aws_kms_key" "kinesis" {
  description             = "${var.name_prefix} kinesis"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}
resource "aws_kms_alias" "kinesis" {
  name          = "alias/${var.name_prefix}-kinesis"
  target_key_id = aws_kms_key.kinesis.key_id
}

output "s3_key_arn" { value = aws_kms_key.s3.arn }
output "secrets_key_arn" { value = aws_kms_key.secrets.arn }
output "sagemaker_key_arn" { value = aws_kms_key.sagemaker.arn }
output "dynamodb_key_arn" { value = aws_kms_key.dynamodb.arn }
output "kinesis_key_arn" { value = aws_kms_key.kinesis.arn }
output "all_key_arns" {
  value = [
    aws_kms_key.s3.arn,
    aws_kms_key.secrets.arn,
    aws_kms_key.sagemaker.arn,
    aws_kms_key.dynamodb.arn,
    aws_kms_key.kinesis.arn,
  ]
}
