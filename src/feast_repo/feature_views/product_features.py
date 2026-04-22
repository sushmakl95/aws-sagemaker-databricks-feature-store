"""Product features feature view.

Product-level aggregates (popularity, embeddings, pricing).
Updated by batch job; very slow-moving.
"""

from datetime import timedelta

from feast import FeatureView, Field
from feast.types import Array, Float32, Int32

from feast_repo.data_sources.sources import product_features_batch
from feast_repo.entities.products import product

product_features_fv = FeatureView(
    name="product_features",
    entities=[product],
    ttl=timedelta(days=7),
    schema=[
        Field(name="total_purchases_7d", dtype=Int32),
        Field(name="total_purchases_30d", dtype=Int32),
        Field(name="unique_buyers_30d", dtype=Int32),
        Field(name="avg_rating", dtype=Float32),
        Field(name="price_usd", dtype=Float32),
        Field(name="embedding", dtype=Array(Float32)),
    ],
    source=product_features_batch,
    online=True,
    tags={
        "owner": "catalog-team",
        "freshness": "6h",
        "embedding_dim": "64",
    },
    description="Product-level aggregates + 64-dim content embedding",
)
