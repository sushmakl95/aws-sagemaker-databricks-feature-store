variable "name_prefix" { type = string }
variable "endpoint_name" { type = string }
variable "feature_group_names" { type = list(string) }
variable "lambda_function_names" { type = list(string) }
variable "alarm_email_recipients" { type = list(string) }
variable "monthly_budget_usd" { type = number }
variable "log_retention_days" { type = number }

data "aws_region" "current" {}

resource "aws_sns_topic" "alerts" {
  name = "${var.name_prefix}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  for_each  = toset(var.alarm_email_recipients)
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = each.value
}

# ------------------------------------------------------------------
# Lambda log groups + alarms
# ------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "lambdas" {
  for_each          = toset(var.lambda_function_names)
  name              = "/aws/lambda/${each.value}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each            = toset(var.lambda_function_names)
  alarm_name          = "${var.name_prefix}-lambda-errors-${each.value}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = each.value
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

# ------------------------------------------------------------------
# Endpoint alarms
# ------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "endpoint_invocation_errors" {
  alarm_name          = "${var.name_prefix}-endpoint-4xx-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Invocation4XXErrors"
  namespace           = "AWS/SageMaker"
  period              = 300
  statistic           = "Sum"
  threshold           = 10
  treat_missing_data  = "notBreaching"

  dimensions = {
    EndpointName = var.endpoint_name
    VariantName  = "AllTraffic"
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "endpoint_latency" {
  alarm_name          = "${var.name_prefix}-endpoint-latency-p99"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "ModelLatency"
  namespace           = "AWS/SageMaker"
  period              = 60
  extended_statistic  = "p99"
  threshold           = 200000
  treat_missing_data  = "notBreaching"

  dimensions = {
    EndpointName = var.endpoint_name
    VariantName  = "AllTraffic"
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.name_prefix}-feature-platform"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/SageMaker", "Invocations", "EndpointName", var.endpoint_name, "VariantName", "AllTraffic"],
            [".", "ModelLatency", ".", ".", ".", "."],
          ]
          period = 60
          stat   = "Average"
          region = data.aws_region.current.name
          title  = "Endpoint Throughput + Latency"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            for fn in var.lambda_function_names :
            ["AWS/Lambda", "Duration", "FunctionName", fn]
          ]
          period = 300
          stat   = "Average"
          region = data.aws_region.current.name
          title  = "Lambda Duration"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 24
        height = 6
        properties = {
          metrics = [
            for fg in var.feature_group_names :
            ["FeaturePlatform", "RecordsIngested", "FeatureView", fg]
          ]
          period = 300
          stat   = "Sum"
          region = data.aws_region.current.name
          title  = "Feature Ingest Throughput"
        }
      },
    ]
  })
}

# ------------------------------------------------------------------
# Budget
# ------------------------------------------------------------------
resource "aws_budgets_budget" "monthly" {
  name              = "${var.name_prefix}-monthly"
  budget_type       = "COST"
  limit_amount      = tostring(var.monthly_budget_usd)
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  time_period_start = "2026-01-01_00:00"

  cost_filter {
    name   = "TagKeyValue"
    values = ["Project$${var.name_prefix}"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type           = "ACTUAL"
    subscriber_email_addresses = var.alarm_email_recipients
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.alarm_email_recipients
  }
}

output "alerts_topic_arn" { value = aws_sns_topic.alerts.arn }
output "dashboard_url" {
  value = "https://${data.aws_region.current.name}.console.aws.amazon.com/cloudwatch/home?region=${data.aws_region.current.name}#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}
