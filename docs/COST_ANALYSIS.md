# Cost Analysis

Production deployment at moderate inference throughput (1K predictions/second peak) costs approximately **$1,250/month**. For local evaluation, the Docker Compose stack costs $0.

## Breakdown (us-east-1, April 2026)

| Resource | Config | $/month |
|---|---|---|
| **SageMaker Inference Endpoint** | ml.m5.xlarge × 3 (24/7) | $520 |
| **SageMaker Feature Store (online)** | DynamoDB on-demand, ~30M reads/mo + 10M writes | $75 |
| **SageMaker Feature Store (offline)** | S3 ~3 TB + Glue catalog | $70 |
| **SageMaker Model Monitor** | hourly ml.m5.xlarge × 30 min/day | $45 |
| **SageMaker Training Jobs** | 1 daily run, ml.m5.xlarge × 45 min, SPOT | $12 |
| **Kinesis Data Streams** | 4 shards × 24/7 | $45 |
| **Lambda (streaming features)** | ~2M invocations/mo, 1GB memory | $18 |
| **Lambda (drift alerter)** | ~720 invocations/mo | $0.50 |
| **DynamoDB (state table)** | PAY_PER_REQUEST, ~10M RCU + 10M WCU | $15 |
| **API Gateway (REST)** | 30M requests/mo | $105 |
| **MLflow (RDS Postgres db.t4g.small)** | 24/7 | $30 |
| **VPC (3 NAT Gateways)** | 3 × $32/mo + data | $100 |
| **Gateway endpoints (S3 + DynamoDB)** | free (reduce NAT traffic) | $0 |
| **Secrets Manager** | 3 secrets × $0.40 | $1.20 |
| **KMS** | 5 CMKs + ~1M API calls | $8 |
| **CloudWatch** | logs 30d + 50 metrics + dashboard | $60 |
| **SNS + EventBridge** | <$1 | $1 |
| **Data Capture S3** | ~100 GB/mo | $5 |
| **Databricks (comparison track)** | i3.xlarge × 2, SPOT, ~4h/day | $45 |
| **Cross-AZ data transfer** | ~500 GB/mo | $10 |

**Total: ~$1,160-1,280/month**

Real production deployments land $900-1,800 depending on endpoint scale + inference volume.

## Cost drivers

**1. SageMaker Endpoint (45%).** 3 × ml.m5.xlarge is the default for HA. Can reduce to 2 × ml.t2.medium in dev for ~$80/month. Cannot use SPOT on real-time endpoints.

**2. VPC (8%).** 3 NATs × $32/mo plus data transfer. S3 + DynamoDB gateway endpoints save ~60% of NAT traffic. Dev environments can run single-AZ with 1 NAT for ~$64/month savings.

**3. API Gateway (9%).** $3.50 per million requests. At 30M/month that's $105. For internal-only inference, replace with a direct SageMaker invocation from the consumer's IAM role to save 100% of API GW cost.

**4. Model Monitor (4%).** Hourly schedule is the minimum useful cadence. Running daily saves ~$30/mo but drift gets detected 24h later.

**5. Online FS (6%).** DynamoDB on-demand pricing is a good default. If QPS is steady, provisioned capacity with auto-scaling is 40% cheaper but requires tuning.

## Optimization playbook

### Low-effort (save ~$200/month)

- **Single-AZ dev/staging**: $64/mo per NAT avoided
- **Drop to 2 endpoint instances in non-prod**: $175/mo saved
- **Shorter CloudWatch retention** (7 days in dev, 30 in staging): $30/mo saved
- **Inference Recommender**: use the right instance type. Default `ml.m5.xlarge` is often oversized. Recommender suggests `ml.c6i.large` for CPU-bound inference — 30% cheaper.

### Medium-effort (save ~$150/month)

- **DynamoDB provisioned + auto-scaling**: $30/mo saved at 30M requests/mo
- **Replace API Gateway with SageMaker direct invocation** (internal consumers only): $105/mo saved
- **SageMaker Serverless Inference** for bursty workloads: pay per request, no minimum. Only works if P99 latency tolerance is ~1s (cold starts).
- **Data capture sampling at 10% in steady state**: $3/mo saved (small), but mostly reduces Monitor compute cost by ~10%

### High-effort

- **SageMaker Multi-Model Endpoint** (1 endpoint hosting 10+ models): consolidates hosting cost across teams. Pays off at 3+ endpoints merging.
- **Batch inference for non-real-time use cases**: 80% cheaper than real-time endpoints if downstream consumers can wait hours.
- **Reserved capacity for endpoints**: 1-year reserved = 40% savings on steady 24/7 endpoints. Only makes sense for stable production workloads.

## What you must NOT skimp on

1. **Multi-AZ for prod endpoints.** Single-AZ saves $175/mo and costs you an outage during an AZ failure.
2. **KMS per data layer.** $1-5/mo each. Blast-radius insurance.
3. **Data capture at 100% in prod.** Reducing to 10% saves $5 but prevents real-time debugging during incidents.
4. **CloudWatch retention of 90 days for model monitor reports.** If a regulator asks "when did drift start?", you need the log.

## Comparison: SageMaker FS vs Databricks FS at this scale

| Cost line | SageMaker FS track | Databricks FS track |
|---|---|---|
| Online store | $75 (DynamoDB) | $110 (Online Tables, serverless) |
| Offline store | $70 (S3 + Glue) | $50 (Delta on S3) |
| Compute for batch ingest | shared Spark/EMR: $40 | Databricks jobs: $80 |
| Monitoring | $45 (Model Monitor) | $35 (Lakehouse Monitoring) |
| **Subtotal** | **$230** | **$275** |

Net: SageMaker FS is ~$45/month cheaper for this baseline. But if your team is already on Databricks, the savings don't justify the platform split. If you're AWS-native and want one more managed service, SageMaker FS is the lower-friction choice.

## Cost monitoring

Deployed automatically via `modules/monitoring`:
- **AWS Budget** at 80%/100% actual + 100% forecasted thresholds
- **Cost anomaly detection** (daily email if spend > 2σ above trend)
- **Tagging** on every resource: `Project`, `Environment`, `CostCenter`

Review via Cost Explorer monthly; filter by `tag:Project = feature-platform`.

## When this setup is overkill

- **< 10 predictions/second**: use a regular Lambda with features encoded inline. No need for a Feature Store.
- **One model, one team**: batch-materialize features to Redis, skip Feast entirely. Feature Store's value is multi-model consistency.
- **Daily predictions, not real-time**: SageMaker Batch Transform at $0.10/hour is 80% cheaper than a 24/7 endpoint.
- **Pure AWS or pure Databricks**: pick one, skip the Feast abstraction layer. The dual-track is valuable if and only if you're using both platforms.
