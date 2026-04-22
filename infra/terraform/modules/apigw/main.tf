variable "name_prefix" { type = string }
variable "inference_endpoint_arn" { type = string }
variable "api_invocation_role" { type = string }

data "aws_region" "current" {}

# Extract endpoint name from ARN (last segment)
locals {
  endpoint_name = element(split("/", var.inference_endpoint_arn), length(split("/", var.inference_endpoint_arn)) - 1)
}

resource "aws_api_gateway_rest_api" "this" {
  name        = "${var.name_prefix}-predictions-api"
  description = "REST API fronting SageMaker inference endpoint"
  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_resource" "predict" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  parent_id   = aws_api_gateway_rest_api.this.root_resource_id
  path_part   = "predict"
}

resource "aws_api_gateway_method" "post" {
  rest_api_id   = aws_api_gateway_rest_api.this.id
  resource_id   = aws_api_gateway_resource.predict.id
  http_method   = "POST"
  authorization = "AWS_IAM"
}

resource "aws_api_gateway_integration" "sagemaker" {
  rest_api_id             = aws_api_gateway_rest_api.this.id
  resource_id             = aws_api_gateway_resource.predict.id
  http_method             = aws_api_gateway_method.post.http_method
  integration_http_method = "POST"
  type                    = "AWS"
  uri                     = "arn:aws:apigateway:${data.aws_region.current.name}:runtime.sagemaker:path/endpoints/${local.endpoint_name}/invocations"
  credentials             = var.api_invocation_role
  passthrough_behavior    = "WHEN_NO_MATCH"
}

resource "aws_api_gateway_method_response" "ok" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  resource_id = aws_api_gateway_resource.predict.id
  http_method = aws_api_gateway_method.post.http_method
  status_code = "200"
}

resource "aws_api_gateway_integration_response" "ok" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  resource_id = aws_api_gateway_resource.predict.id
  http_method = aws_api_gateway_method.post.http_method
  status_code = aws_api_gateway_method_response.ok.status_code
  depends_on  = [aws_api_gateway_integration.sagemaker]
}

resource "aws_api_gateway_deployment" "this" {
  rest_api_id = aws_api_gateway_rest_api.this.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.predict.id,
      aws_api_gateway_method.post.id,
      aws_api_gateway_integration.sagemaker.id,
    ]))
  }

  depends_on = [aws_api_gateway_integration_response.ok]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.this.id
  rest_api_id   = aws_api_gateway_rest_api.this.id
  stage_name    = "prod"
}

output "invoke_url" { value = aws_api_gateway_stage.prod.invoke_url }
output "api_id"     { value = aws_api_gateway_rest_api.this.id }
