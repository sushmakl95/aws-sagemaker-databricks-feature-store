# Architecture

## Core decisions

**1. Feast as the unified abstraction, not "one platform wins."** SageMaker Feature Store is purpose-built for AWS-native ML teams. Databricks Feature Store is purpose-built for lakehouse-first teams. They're both good at their respective jobs. Rather than pick one, we expose both through Feast so downstream consumers write the same code either way. When we need to migrate a workload from one to the other, the consumer-side change is zero.

**2. Online + offline stores serve different access patterns.**
- **Online**: microsecond lookups keyed on entity_id. Used at inference time. Backed by DynamoDB (SageMaker track) or Online Tables (Databricks track). Sized for peak QPS, not total data volume.
- **Offline**: Full historical record of every feature value at every event time. Used for training + backfills + analysis. Backed by S3 + Glue catalog (SageMaker track) or Delta tables on S3 (Databricks track). Sized for total volume, not latency.

Both stores must agree on feature values at every ingestion point — this is online/offline parity, and it's the #1 cause of serving bugs in ML systems. See `docs/ONLINE_OFFLINE_PARITY.md`.

**3. Streaming features get their own path.** Per-event features (events_last_5min, seconds_since_last_event) are computed in Lambda directly from Kinesis. Batch features (account_age_days, total_spend) are computed by Spark daily. We don't try to unify them because the SLAs are different: streaming features must be fresh within seconds, batch features are fine being fresh within hours.

**4. Point-in-time correctness is enforced at training data assembly.** Naive joins on feature tables cause data leakage (training on features derived from post-event data). We use Feast's built-in PIT joins, which produce training rows where every feature value is AS OF the label's event timestamp. This costs 10-15% of training data volume (late-arriving features get dropped) but eliminates leakage. Non-negotiable.

**5. Model Monitor + custom drift detector, belt-and-suspenders.** SageMaker Model Monitor gives constraint-violation alerts (declarative, AWS-managed). Our custom drift detector computes PSI + KS statistics (programmable, works on Databricks Lakehouse Monitoring output too). Real teams run both: Monitor for "did a documented constraint break?", custom for "did the distribution shift in a way constraints didn't catch?"

**6. Data capture is always on.** Every inference request + response is logged to S3 (sampling 100% in prod; 10% in dev to save cost). This fuels Model Monitor, enables replay debugging, and is the ground truth for fairness audits. The $30/month extra cost is worth it; running ML in production without data capture is operating blind.

**7. Two training paths: SageMaker Training Jobs + Databricks ML.** SageMaker Training Jobs are better for: SPOT-heavy cost optimization, pure-Python training loops, heterogeneous hardware (CPU/GPU/Inferentia), integration with SageMaker Hosting. Databricks ML is better for: teams already in the Databricks ecosystem, PySpark feature engineering + training in one notebook, tighter MLflow Autolog integration, Unity Catalog model governance. We offer both because "which one wins" depends on the team, not the workload.

## Component interaction

### Streaming feature ingest flow

```
Application event
  → Kinesis put_record
  → Kinesis event source mapping (batch=100, window=10s)
  → Lambda streaming_feature_pipeline
  → Per-user state read from DynamoDB
  → Feature computation (rolling windows, ratios)
  → Per-user state written back to DynamoDB
  → PutRecord to SageMaker Feature Store (user_recency feature group)
  → (Parallel) Same batch to Databricks FS (if dual-track enabled)
```

End-to-end latency (event → feature available for inference): ~2-5 seconds P99, dominated by Kinesis batching window.

### Inference flow

```
Client POST /predict { "user_id": "U123" }
  → API Gateway REST API
  → SageMaker Endpoint (ml.m5.xlarge × 3 behind endpoint load balancer)
  → predictor.py model_fn (loaded once at startup)
  → predict_fn: Feast SDK get_online_features()
    → DynamoDB BatchGetItem on feature group tables
  → XGBoost predict_proba()
  → Response
  → Data capture to S3 (input + output)
```

End-to-end: P99 under 50 ms when online store is warm.

### Training flow (SageMaker path)

```
Nightly trigger (EventBridge)
  → CLI: features train-sagemaker
  → SageMakerTrainingRunner.submit()
  → SageMaker Training Job (SPOT)
  → Training container pulls from SMFS offline via Athena query
  → Train XGBoost, MLflow autolog to MLflow server
  → Model artifact → S3
  → Register to Model Package Group
  → Human approval → deploy to endpoint config → new variant → blue-green cut
```

### Drift monitoring flow

```
Hourly SageMaker Model Monitor job
  → Reads data capture (last hour) from S3
  → Compares against baseline statistics + constraints
  → Writes constraint_violations.json to reports bucket
  → EventBridge rule matches "MonitoringExecutionStatus=CompletedWithViolations"
  → Lambda drift_alerter
  → Parse violations → SNS email + Slack webhook
```

## What breaks this setup

- **Schema drift in feature groups**: SageMaker FS requires all records match the registered schema. Adding a feature requires a new feature group (no in-place schema migration). We version feature groups by suffix (`user_recency_v2`) and run both in parallel during rollover.
- **DynamoDB hot partitions**: if one entity_id is 1000× hotter than average (a bot, a test user), its partition gets throttled. Solution: use `user_id + shard_suffix` where shard is `hash(user_id) % 8`, then aggregate at read time. We document this in `docs/RUNBOOK.md` but don't implement by default because most teams don't hit it.
- **Feast registry corruption**: Feast uses a SQL-backed registry (Postgres here). Registry corruption = all feature views disappear. We run `pg_dump` via an hourly cron and keep 7 days.
- **Training/serving skew via Python version mismatch**: if training runs Python 3.11 but inference container is 3.10, some numpy/pandas type coercion differs. We pin identical images for both.

## What we don't do (and why)

- **Real-time feature materialization**: we write to both online + offline on ingest. We don't re-materialize from offline → online on a schedule. This keeps the offline store the source of truth for historical features but means online data is eventually consistent with offline (usually within seconds).
- **Multi-region feature stores**: DynamoDB Global Tables would let us serve features from multiple regions. We don't need this for the workloads we target (regional B2C apps). If you need cross-region inference, enable GTS on the DDB tables manually.
- **Feature transformations at lookup time**: Feast On-Demand Transformations let you compute features at inference from the request + online features. We configure but don't use this by default — debug-ability suffers, and most "on-demand" transforms are better computed upstream.

## Data lineage (what uses what)

```
Kinesis user-events
  ├── streaming_feature_pipeline Lambda
  │     └── user_recency feature group
  │           ├── churn_predictor model
  │           └── fraud_detector model
  └── DLT bronze table (Databricks track)
        └── DLT user_recency_features
              └── churn_predictor (Databricks variant)

Postgres orders (daily batch via Spark)
  └── user_lifetime feature group
        └── churn_predictor model

Catalog embeddings (nightly GPU job)
  └── product_features feature group
        └── recommendation_model
```

When deprecating a feature view: retire dependent models first. This is enforced by the feature-views CI gate (`scripts/validate_feature_views.py`) which fails if any registered model still uses a removed feature.

## Capacity planning

See `docs/COST_ANALYSIS.md` for real numbers. The production baseline assumes:
- 1,000 inference requests/second peak, 200/second average
- 5,000 Kinesis events/second peak
- 50 million feature records/day ingested
- 100 GB/day of data capture
- 10 TB total offline store after 6 months
