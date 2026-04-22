# Model Monitoring

## What we monitor

| Dimension | Method | Alert threshold |
|---|---|---|
| **Data drift** | PSI + KS on each feature, hourly | PSI > 0.25 OR KS p < 0.01 |
| **Prediction distribution shift** | PSI on model output scores | PSI > 0.15 |
| **Inference latency** | CloudWatch endpoint metrics | P99 > 200ms for 5 min |
| **Inference error rate** | 4xx/5xx rates | > 1% for 5 min |
| **Feature freshness** | max(ingestion_time) per FV | stale > 2× TTL |
| **Online store hit rate** | BatchGetItem hit count | < 95% for 5 min |

## Data drift: two approaches

### 1. SageMaker Model Monitor

**How it works**:
- At training time, generate `statistics.json` + `constraints.json` from training data (see `scripts/generate_baseline.py`)
- Enable data capture on the endpoint (enabled by default in our Terraform)
- Schedule Monitor job (hourly default)
- Monitor reads last hour of captured data, compares to baseline, writes `constraint_violations.json`
- EventBridge rule fires on "CompletedWithViolations"
- Lambda `drift_alerter` parses the report + sends SNS + Slack alert

**Advantages**:
- Managed — no compute to run
- Declarative constraint language
- Integrates with SageMaker Model Registry

**Disadvantages**:
- Constraint-focused: tells you "feature X violated rule Y", not "the distribution shifted by δ"
- No explicit PSI/KS — have to infer drift magnitude from violation count
- Limited to AWS (not portable to on-prem)

### 2. Custom drift detector (PSI + KS)

**How it works**:
- Export baseline as parquet at training time
- Nightly job reads last 24h of data capture (or last 24h of offline feature values), computes PSI + KS against baseline
- Write per-feature drift scores to Delta table `main.monitoring.drift_reports`
- Databricks SQL dashboard visualizes trends
- Alert via cron job if PSI > threshold

**Advantages**:
- Portable across SageMaker + Databricks
- Numeric drift score — easy to trend, easy to set thresholds
- Simpler to reason about in post-incident reviews

**Disadvantages**:
- More code to maintain
- Have to run compute ourselves

**Recommendation**: run both. Monitor catches "constraint breach, page the team" (high-severity, clear action). Custom catches "gradual drift, investigate this week" (medium-severity, trending concern).

## Drift metrics explained

### Population Stability Index (PSI)

Bucket the baseline values into deciles. Bucket the current values into the same deciles. Compare proportions:

```
PSI = Σ (current_frac_i - baseline_frac_i) × log(current_frac_i / baseline_frac_i)
```

Rule of thumb:
- PSI < 0.1: no significant drift
- 0.1 ≤ PSI < 0.25: moderate drift, investigate
- PSI ≥ 0.25: major drift, retrain

PSI is symmetric and bounded. It's easy to trend over time. It's not a statistical test (no p-value), so the thresholds are conventions, not proofs.

### Kolmogorov-Smirnov (KS) test

For two empirical CDFs, the KS statistic is the max absolute difference between them. The two-sample KS test gives a p-value: how likely are these two samples from the same distribution?

Rule of thumb:
- p > 0.05: no evidence of drift
- 0.01 < p ≤ 0.05: weak evidence, monitor
- p ≤ 0.01: strong evidence, investigate

KS is more formal than PSI but loses information when the shift is only in the tails. Real deployments use both.

## Setting up Model Monitor

### 1. Generate baseline at training time

```python
from features.monitoring import BaselineConfig, generate_baseline

# After training, on the training DataFrame
generate_baseline(BaselineConfig(
    input_path="s3://.../training_set.parquet",
    output_dir="s3://.../baselines/churn_v3/",
))
```

### 2. Terraform provisions the monitor schedule

The `sagemaker_model_monitor` module creates:
- A `data_quality_job_definition` (one-time job spec)
- A `monitoring_schedule` (hourly cron)

### 3. Model Monitor runs automatically every hour

Output lands at:
```
s3://<monitor-reports-bucket>/reports/<endpoint-name>/<timestamp>/
├── statistics.json               # current distribution
└── constraint_violations.json    # violations vs baseline constraints
```

### 4. Alerting

EventBridge rule in the `lambda` module:
```json
{
  "source": ["aws.sagemaker"],
  "detail-type": ["SageMaker Model Monitoring Job Status Change"],
  "detail": {
    "MonitoringExecutionStatus": ["Completed", "CompletedWithViolations"]
  }
}
```

→ `drift_alerter` Lambda → SNS email + Slack webhook.

## Prediction distribution monitoring

Beyond input features, monitor the output distribution:

```python
from features.monitoring import detect_drift

# Last 7 days of inference scores
recent_scores = spark.read.table("main.monitoring.inference_logs") \
    .where("request_ts > current_timestamp() - INTERVAL 7 DAYS") \
    .select("prediction_score").toPandas()

# Baseline from the test split at training time
baseline_scores = pd.read_parquet("s3://.../test_predictions_baseline.parquet")

report = detect_drift(
    baseline_df=baseline_scores,
    current_df=recent_scores,
    feature_columns=["prediction_score"],
    psi_threshold=0.15,  # tighter threshold on model outputs
)
```

If output distribution drifted but input features didn't: you may have a latent covariate shift (an unobserved feature changed). Investigate with SHAP + partial-dependence plots.

## Triage playbook

**Alert: PSI > 0.25 on `total_spend` for churn_predictor endpoint**

1. **Acknowledge** in Slack. Track in incident channel.
2. **Scope**: Is this one feature? Multiple? Check the dashboard.
3. **Volume check**: Is inference volume normal? (Sudden drop = upstream issue, not drift.)
4. **Timing**: When did drift start? Correlate with deploys, marketing campaigns, holidays.
5. **Check feature freshness**: Is the batch pipeline producing `total_spend` on schedule? Stale features look like drift.
6. **If freshness is fine**: real drift. Options:
   - **Retrain**: if drift is expected (seasonal, new product launch), retrain on fresh data
   - **Debug**: if drift is unexpected (possible fraud pattern, data pipeline bug), trace upstream to the OLTP source
   - **Temporarily revert**: roll back to prior model if accuracy-critical and retrain is days away
7. **Post-incident**: if manual retrain was required, check automatic retrain cadence. Most drift-triggered retrains indicate retrain schedule is too slow.

## Monitoring the monitor

Meta-alerts on monitoring-system health:
- **Monitor job hasn't run in 2 hours**: EventBridge isn't firing or Lambda is broken
- **Baseline hasn't updated in 30 days**: training pipeline may have failed silently
- **Drift reports table hasn't grown in 24h**: custom detector is broken
- **SNS alerts topic has 0 deliveries in 7 days**: no drift (plausible) OR alerting path is broken (verify by sending a test alert monthly)

## What we don't monitor (yet)

- **Fairness / bias metrics**: SageMaker Clarify supports this; we'd add a `ModelBiasJobDefinition` for production rollout. Not in the default template to keep costs down.
- **Feature importance drift**: SHAP-value distributions can shift even when input distributions don't. Third-party tools (WhyLabs, Fiddler) do this; not in scope for this repo.
- **Concept drift (P(y|x))**: requires labels to land back in the system. We track this manually per model via A/B test holdouts.
