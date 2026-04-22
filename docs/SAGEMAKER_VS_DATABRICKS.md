# SageMaker vs Databricks for ML Platform Workloads

## TL;DR

| Capability | SageMaker | Databricks |
|---|---|---|
| **Best fit** | AWS-native org, cost-sensitive, custom containers | Lakehouse-first org, data + ML in one platform |
| **Feature Store online** | DynamoDB-backed (managed) | Online Tables (serverless-ish) |
| **Feature Store offline** | S3 + Glue/Athena | Delta + Unity Catalog |
| **Training compute** | Managed jobs, SPOT support | Jobs clusters, SPOT support |
| **Serving latency** | P99 ~30-50ms (managed endpoints) | P99 ~50-80ms (Model Serving) |
| **Observability** | CloudWatch + Model Monitor | Workspace UI + Lakehouse Monitoring |
| **Cost for 1K predictions/sec** | ~$230/mo for FS + compute | ~$275/mo for FS + compute |
| **Python ecosystem** | ✅ full | ✅ full |
| **SQL + notebook integration** | ⚠️ SageMaker Studio works but separate | ✅ native (Databricks SQL + notebooks) |
| **Lock-in** | AWS-heavy | Databricks-heavy |

## Dimension-by-dimension

### Feature Store online lookup

**SageMaker FS**: reads hit DynamoDB. Latency is ~2-10ms P99. Scales to millions of records per second. You pay for DynamoDB RCU/WCU, which adds up at scale but is clear + predictable.

**Databricks FS Online Tables**: reads hit Databricks' managed online-serving layer. Latency is ~5-15ms P99. Sizing is less transparent (serverless-like). Costs are billed as Databricks DBUs, which makes cross-team cost attribution harder.

**Winner**: SageMaker FS if you need microsecond-level predictability. Databricks FS if you're happy with slightly higher latency in exchange for tighter integration with Delta tables.

### Feature Store offline training data

**SageMaker FS**: written continuously to S3 (append-only Parquet). Glue crawler makes it queryable via Athena. Point-in-time joins via Feast or direct SQL. S3 costs are negligible, but Athena query costs add up at scale.

**Databricks FS**: written to Delta tables in Unity Catalog. Native ASOF JOIN for PIT correctness. Delta's transaction log provides exact point-in-time reads. Better at scale (10TB+ feature tables).

**Winner**: Databricks FS at 10TB+ scale. SageMaker FS is simpler for smaller tables.

### Training compute

**SageMaker Training Jobs**:
- Managed: you submit a container, SageMaker pulls it, runs, writes output to S3, terminates.
- Excellent SPOT support via Managed Spot Training + automatic checkpoint restoration.
- Hyperparameter tuning via SageMaker HPO (Bayesian + random search).
- Distributed training via built-in MPI/Horovod, or custom.
- Cold start: ~2 minutes to pull container + start.

**Databricks ML Jobs**:
- Notebook-driven or script-driven. Runs on a Databricks cluster.
- SPOT support for cluster instances.
- MLflow autologging is tightly integrated.
- Cold start: ~1-5 minutes depending on cluster reuse.

**Winner**: tie. SageMaker is better for "one-off container with specific deps". Databricks is better for "iterative notebook development that also needs to run as a scheduled job".

### Serving

**SageMaker Endpoints**:
- Always-on instances (`ml.m5.xlarge` × N behind a load balancer).
- Blue-green deploys via endpoint config.
- Data capture built in.
- Multi-model endpoints + Serverless Inference variants available.
- Cost: instance-hour based. 3 × `ml.m5.xlarge` 24/7 = ~$520/mo.

**Databricks Model Serving**:
- Container-based; autoscaling 0 → N.
- Built-in request logging.
- Tighter integration with Unity Catalog model registry.
- Cost: DBU-based. Depends on model size + scaling policy. Usually slightly more expensive than SageMaker for steady traffic.

**Winner**: SageMaker for steady high-QPS traffic (predictable cost). Databricks for bursty traffic + low baseline (autoscaling advantage).

### Observability + monitoring

**SageMaker Model Monitor**: managed, scheduled jobs. Produces structured JSON reports. Supports data quality + model bias + model explainability + model quality monitors. Integrates with CloudWatch. Setup is declarative (define baseline + schedule).

**Databricks Lakehouse Monitoring**: declarative monitors on Delta tables. Tracks statistics over time. Drift via `TimeSeriesMonitor`. Builds dashboards automatically. Good for data drift; model-specific monitoring (bias, explainability) less baked-in.

**Winner**: SageMaker for ML-specific monitoring (bias + explainability managed). Databricks for "any Delta table + general data quality".

### Developer experience

**SageMaker**:
- SageMaker Studio: Jupyter-based IDE, decent for interactive work
- SDK (`sagemaker.Estimator`) is Pythonic
- Debugging: step into container code locally via `local_mode=True` is possible but fiddly
- Ecosystem: AWS CLI + boto3 everywhere

**Databricks**:
- Databricks Notebooks: best-in-class for notebook-driven development
- Workflows for scheduling
- Debugging: REPL-like, interactive cluster attach
- Ecosystem: Databricks CLI, MLflow client

**Winner**: Databricks for interactive model development. SageMaker for "I want an API, not an IDE."

### Model governance

**SageMaker Model Registry**: model packages + package groups. Approval workflow. Integrates with CodePipeline for deployment gates.

**Databricks Model Registry (Unity Catalog)**: 3-part namespace (catalog.schema.model). Aliases (`@Production`). Integrates with Databricks Jobs + model serving + Unity Catalog governance.

**Winner**: Unity Catalog if you're in the Databricks ecosystem. SageMaker Registry otherwise.

### Cost at 1K predictions/second

| Component | SageMaker | Databricks |
|---|---|---|
| Online feature store | $75 (DynamoDB) | $110 (Online Tables) |
| Offline feature store | $70 (S3 + Glue) | $50 (Delta on S3) |
| Batch feature ingest compute | $40 (EMR Serverless) | $80 (Databricks jobs) |
| Monitoring | $45 (Model Monitor) | $35 (Lakehouse Monitoring) |
| **Subtotal (feature + monitoring)** | **$230/mo** | **$275/mo** |
| Serving endpoint (24/7) | $520 (SageMaker) | $560 (Model Serving) |
| Training (daily) | $12 | $28 |
| **Total** | **$762/mo** | **$863/mo** |

At this scale, SageMaker is ~13% cheaper. Delta breaks down at 10TB+ offline tables where Databricks' read efficiency outweighs SageMaker's base cost.

### Team skill fit

- **AWS-heavy team**: SageMaker lets you use skills you already have (IAM, VPC, CloudWatch, boto3, Terraform).
- **Data-engineering-heavy team**: Databricks unifies data + ML, reducing context switching.
- **Mixed team**: either works, but you'll invest in one and the other becomes a second-class citizen.

## When to pick which

**Pick SageMaker if**:
- Your org is already heavy on AWS (IAM, VPC, VPC endpoints, existing Terraform)
- You need tight cost control — DynamoDB pricing + endpoint instance-hour is predictable
- You want ML-specific features (Clarify for bias, Debugger, Neo for inference optimization)
- You have custom training containers with non-Python deps

**Pick Databricks if**:
- Your data platform is already Databricks — don't fragment
- You value integrated notebook-to-production workflow
- You have >10TB feature tables where Delta's query efficiency matters
- Your team prefers SQL + notebooks over Python SDK

**Pick both** (this repo's setup) if:
- You're actively migrating from one to the other and need overlap
- Different teams within the org have different preferences
- You want to comparison-shop cost + performance on your specific workload before committing

## Empirical observations from running both

1. **SageMaker's Feature Store offline store is underappreciated.** The S3 + Glue setup looks old-school but it's actually the most flexible (Athena, Redshift Spectrum, Spark, Trino all work without modification).

2. **Databricks' Unity Catalog lineage is hard to match elsewhere.** Out of the box, you can see "this model uses this feature table". SageMaker lineage works but requires more manual tracking.

3. **Operationally, SageMaker has lower daily overhead.** Fewer moving parts — no cluster lifecycle, no notebook version drift. Databricks requires more "who can access what cluster" thinking.

4. **Cost comparisons are highly workload-dependent.** At small scale (< 100 predictions/sec), Databricks is often cheaper because Model Serving scales to zero. At large scale (> 10K predictions/sec), SageMaker's instance-hour model beats DBU-based billing.

5. **Don't switch for 10% savings.** The migration cost exceeds 2 years of savings. Switch because the other platform solves a structural problem, not a cost one.
