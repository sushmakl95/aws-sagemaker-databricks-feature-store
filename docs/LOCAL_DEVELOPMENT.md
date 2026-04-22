# Local Development

Run the platform end-to-end locally without an AWS account.

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11 | Runtime |
| Java | 17 | PySpark |
| Docker | 24+ | LocalStack + Postgres + Redis + MLflow |
| Make | any | Convenience |

## Setup

```bash
git clone https://github.com/sushmakl95/aws-sagemaker-databricks-feature-store.git
cd aws-sagemaker-databricks-feature-store
make install-dev
make compose-up
```

Compose starts:
- **LocalStack** (Kinesis, DynamoDB, S3) on localhost:4566
- **Postgres 16** (Feast registry + MLflow backend) on localhost:5432
- **Redis 7** (as online store for local Feast config) on localhost:6379
- **MLflow tracking server** on localhost:5000

Wait ~30 seconds for all services to be healthy, then:

```bash
make bootstrap-local
```

This creates the local Kinesis stream, DynamoDB state table, S3 buckets, and initializes the Feast registry.

## Run the streaming pipeline locally

```bash
make seed-sample-events        # writes 10K events to LocalStack Kinesis
make run-streaming-features    # runs the Lambda handler as a local process
```

You should see logs like:
```
INFO lambda_batch_done input_records=100 feature_records=85 ingested=85 failed=0
```

Check DynamoDB state (via LocalStack):
```bash
aws --endpoint-url http://localhost:4566 dynamodb scan \
  --table-name feature-platform-local-user-state --limit 5
```

Check SageMaker FS records (mocked by LocalStack):
```bash
aws --endpoint-url http://localhost:4566 sagemaker list-feature-groups
```

## Run a training job locally

```bash
make generate-training-data    # builds a synthetic training set from local features
make train-local               # runs features/training/train.py with XGBoost
```

MLflow UI at http://localhost:5000 shows the run, params, and metrics.

## Run drift detection locally

```bash
make generate-baseline
make simulate-drift            # injects drifted records into current data
make check-drift
```

Produces `./drift-report.json` — inspect it to see which features drifted.

## Interactive development

### Using Jupyter

```bash
make notebook
```

Opens Jupyter at http://localhost:8888 with the Python + PySpark kernel.

### Using the CLI

```bash
features --help
features feast-sync --dry-run
features train --training-data-path ./data/local_training.parquet --local
features check-drift --baseline-path ./baseline.parquet --current-path ./current.parquet
```

## Testing

### Unit tests

```bash
make test-unit
```

Runs in ~20 seconds. Uses a local SparkSession and in-memory Feast store.

### Integration tests

```bash
make compose-up
make test-integration
```

Takes ~5 minutes. Exercises the full Kinesis → Lambda → FS → lookup path against LocalStack.

### Online/offline parity test

```bash
pytest tests/integration/test_parity.py -v
```

Writes a test record, waits 10s, asserts online.read == offline.read.

## What doesn't work locally

- **SageMaker Endpoint inference** — LocalStack doesn't implement endpoints. We mock with a Flask wrapper around `predictor.py`.
- **Model Monitor** — LocalStack doesn't have this. Tested only against real AWS.
- **Databricks integrations** — require a real Databricks workspace. The `databricks_fs_sink.py` raises `RuntimeError` if imported outside Databricks ML runtime.
- **API Gateway + SageMaker integration** — LocalStack's AWS_PROXY integration is partial. Use the Flask wrapper directly.

## Shutting down

```bash
make compose-down       # stops containers, keeps volumes
make compose-clean      # stops containers + removes volumes (DESTRUCTIVE)
```

## Environment variables

`.env.example` → copy to `.env` (gitignored):

```bash
AWS_REGION=us-east-1
AWS_ENDPOINT_URL=http://localhost:4566   # LocalStack
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test

FEATURES_LOG_LEVEL=INFO
FEATURES_LOG_FORMAT=console

FEAST_REGISTRY_URI=postgresql://feast:feast@localhost:5432/feast_registry
MLFLOW_TRACKING_URI=http://localhost:5000

LOCAL_DEV=true
```

## IDE setup

**VS Code**: install Python + Ruff + HashiCorp Terraform extensions. The repo's `pyproject.toml` + `.pre-commit-config.yaml` are auto-detected.

**PyCharm**: mark `src/` as Sources Root. Use the venv from `make install-dev`.

## Common issues

**"Kinesis stream not found"** after `make compose-up`: LocalStack takes 30+ seconds to be ready. Run `make bootstrap-local` only after containers are healthy.

**"Feast SQL registry locked"**: stale lock from a killed process. `psql -h localhost -U feast -c "UPDATE feast_registry.registry SET in_progress = false;"`

**"PySpark OOM in tests"**: bump driver memory via `make test-unit SPARK_DRIVER_MEMORY=4g`.

**"MLflow server can't connect to Postgres"**: check `docker compose logs postgres` — if it's still initializing, wait. `make compose-up` has a `depends_on: healthy` check but sometimes first boot is slow.
