variable "name_prefix" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_id" { type = string }
variable "execution_role_arn" { type = string }
variable "kinesis_stream_arn" { type = string }
variable "state_table_name" { type = string }
variable "feature_group_name" { type = string }
variable "sns_alerts_topic_arn" { type = string }
variable "monitor_reports_bucket" { type = string }
variable "slack_webhook_url_secret" { type = string }

data "archive_file" "lambdas" {
  type        = "zip"
  source_dir  = "${path.module}/../../../../src"
  output_path = "${path.module}/lambdas.zip"
  excludes    = ["**/__pycache__/**", "**/*.pyc"]
}

# ---------------------------------------------------------------------
# Streaming feature pipeline Lambda
# ---------------------------------------------------------------------
resource "aws_lambda_function" "streaming_features" {
  function_name    = "${var.name_prefix}-streaming-features"
  role             = var.execution_role_arn
  runtime          = "python3.11"
  handler          = "lambdas.streaming_feature_pipeline.handler"
  filename         = data.archive_file.lambdas.output_path
  source_code_hash = data.archive_file.lambdas.output_base64sha256
  timeout          = 60
  memory_size      = 1024

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [var.security_group_id]
  }

  environment {
    variables = {
      FEATURE_GROUP_NAME = var.feature_group_name
      STATE_TABLE_NAME   = var.state_table_name
    }
  }
}

resource "aws_lambda_event_source_mapping" "kinesis_to_streaming" {
  event_source_arn              = var.kinesis_stream_arn
  function_name                 = aws_lambda_function.streaming_features.arn
  starting_position             = "LATEST"
  batch_size                    = 100
  maximum_batching_window_in_seconds = 10
  parallelization_factor        = 2
}

# ---------------------------------------------------------------------
# Drift alerter Lambda
# ---------------------------------------------------------------------
resource "aws_lambda_function" "drift_alerter" {
  function_name    = "${var.name_prefix}-drift-alerter"
  role             = var.execution_role_arn
  runtime          = "python3.11"
  handler          = "lambdas.drift_alerter.handler"
  filename         = data.archive_file.lambdas.output_path
  source_code_hash = data.archive_file.lambdas.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      SNS_TOPIC_ARN            = var.sns_alerts_topic_arn
      SLACK_WEBHOOK_URL_SECRET = var.slack_webhook_url_secret
    }
  }
}

# EventBridge rule -> drift alerter
resource "aws_cloudwatch_event_rule" "monitor_completed" {
  name        = "${var.name_prefix}-monitor-completed"
  description = "Fires when SageMaker Model Monitor job completes"
  event_pattern = jsonencode({
    source      = ["aws.sagemaker"]
    detail-type = ["SageMaker Model Monitoring Job Status Change"]
    detail = {
      MonitoringExecutionStatus = ["Completed", "CompletedWithViolations"]
    }
  })
}

resource "aws_cloudwatch_event_target" "drift_alerter" {
  rule      = aws_cloudwatch_event_rule.monitor_completed.name
  target_id = "drift-alerter-lambda"
  arn       = aws_lambda_function.drift_alerter.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.drift_alerter.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.monitor_completed.arn
}

output "streaming_features_arn" { value = aws_lambda_function.streaming_features.arn }
output "drift_alerter_arn"      { value = aws_lambda_function.drift_alerter.arn }
output "all_function_names" {
  value = [
    aws_lambda_function.streaming_features.function_name,
    aws_lambda_function.drift_alerter.function_name,
  ]
}
