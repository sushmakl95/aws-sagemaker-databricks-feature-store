"""Data source definitions for Feast."""

from feast import FileSource, PushSource
from feast.data_source import RequestSource
from feast.types import Float32, Int32, String

# --------------------------------------------------------------------------
# Batch sources -- point at the SageMaker FS offline store (S3 + Glue)
# --------------------------------------------------------------------------
user_aggregates_batch = FileSource(
    name="user_aggregates_batch",
    path="s3://${ICEBERG_WAREHOUSE}/feature_store/user_aggregates/",
    timestamp_field="event_time",
    created_timestamp_column="ingestion_time",
    description="Daily user behavioral aggregates",
)

user_lifetime_batch = FileSource(
    name="user_lifetime_batch",
    path="s3://${ICEBERG_WAREHOUSE}/feature_store/user_lifetime/",
    timestamp_field="event_time",
    created_timestamp_column="ingestion_time",
    description="User-level lifetime features (seniority, total_spend)",
)

product_features_batch = FileSource(
    name="product_features_batch",
    path="s3://${ICEBERG_WAREHOUSE}/feature_store/product_features/",
    timestamp_field="event_time",
    created_timestamp_column="ingestion_time",
    description="Product aggregates (popularity, avg_rating)",
)

# --------------------------------------------------------------------------
# Push source for streaming features (Lambda -> Feast push API)
# --------------------------------------------------------------------------
user_recency_push = PushSource(
    name="user_recency_push",
    batch_source=user_aggregates_batch,
    description="Low-latency streaming updates to user_recency features",
)

# --------------------------------------------------------------------------
# Request source for features computed from the inference request itself
# (e.g., time-of-day, device-type from the incoming payload)
# --------------------------------------------------------------------------
inference_request = RequestSource(
    name="inference_request",
    schema=[
        ("device_type", String),
        ("hour_of_day", Int32),
        ("client_latency_ms", Float32),
    ],
    description="Features derived from the current inference request",
)
