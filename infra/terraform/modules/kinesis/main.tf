variable "name_prefix" { type = string }
variable "kms_key_arn" { type = string }
variable "shard_count" { type = number }

resource "aws_kinesis_stream" "events" {
  name             = "${var.name_prefix}-user-events"
  shard_count      = var.shard_count
  retention_period = 72

  encryption_type = "KMS"
  kms_key_id      = var.kms_key_arn

  shard_level_metrics = [
    "IncomingBytes",
    "IncomingRecords",
    "OutgoingBytes",
    "OutgoingRecords",
    "IteratorAgeMilliseconds",
  ]

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }
}

output "stream_name" { value = aws_kinesis_stream.events.name }
output "stream_arn"  { value = aws_kinesis_stream.events.arn }
