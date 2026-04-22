# Online/Offline Parity

## The invariant

For every `(entity_id, event_time)` tuple that has been ingested, the online store and offline store **must return the same feature values**.

Violating this invariant causes training/serving skew: your model was trained on offline values but sees different online values at inference. This is the #1 silent-correctness bug in ML systems — models appear healthy by latency/throughput metrics, but produce subtly wrong predictions.

## How parity can break

**1. Dual-write failures.** The Lambda writes to online store, then to offline store. If the offline write fails but the online succeeded, online has data that offline doesn't. If you retry and both succeed, but the retry has a different timestamp, offline has *two* records while online has the latest — mismatching if your reader does AS-OF lookups.

**2. Schema drift.** Someone adds a feature to the online store but forgets to update the offline schema. Training sees `NULL`, serving sees actual values — model learns to ignore the feature, then at inference it's non-null and out of distribution.

**3. Transformation logic divergence.** Training computes `avg_order_value` from raw events using a Spark UDF. Serving computes it from a precomputed feature view that used a slightly different aggregation (e.g., `AVG(amount)` vs `SUM(amount) / COUNT(*)`). If one uses null-exclusion semantics and the other includes nulls as 0, values differ.

**4. Time zone confusion.** Training data has `event_time` in UTC; serving pipeline parses client timestamps in local time. At inference, the "1 hour ago" feature reads from yesterday if the client is in Tokyo.

**5. Data type coercion.** Training: `total_spend` is float64. Online store: DynamoDB stores it as string. Python implicit str→float conversion handles "3.14" but not "3.14000000000001" (which you'd see from accumulated floats). One record fails quietly, feature comes back null, skew.

## How we enforce parity

### 1. Single source of transformation logic

Features are defined in one place (`src/features/transforms/`) and called by both streaming + batch pipelines. No re-implementation per pipeline.

### 2. Schema enforcement at the Feature Group level

SageMaker Feature Groups have a fixed schema. Writing a record with an extra column fails. This catches "forgot to update offline" at ingest time, not at training time.

### 3. Identical writes via a single sink abstraction

`SageMakerFSSink.write_batch()` writes to the Feature Group via `PutRecord`, which automatically updates both online (DynamoDB) + offline (S3). Atomic-per-record within the single API call. If we also run `DatabricksFSSink.write_batch()` in the dual-track, we use the same `FeatureRecord` object, so the values are identical by construction.

### 4. Parity tests in CI

```python
# tests/integration/test_parity.py
def test_online_offline_same_values():
    record = make_test_record(entity_id="U_parity_test")
    sink.write_batch([record])
    time.sleep(10)  # propagation

    online = fs.get_online_features(
        features=[f"{FV}:{FEAT}"],
        entity_rows=[{"user_id": "U_parity_test"}],
    ).to_dict()

    offline = fs.get_historical_features(
        entity_df=pd.DataFrame([{
            "user_id": "U_parity_test",
            "event_timestamp": record.event_time + timedelta(seconds=1),
        }]),
        features=[f"{FV}:{FEAT}"],
    ).to_df()

    assert online[FEAT][0] == offline[FEAT].iloc[0]
```

Run nightly against a staging environment.

### 5. Timezone discipline

Every timestamp in every feature is stored as UTC with explicit timezone info. The `FeatureRecord.event_time` dataclass field is typed `datetime`, and we validate `tzinfo is not None` at construction.

### 6. Type discipline

`FeatureValueType` enum is the single source of truth. Terraform feature definitions, Feast schema, and `FeatureRecord.features` dict must all agree. Type mismatches are caught at `features feast-sync` (CI) before deploy.

## Parity-breaking changes that require care

**Adding a feature**:
- Add to offline first, backfill historical values
- Wait until backfill is complete before enabling online write
- Only then consume the feature in a model

**Removing a feature**:
- Stop reading the feature from models (retrain without it)
- Wait until no live model uses it
- Then disable online + offline writes
- Keep historical data in offline store for auditability

**Renaming a feature**:
- Treat as "add new + remove old"
- Never rename in-place; SageMaker FS refuses anyway

**Changing a feature's data type**:
- Not possible in-place. Create a new feature (different name) and migrate models.

## When parity is intentionally approximate

**Eventual consistency on online store**: PutRecord acknowledges when the online store is updated. Offline updates are async (up to 15 minutes). This is fine for streaming features (offline is for training, not serving) but is visible in the parity test above (hence the `time.sleep(10)`).

**Batch refresh of online from offline**: If you use SageMaker's `ingest_offline_to_online` or Databricks `publish_table()`, there's a window where offline has newer data than online. Typically bounded at ~30 minutes for hourly refresh. This is a documented gap — alerting runs on both to catch if the gap grows.

## Debugging a parity incident

1. **Confirm scope**: is this one feature? one user? one time window?
2. **Check the data capture**: pull the last 10 inference requests + responses for the affected entity. Compare online feature values to what training data would have at the same `event_time`.
3. **Check ingest logs**: the streaming Lambda logs every batch with success/failure counts. DLQ for persistent failures.
4. **Check the offline store directly**: `SELECT * FROM glue_catalog.streaming.user_recency WHERE entity_id = ? ORDER BY event_time DESC LIMIT 10`. Compare to DynamoDB `GetItem` result.
5. **If values differ**: almost always a Lambda failure mid-write. Look for SNS alerts from the `RecordsFailed` CloudWatch metric.
6. **If values match but training/serving still differ**: likely a transformation divergence. Check model's inference container's Feast lookup config matches the training config.

## What we don't do (yet)

- **Streaming offline → online consistency enforcement**: SageMaker FS's native dual-write has up to 15 min offline lag. We don't bridge that.
- **Cross-store (SageMaker ↔ Databricks) parity monitoring**: when dual-track is enabled, we don't automatically compare values between SMFS and DBFS. Teams that run both should add a nightly parity test. Open issue: implement as a CloudWatch Synthetics probe.
