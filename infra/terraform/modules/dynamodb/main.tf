variable "name_prefix" { type = string }
variable "kms_key_arn" { type = string }

resource "aws_dynamodb_table" "state" {
  name         = "${var.name_prefix}-user-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"

  attribute {
    name = "user_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name    = "${var.name_prefix}-user-state"
    Purpose = "streaming-feature-state"
  }
}

output "state_table_name" { value = aws_dynamodb_table.state.name }
output "state_table_arn"  { value = aws_dynamodb_table.state.arn }
