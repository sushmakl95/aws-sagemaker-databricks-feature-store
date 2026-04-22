"""User recency feature view.

Low-latency streaming features about user's recent behavior (last 5 min - 1 hour).
Updated via Lambda push API + backfilled from batch source.
"""

from datetime import timedelta

from feast import FeatureView, Field
from feast.types import Float32, Int32

from feast_repo.data_sources.sources import user_recency_push
from feast_repo.entities.users import user

user_recency_fv = FeatureView(
    name="user_recency",
    entities=[user],
    ttl=timedelta(hours=1),
    schema=[
        Field(name="events_last_5min", dtype=Int32),
        Field(name="events_last_1h", dtype=Int32),
        Field(name="distinct_products_last_1h", dtype=Int32),
        Field(name="avg_order_value_last_1h", dtype=Float32),
        Field(name="seconds_since_last_event", dtype=Int32),
    ],
    source=user_recency_push,
    online=True,
    tags={
        "owner": "ml-platform",
        "freshness": "1h",
        "compute_cost": "low",
        "sla": "p99_lookup_10ms",
    },
    description="Recent user behavior (last 5min-1h rolling windows)",
)
