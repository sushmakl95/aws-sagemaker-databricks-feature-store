# Authoring Features

## The mental model

A feature is: **a named value derived from entity state as of a point in time**, with a known freshness guarantee. Everything in this repo exists to make that definition concrete + enforced.

Good features have five properties:
1. **Name that describes the computation** — `events_last_5min`, not `feat_17`
2. **Stable value type** — once published as Float32, never change to String
3. **Known TTL** — past which the value is treated as missing
4. **Clear ownership** — one team's pager goes off if it breaks
5. **Testable** — you can reproduce the value offline from raw data

## Where features live

| Type | Pipeline | Schedule | Backend | Example |
|---|---|---|---|---|
| Streaming (per-event) | Lambda | triggered | SMFS online + offline | `events_last_5min` |
| Batch (daily) | Spark job | nightly | SMFS offline | `total_spend` |
| Batch (hourly) | Spark job | hourly | SMFS offline | `product_popularity_1h` |
| Embedding | GPU batch | weekly | SMFS offline | `user_embedding_v3` |
| On-demand | Feast ODT | at lookup | n/a | `hour_of_day` |

## Steps to add a new feature

### 1. Define the FeatureView in `src/feast_repo/feature_views/`

```python
# src/feast_repo/feature_views/user_engagement.py
from datetime import timedelta
from feast import FeatureView, Field
from feast.types import Float32, Int32

from feast_repo.data_sources.sources import user_aggregates_batch
from feast_repo.entities.users import user

user_engagement_fv = FeatureView(
    name="user_engagement",
    entities=[user],
    ttl=timedelta(hours=6),
    schema=[
        Field(name="sessions_last_24h", dtype=Int32),
        Field(name="avg_session_duration_sec", dtype=Float32),
    ],
    source=user_aggregates_batch,
    online=True,
    tags={
        "owner": "ml-platform",
        "freshness": "6h",
        "compute_cost": "low",
    },
    description="User engagement aggregates over 24h window",
)
```

### 2. Register the FeatureView

```python
# src/feast_repo/feature_views/__init__.py
from feast_repo.feature_views.user_engagement import user_engagement_fv
```

### 3. Author the compute

For a batch feature, add logic to `src/features/transforms/` using the existing primitives:

```python
from features.transforms import rolling_avg

result = rolling_avg(
    df=sessions_df,
    entity_col="user_id",
    event_time_col="session_start",
    value_col="duration_seconds",
    window_duration="24 hours",
    output_col="avg_session_duration_sec",
)
```

For a streaming feature, extend `src/lambdas/streaming_feature_pipeline.py` (or create a separate Lambda) and add the feature to the corresponding SageMaker Feature Group Terraform definition.

### 4. Create/update the feature group in Terraform

```hcl
# infra/terraform/modules/sagemaker_feature_store/main.tf
resource "aws_sagemaker_feature_group" "user_engagement" {
  feature_group_name             = "${var.name_prefix}-user-engagement"
  record_identifier_feature_name = "entity_id"
  event_time_feature_name        = "event_time"
  role_arn                       = var.offline_role_arn

  feature_definition {
    feature_name = "sessions_last_24h"
    feature_type = "Integral"
  }
  feature_definition {
    feature_name = "avg_session_duration_sec"
    feature_type = "Fractional"
  }

  # ... online_store_config, offline_store_config
}
```

### 5. Test locally

```bash
# Unit test the transform
pytest tests/unit/test_aggregations.py::test_rolling_avg -v

# Integration test: generate synthetic data, run pipeline locally
make compose-up
make seed-sample-data
python -m features.jobs.user_engagement_batch --local
```

### 6. Deploy

```bash
# Infra first
cd infra/terraform
terraform plan -var-file=envs/dev.tfvars
terraform apply -var-file=envs/dev.tfvars

# Feast registry
features feast-sync --repo-path src/feast_repo

# Run a backfill (only for the new feature — existing features unaffected)
features batch-backfill --feature-view user_engagement --date-range 2026-01-01:2026-04-22
```

## Do's and don'ts

**Do** version your feature views by adding a suffix (`_v2`) when breaking changes happen. SageMaker FS has no schema evolution; a new schema means a new feature group.

**Do** add a `tags` block to every FeatureView with `owner`, `freshness`, and (if PII may be computed) `pii: true`. Our CI catches missing tags.

**Do** compute features from immutable inputs (event logs) rather than mutable state (current DB row). Immutable inputs make backfills deterministic.

**Don't** compute features using `now()` inside the pipeline. Use `event_time` or a pinned "as of" timestamp. Otherwise backfills produce different values than live ingest.

**Don't** create a feature view with 100+ features. Split into logical groups (user_recency, user_lifetime, user_preferences). At training time, Feast efficiently joins across them.

**Don't** use features whose definition references models ("probability of churn from model v7"). This creates circular dependencies. If you need a model's output as a feature, materialize it as a separate ML step, write to its own feature view, and register the lineage.

## Testing a feature's online/offline parity

```python
# tests/integration/test_user_engagement_parity.py
from datetime import datetime, timedelta, UTC
import pandas as pd

from feast import FeatureStore

def test_online_offline_parity():
    fs = FeatureStore(repo_path="src/feast_repo")

    # Ingest a single record
    record = pd.DataFrame([{
        "entity_id": "U_test",
        "event_time": datetime.now(UTC),
        "sessions_last_24h": 7,
        "avg_session_duration_sec": 312.5,
    }])
    fs.push("user_engagement_push", record)

    # Wait for propagation (eventual consistency on online store)
    import time; time.sleep(5)

    # Read from online
    online = fs.get_online_features(
        features=["user_engagement:sessions_last_24h"],
        entity_rows=[{"user_id": "U_test"}],
    ).to_dict()
    assert online["sessions_last_24h"][0] == 7

    # Read from offline via point-in-time join
    offline = fs.get_historical_features(
        entity_df=pd.DataFrame([{
            "user_id": "U_test",
            "event_timestamp": datetime.now(UTC) + timedelta(minutes=1),
        }]),
        features=["user_engagement:sessions_last_24h"],
    ).to_df()
    assert offline["sessions_last_24h"][0] == 7
```

## Naming conventions

- Feature view names: `<entity>_<purpose>` (`user_recency`, `product_features`)
- Feature names: `<descriptor>_<aggregation>_<window>` (`orders_count_7d`, `avg_spend_30d`)
- Keep feature names lowercase + snake_case
- Avoid ambiguous abbreviations (`avg_ov_30d` → `avg_order_value_30d`)

## CI gates

Every PR runs `scripts/validate_feature_views.py` which enforces:
- FeatureView name pattern `^[a-z][a-z0-9_]*$`
- Every FV has a non-empty `owner` tag
- TTL is at least 5 minutes (shorter TTLs indicate misconfigured streaming)
- Schema doesn't repeat a name across FVs (prevents lookup ambiguity)
- No removed FV is still referenced by a registered model
