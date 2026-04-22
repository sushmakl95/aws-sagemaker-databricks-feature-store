output "feature_store_offline_bucket" {
  value = module.s3.feature_store_offline_bucket_name
}

output "feature_group_names" {
  value = module.sagemaker_feature_store.feature_group_names
}

output "endpoint_name" {
  value = module.sagemaker_inference.endpoint_name
}

output "endpoint_arn" {
  value = module.sagemaker_inference.endpoint_arn
}

output "kinesis_stream_name" {
  value = module.kinesis.stream_name
}

output "state_table_name" {
  value = module.dynamodb.state_table_name
}

output "mlflow_tracking_uri" {
  value = module.mlflow.tracking_uri
}

output "api_gateway_invoke_url" {
  value = module.apigw.invoke_url
}

output "dashboard_url" {
  value = module.monitoring.dashboard_url
}
