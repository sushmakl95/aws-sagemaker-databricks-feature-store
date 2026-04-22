"""User lifetime feature view.

Slow-moving features updated by nightly batch job. TTL is longer since
lifetime features don't change per-minute.
"""

from datetime import timedelta

from feast import FeatureView, Field
from feast.types import Float32, Int32

from feast_repo.data_sources.sources import user_lifetime_batch
from feast_repo.entities.users import user

user_lifetime_fv = FeatureView(
    name="user_lifetime",
    entities=[user],
    ttl=timedelta(days=30),
    schema=[
        Field(name="account_age_days", dtype=Int32),
        Field(name="total_orders", dtype=Int32),
        Field(name="total_spend", dtype=Float32),
        Field(name="avg_order_value", dtype=Float32),
        Field(name="distinct_products_purchased", dtype=Int32),
        Field(name="churn_risk_score", dtype=Float32),
    ],
    source=user_lifetime_batch,
    online=True,
    tags={
        "owner": "data-platform",
        "freshness": "24h",
        "compute_cost": "medium",
        "pii": "false",
    },
    description="Lifetime user aggregates (updated nightly)",
)
