"""Embedding feature helpers.

For text/categorical embeddings, we typically:
  1. Train the embedding model separately (out of scope here)
  2. Score entities in a periodic batch job (e.g., nightly)
  3. Store the resulting vector as a FLOAT_LIST feature
  4. Downstream models use the vector as inputs

This module provides helpers for the batch scoring phase.
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType, FloatType

from features.utils.logging_config import get_logger

log = get_logger(__name__, component="transforms.embeddings")


def normalize_embedding(
    df: DataFrame,
    embedding_col: str,
    output_col: str | None = None,
) -> DataFrame:
    """L2-normalize an embedding column in place.

    Required when using cosine similarity at inference -- pre-normalizing
    means cosine = dot product.
    """
    output = output_col or embedding_col

    def _l2_normalize(vec: list[float]) -> list[float]:
        if not vec:
            return vec
        norm = sum(x * x for x in vec) ** 0.5
        if norm == 0:
            return vec
        return [x / norm for x in vec]

    normalize_udf = F.udf(_l2_normalize, ArrayType(FloatType()))
    return df.withColumn(output, normalize_udf(F.col(embedding_col)))


def embedding_dot_product(
    df: DataFrame,
    embedding_col_a: str,
    embedding_col_b: str,
    output_col: str = "dot_product",
) -> DataFrame:
    """Compute dot product of two embedding columns (assumed same dim).

    If both embeddings are L2-normalized, this equals cosine similarity.
    """

    def _dot(a: list[float], b: list[float]) -> float:
        if a is None or b is None or len(a) != len(b):
            return 0.0
        return sum(x * y for x, y in zip(a, b, strict=False))

    dot_udf = F.udf(_dot, FloatType())
    return df.withColumn(output_col, dot_udf(F.col(embedding_col_a), F.col(embedding_col_b)))


def validate_embedding_dim(
    df: DataFrame,
    embedding_col: str,
    expected_dim: int,
) -> DataFrame:
    """Filter out rows where the embedding doesn't match expected dimension.

    Returns the filtered DataFrame. Logs count of dropped rows.
    """
    before_count = df.count()
    filtered = df.filter(F.size(F.col(embedding_col)) == expected_dim)
    after_count = filtered.count()
    dropped = before_count - after_count
    if dropped > 0:
        log.warning(
            "embedding_dim_mismatch_dropped",
            column=embedding_col,
            expected_dim=expected_dim,
            dropped=dropped,
        )
    return filtered
