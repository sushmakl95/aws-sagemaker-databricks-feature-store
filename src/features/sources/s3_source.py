"""S3 source reader for batch feature engineering.

Reads Parquet/Delta/CSV from S3 with schema enforcement + partition pruning.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.types import StructType

from features.utils.logging_config import get_logger

log = get_logger(__name__, component="source.s3")


@dataclass
class S3SourceConfig:
    """S3 source configuration."""
    s3_path: str
    """e.g., s3://bucket/path/ for Delta or partitioned Parquet."""
    format: str = "delta"
    """delta, parquet, csv, json."""
    partition_filter: str | None = None
    """SQL filter on partition columns, e.g. 'event_date >= "2026-01-01"'."""
    schema: StructType | None = None
    """Optional schema enforcement for non-Delta formats."""


class S3Source:
    """Batch S3 source for feature engineering."""

    def __init__(self, spark: SparkSession, config: S3SourceConfig):
        self.spark = spark
        self.config = config

    def read(self) -> DataFrame:
        log.info(
            "s3_source_read",
            path=self.config.s3_path,
            format=self.config.format,
        )
        reader = self.spark.read.format(self.config.format)
        if self.config.schema:
            reader = reader.schema(self.config.schema)
        df = reader.load(self.config.s3_path)
        if self.config.partition_filter:
            df = df.where(self.config.partition_filter)
        return df
