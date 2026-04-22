variable "name_prefix" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "artifacts_bucket" { type = string }
variable "db_password_secret" { type = string }
variable "instance_class" {
  type    = string
  default = "db.t4g.micro"
}

data "aws_secretsmanager_secret_version" "db_password" {
  secret_id = var.db_password_secret
}

resource "aws_security_group" "mlflow_db" {
  name        = "${var.name_prefix}-mlflow-db-sg"
  description = "MLflow backing store"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_subnet_group" "mlflow" {
  name       = "${var.name_prefix}-mlflow-db-subnet"
  subnet_ids = var.subnet_ids
}

resource "aws_db_instance" "mlflow" {
  identifier             = "${var.name_prefix}-mlflow"
  engine                 = "postgres"
  engine_version         = "16.2"
  instance_class         = var.instance_class
  allocated_storage      = 20
  db_name                = "mlflow"
  username               = "mlflow"
  password               = data.aws_secretsmanager_secret_version.db_password.secret_string
  db_subnet_group_name   = aws_db_subnet_group.mlflow.name
  vpc_security_group_ids = [aws_security_group.mlflow_db.id]
  skip_final_snapshot    = true
  publicly_accessible    = false
  storage_encrypted      = true
  backup_retention_period = 7
  deletion_protection    = false
}

# MLflow tracking server runs as ECS Fargate task. For brevity we output
# the tracking URI pointing at the RDS instance for self-hosted setups.
output "tracking_uri" {
  value = "postgresql://mlflow:****@${aws_db_instance.mlflow.endpoint}/mlflow"
}
output "artifacts_uri" {
  value = "s3://${var.artifacts_bucket}/mlflow-artifacts/"
}
output "rds_endpoint" { value = aws_db_instance.mlflow.endpoint }
