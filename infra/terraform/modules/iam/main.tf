variable "name_prefix" { type = string }
variable "s3_bucket_arns" { type = list(string) }
variable "kms_key_arns" { type = list(string) }
variable "feature_group_arns" { type = list(string) }

# ---------------------------------------------------------------------
# Lambda execution role
# ---------------------------------------------------------------------
resource "aws_iam_role" "lambda" {
  name = "${var.name_prefix}-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_kinesis" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaKinesisExecutionRole"
}

resource "aws_iam_role_policy" "lambda_access" {
  name = "${var.name_prefix}-lambda-access"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem",
          "dynamodb:UpdateItem", "dynamodb:Query",
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["sagemaker:PutRecord", "sagemaker:GetRecord", "sagemaker:DescribeFeatureGroup"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = concat(var.s3_bucket_arns, [for arn in var.s3_bucket_arns : "${arn}/*"])
      },
      {
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = var.kms_key_arns
      },
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
      },
    ]
  })
}

# ---------------------------------------------------------------------
# SageMaker Feature Store offline role
# ---------------------------------------------------------------------
resource "aws_iam_role" "sagemaker_fs_offline" {
  name = "${var.name_prefix}-sm-fs-offline-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sagemaker.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "sagemaker_fs_offline" {
  role = aws_iam_role.sagemaker_fs_offline.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:*"]
        Resource = concat(var.s3_bucket_arns, [for arn in var.s3_bucket_arns : "${arn}/*"])
      },
      {
        Effect   = "Allow"
        Action   = ["glue:*"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = var.kms_key_arns
      },
    ]
  })
}

# ---------------------------------------------------------------------
# SageMaker Training role
# ---------------------------------------------------------------------
resource "aws_iam_role" "sagemaker_training" {
  name = "${var.name_prefix}-sm-training-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sagemaker.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "sagemaker_training_full" {
  role       = aws_iam_role.sagemaker_training.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

resource "aws_iam_role_policy" "sagemaker_training_access" {
  role = aws_iam_role.sagemaker_training.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:*"]
        Resource = concat(var.s3_bucket_arns, [for arn in var.s3_bucket_arns : "${arn}/*"])
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = var.kms_key_arns
      },
    ]
  })
}

# ---------------------------------------------------------------------
# SageMaker Inference role
# ---------------------------------------------------------------------
resource "aws_iam_role" "sagemaker_inference" {
  name = "${var.name_prefix}-sm-inference-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sagemaker.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "sagemaker_inference_full" {
  role       = aws_iam_role.sagemaker_inference.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

resource "aws_iam_role_policy" "sagemaker_inference_access" {
  role = aws_iam_role.sagemaker_inference.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sagemaker:GetRecord", "sagemaker:BatchGetRecord",
          "dynamodb:BatchGetItem", "dynamodb:GetItem",
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = [for arn in var.s3_bucket_arns : "${arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = var.kms_key_arns
      },
    ]
  })
}

# ---------------------------------------------------------------------
# SageMaker Model Monitor role
# ---------------------------------------------------------------------
resource "aws_iam_role" "sagemaker_monitor" {
  name = "${var.name_prefix}-sm-monitor-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sagemaker.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "sagemaker_monitor_full" {
  role       = aws_iam_role.sagemaker_monitor.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

# ---------------------------------------------------------------------
# API Gateway -> SageMaker invocation role
# ---------------------------------------------------------------------
resource "aws_iam_role" "apigw_sagemaker" {
  name = "${var.name_prefix}-apigw-sm-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "apigateway.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "apigw_invoke" {
  role = aws_iam_role.apigw_sagemaker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sagemaker:InvokeEndpoint"]
      Resource = "*"
    }]
  })
}

# ---------------------------------------------------------------------
# Databricks instance profile (cross-account trust)
# ---------------------------------------------------------------------
resource "aws_iam_role" "databricks" {
  name = "${var.name_prefix}-databricks-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::414351767826:root" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "sts:ExternalId" = var.name_prefix }
      }
    }]
  })
}

resource "aws_iam_role_policy" "databricks_access" {
  role = aws_iam_role.databricks.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:*"]
        Resource = concat(var.s3_bucket_arns, [for arn in var.s3_bucket_arns : "${arn}/*"])
      },
      {
        Effect   = "Allow"
        Action   = ["kinesis:GetRecords", "kinesis:GetShardIterator", "kinesis:DescribeStream", "kinesis:ListShards"]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "databricks" {
  name = "${var.name_prefix}-databricks-profile"
  role = aws_iam_role.databricks.name
}

output "lambda_role_arn"                    { value = aws_iam_role.lambda.arn }
output "sagemaker_fs_offline_role_arn"      { value = aws_iam_role.sagemaker_fs_offline.arn }
output "sagemaker_training_role_arn"        { value = aws_iam_role.sagemaker_training.arn }
output "sagemaker_inference_role_arn"       { value = aws_iam_role.sagemaker_inference.arn }
output "sagemaker_monitor_role_arn"         { value = aws_iam_role.sagemaker_monitor.arn }
output "apigw_sagemaker_role_arn"           { value = aws_iam_role.apigw_sagemaker.arn }
output "databricks_instance_profile_arn"    { value = aws_iam_instance_profile.databricks.arn }
