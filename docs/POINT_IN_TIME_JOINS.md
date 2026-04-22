# Point-in-Time Joins

## The problem

You have a label DataFrame: `(user_id, event_time, churned)`. You want to train a model that predicts `churned` from user features. You join feature tables to the labels and train.

If you join naively, you leak future information. Example:

- Label row: `user_id=U1, event_time=2026-03-15, churned=1`
- Feature table has `total_orders` at multiple timestamps:
  - 2026-03-10: total_orders = 8
  - 2026-03-15: total_orders = 10 (the event day — includes the behavior we're trying to predict)
  - 2026-03-20: total_orders = 12

A naive `JOIN ON user_id` picks the latest value (12 — after the event), or worse, the current value (12 at train time). Either way, you're training on data that wasn't available at the moment the label was determined. The model learns a pattern it can't use at inference time.

## Point-in-time (PIT) correctness

The correct join pattern: for each label row, find the **most recent feature value where `feature_event_time <= label_event_time AND feature_event_time > label_event_time - feature_ttl`**.

For the example above:
- Label row: `user_id=U1, event_time=2026-03-15`
- Matching feature row: `total_orders=8` (the 2026-03-10 record, which is the most recent before event_time)

This is what Feast's `get_historical_features()` does. The Databricks Feature Store `create_training_set()` does the same.

## How the code does it

### Feast path (SageMaker track)

```python
from feast import FeatureStore
import pandas as pd

fs = FeatureStore(repo_path="src/feast_repo")

# Label DataFrame
labels = pd.DataFrame([
    {"user_id": "U1", "event_timestamp": "2026-03-15 10:00:00", "churned": 1},
    {"user_id": "U2", "event_timestamp": "2026-03-16 11:30:00", "churned": 0},
])

training_df = fs.get_historical_features(
    entity_df=labels,
    features=[
        "user_recency:events_last_1h",
        "user_lifetime:total_orders",
        "user_lifetime:total_spend",
    ],
).to_df()
```

Feast generates a SQL query (for Redshift/BigQuery/Athena) that looks like:

```sql
WITH labels AS (
  SELECT user_id, event_timestamp, churned FROM temp_labels
),
features AS (
  SELECT user_id, event_time AS feature_ts, events_last_1h
  FROM user_recency
)
SELECT l.*, f.events_last_1h
FROM labels l
LEFT JOIN LATERAL (
  SELECT *
  FROM features f
  WHERE f.user_id = l.user_id
    AND f.feature_ts <= l.event_timestamp
    AND f.feature_ts > l.event_timestamp - INTERVAL '1 hour'  -- the TTL
  ORDER BY f.feature_ts DESC
  LIMIT 1
) f ON TRUE
```

The `LATERAL` + `ORDER BY DESC LIMIT 1` pattern gives the most recent feature row ≤ the label's event_time, respecting TTL.

### Databricks path

```python
from databricks.feature_engineering import FeatureEngineeringClient, FeatureLookup

fe = FeatureEngineeringClient()

feature_lookups = [
    FeatureLookup(
        table_name="main.feature_store.user_lifetime",
        lookup_key="user_id",
        feature_names=["total_orders", "total_spend"],
        timestamp_lookup_key="event_time",
    ),
]

training_set = fe.create_training_set(
    df=labels_df,
    feature_lookups=feature_lookups,
    label="churned",
)
```

Databricks uses ASOF JOIN natively, which does the same thing.

## Handling late-arriving features

A feature is "late-arriving" if `feature.event_time < label.event_time` but the feature wasn't visible in the feature store until after the label was generated (e.g., batch job runs nightly, so all of day N's features land at 2am of day N+1).

**PIT joins with TTL correctly drop late-arriving features from training** — if the label is at 10am on day N and the feature's event_time is 3pm on day N (but batch-ingested at 2am day N+1), the feature doesn't satisfy `feature_ts <= 10am`.

This is correct behavior! At inference time, you wouldn't have that feature value either. The training distribution matches production.

If dropping late features leaves too many labels with NaN features:
- **Option A**: Backfill with faster cadence (hourly instead of daily)
- **Option B**: Shift label event_time forward (e.g., "churn at day N+1" instead of "churn at day N")
- **Option C**: Use streaming feature ingest for that feature view

## Handling deletes

If a feature value gets deleted (e.g., GDPR "right to be forgotten"):
- SageMaker FS: delete via `sagemaker.delete_record()`. The offline store is append-only, so the deleted record remains as a historical artifact. Use a "tombstone" row with null values to hide the feature.
- Databricks FS: Delta supports actual row deletes via `DELETE FROM`. Deletions are visible immediately to new training runs but not to already-created training sets.

## Debugging PIT joins

**Symptom**: model has near-perfect test AUC, terrible production AUC.
**Likely cause**: leak via naive join. Verify your training set was built with a PIT-aware function (`get_historical_features` or `create_training_set`), not a raw Spark join.

**Symptom**: model trains but 90% of labels get NaN features.
**Likely cause**: TTL is too short relative to feature freshness. Either extend TTL or increase feature ingest frequency.

**Symptom**: training set size decreases after adding a new feature.
**Likely cause**: inner join on the new FV drops labels where no matching feature exists in the TTL window. This is correct — verify the FV is backfilled for the training period. Use `LEFT JOIN` equivalent (Feast does this by default; Databricks defaults to inner, use `exclude_columns` pattern instead).

## TTL selection guide

| Feature type | Typical TTL | Rationale |
|---|---|---|
| Streaming recency | 1-6 hours | Value changes by the minute; stale after an hour |
| Daily aggregates | 1-7 days | Batch runs nightly; 1 day means a broken job loses features |
| Weekly aggregates | 30 days | Rarely changes; larger TTL buffers pipeline issues |
| Embeddings | 30-90 days | Stable over retraining cycles |
| Static categorical | 365 days | Essentially constant |

Rule of thumb: TTL should be 2-3× the feature's expected refresh cadence. If it updates hourly, TTL = 3-6 hours.

## Further reading

- Feast docs: https://docs.feast.dev/concepts/point-in-time-joins
- Uber's Michelangelo paper: point-in-time joins at scale
- Databricks ASOF JOIN: https://docs.databricks.com/en/sql/language-manual/sql-ref-syntax-qry-select-join.html#asof-join
