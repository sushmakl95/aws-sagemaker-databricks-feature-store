# Operations Runbook

## On-call severity matrix

| Severity | Trigger | SLA to ack | Action |
|---|---|---|---|
| P0 | Inference endpoint returning 5xx > 1% for 5 min | 5 min | Page |
| P0 | Feature store online store unreachable | 5 min | Page |
| P0 | Streaming feature Lambda failing > 50% of invocations | 5 min | Page |
| P1 | Drift detected (PSI > 0.25) on any production feature | 30 min | Slack |
| P1 | Batch feature pipeline hasn't run in 25h | 30 min | Slack |
| P1 | Model Monitor job failing | 30 min | Slack |
| P2 | Single Lambda error spike, others healthy | Next business day | Backlog |

## Common scenarios

### 1. Endpoint 5xx errors

**Symptoms**: CloudWatch alarm `endpoint-4xx-errors` firing. API Gateway returning 502.

**Diagnosis**:
```bash
# Endpoint status
aws sagemaker describe-endpoint --endpoint-name <endpoint> \
  --query '{Status:EndpointStatus,Instances:ProductionVariants[0].CurrentInstanceCount}'

# Model container logs
aws logs tail /aws/sagemaker/Endpoints/<endpoint> --follow

# Look for model_fn / predict_fn exceptions
```

**Common causes + fixes**:
- **Model container OOM**: increase instance size via `UpdateEndpointConfig` + `UpdateEndpoint`
- **Feast online store unreachable from container**: check VPC config; container needs access to DynamoDB via VPC endpoint or NAT
- **Model artifact corrupt**: check `model.tar.gz` in S3; roll back to previous model version via `aws sagemaker update-endpoint --endpoint-config-name <prior-config>`

### 2. Streaming feature Lambda failing

**Symptoms**: Kinesis `IteratorAge` growing. Lambda error rate > 10%.

**Diagnosis**:
```bash
aws logs tail /aws/lambda/<prefix>-streaming-features --follow --since 15m
```

**Common causes + fixes**:
- **DynamoDB throttling on state table**: symptom is `ProvisionedThroughputExceededException`. Switch to on-demand billing (one-click in console), or pre-scale partitions.
- **SageMaker FS PutRecord throttling**: symptom is `ThrottlingException`. Already retried with backoff in the sink — check if throttle rate is per-second (FeatureGroup cap = 10K/sec). Shard input or request quota increase.
- **Poison record**: one specific event causes parse exception, same record retried, pipeline stuck. Check DLQ; skip the record with a hotfix to the parser.
- **Lambda concurrency cap**: check reserved concurrency on the function. Default account concurrency = 1000. If other functions compete, add reserved concurrency.

### 3. Feature drift alert

**Symptoms**: Slack/SNS alert from `drift_alerter` Lambda.

**Diagnosis**:
1. Open the drift dashboard (Databricks SQL)
2. Check which features drifted (count, magnitude, timing)
3. Correlate with:
   - Recent deploys to any upstream pipeline
   - Marketing campaigns or product launches
   - Holidays or seasonal effects
   - Customer base changes (new geographic markets?)

**Actions**:
- **Explained drift (holiday / campaign)**: document + optionally retrain on fresh data
- **Pipeline bug (bad data upstream)**: fix the pipeline, backfill affected window, retrain
- **Real user behavior shift**: trigger retrain via `features train-sagemaker --mlflow-tag drift-retrain=<date>`
- **Uncertain**: run an A/B test with retrained model before promoting

### 4. Feature freshness alert

**Symptoms**: `feature_freshness_registry` shows a FV stale > 2× its TTL.

**Diagnosis**:
```bash
# Last ingest time per FV
aws sagemaker describe-feature-group --feature-group-name <fg> \
  --query 'LastModifiedTime'

# Is the batch/streaming pipeline running?
aws lambda get-function --function-name <streaming-fn>  # state, last invoke
aws emr-serverless list-job-runs --application-id <id>  # last batch run
```

**Common causes + fixes**:
- **Batch pipeline failed silently**: check the scheduler (EventBridge/Airflow), re-run
- **Source data missing**: upstream Kinesis stream has no events — check producer health
- **Write failure mid-batch**: check Lambda DLQ, replay failed batches

### 5. Model Monitor job failing

**Symptoms**: Monitor schedule in `Failed` state.

**Diagnosis**:
```bash
aws sagemaker list-monitoring-executions \
  --monitoring-schedule-name <schedule> \
  --status-equals Failed \
  --max-results 5
```

**Common causes + fixes**:
- **No data capture in last hour**: if endpoint had no traffic, Monitor skips. Harmless if expected (e.g., after-hours low traffic). Otherwise, investigate traffic drop.
- **Baseline JSON missing**: baseline wasn't uploaded to S3 at training time. Run `scripts/generate_baseline.py` from the latest training run and upload to `s3://.../baselines/`.
- **Container doesn't have permission to read data capture**: update `sagemaker_monitor` IAM role.

### 6. Online/offline parity failure

**Symptoms**: nightly `test_parity.py` fails.

**Diagnosis**: the test pinpoints the specific entity_id + feature that disagrees. Check:
1. The SMFS offline store (Athena query on the feature group's Glue table)
2. The SMFS online store (`sagemaker-featurestore-runtime.get_record` for the entity)
3. If values differ: trace to the Lambda invocation that wrote this entity. Did both online + offline commit?

**Fix**: delete the mismatched record from both stores; re-ingest from source events. If this is a systemic bug, pause the Lambda, dual-write a fix via `scripts/backfill_parity.py`, resume.

### 7. DynamoDB hot partition

**Symptoms**: one specific `user_id` returns 400s; Lambda retries burning CPU.

**Diagnosis**:
```bash
# Get per-partition metrics
aws dynamodb describe-table --table-name <table> \
  --query 'Table.ItemCount,Table.TableSizeBytes'

# Check per-partition throttles
aws cloudwatch get-metric-statistics --namespace AWS/DynamoDB \
  --metric-name ReadThrottleEvents --dimensions Name=TableName,Value=<table> \
  --statistics Sum --period 300 --start-time ... --end-time ...
```

**Fix**: shard writes by appending `:shard-<n>` where `n = hash(user_id) % 8`. Aggregate at read time. Only needed when one entity is 100× hotter than P99.

### 8. Training job failing

**Symptoms**: nightly `sagemaker_runner` submission returns Failed.

**Diagnosis**:
```bash
aws sagemaker describe-training-job --training-job-name <job> \
  --query 'FailureReason'

aws logs tail /aws/sagemaker/TrainingJobs/<job> --follow
```

**Common causes + fixes**:
- **Not enough spot capacity**: job waited 2 hours, no SPOT. Fall back to on-demand (`--no-spot` flag).
- **Training data missing**: check S3 input path exists and has data. If the upstream feature pipeline failed, its output is empty.
- **OOM during training**: larger instance (`ml.m5.2xlarge`) or reduce `n_estimators`.
- **MLflow tracking URI unreachable**: check MLflow server health (RDS endpoint + ECS task).

### 9. Endpoint rollout failure

**Symptoms**: deploying a new model version fails; endpoint status stuck in `Updating`.

**Diagnosis**:
```bash
aws sagemaker describe-endpoint --endpoint-name <endpoint>
aws sagemaker describe-endpoint-config --endpoint-config-name <config>
```

**Fix**:
- **Wrong model package**: roll forward/back by updating endpoint to known-good endpoint config:
  ```bash
  aws sagemaker update-endpoint \
    --endpoint-name <endpoint> \
    --endpoint-config-name <prior-known-good>
  ```
- **Insufficient capacity in AZ**: wait, or spread to more AZs via a new endpoint config.
- **Bad model artifact**: test locally with `predictor.model_fn(<model_dir>)` — if it fails, fix the model build before retrying.

## CLI cheat sheet

```bash
# List all feature groups
aws sagemaker list-feature-groups

# Get one record
aws sagemaker-featurestore-runtime get-record \
  --feature-group-name <fg> --record-identifier-value-as-string U123

# Query offline store via Athena
aws athena start-query-execution \
  --query-string "SELECT * FROM feature_platform_feature_store.user_recency WHERE entity_id = 'U123' ORDER BY event_time DESC LIMIT 10"

# Tail streaming Lambda
aws logs tail /aws/lambda/feature-platform-prod-streaming-features --follow

# Tail endpoint invocation logs
aws logs tail /aws/sagemaker/Endpoints/feature-platform-prod-churn-endpoint --follow

# Endpoint metrics
aws cloudwatch get-metric-statistics --namespace AWS/SageMaker \
  --metric-name Invocations --dimensions Name=EndpointName,Value=<> Name=VariantName,Value=AllTraffic \
  --statistics Sum --period 60 --start-time 1h-ago --end-time now
```

## Scaling operations

**Increase endpoint instance count**:
```bash
aws sagemaker update-endpoint-weights-and-capacities \
  --endpoint-name <endpoint> \
  --desired-weights-and-capacities VariantName=AllTraffic,DesiredInstanceCount=5
```

**Increase Kinesis shards**:
```bash
aws kinesis update-shard-count --stream-name <s> \
  --target-shard-count 8 --scaling-type UNIFORM_SCALING
```

**Increase Lambda reserved concurrency**:
```bash
aws lambda put-function-concurrency \
  --function-name <fn> --reserved-concurrent-executions 100
```

## Post-incident review template

Every P0 deserves a review within 5 business days.

1. Timeline (first symptom → ack → mitigation → resolution → RCA)
2. Root cause (actual failure, not the symptom)
3. Impact (predictions affected, customer impact, financial)
4. Detection (how did we find out? could we have found out faster?)
5. Prevention (action items with owners + deadlines)
