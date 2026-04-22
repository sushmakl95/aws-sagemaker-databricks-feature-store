"""Databricks Feature Store sink.

Wraps `FeatureEngineeringClient.write_table()` (Unity Catalog) or
`FeatureStoreClient.write_table()` (legacy workspace FS).

This module is only runnable on Databricks (imports the `databricks.feature_engineering`
client at call time to avoid hard dependency when running elsewhere).

For non-Databricks environments, use `SageMakerFSSink` instead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pyspark.sql import DataFrame

from features.utils.logging_config import get_logger

log = get_logger(__name__, component="sink.databricks_fs")


@dataclass
class DatabricksFSSinkConfig:
    table_name: str
    """Unity Catalog table: catalog.schema.table."""
    mode: str = "merge"
    """One of: merge (upsert), overwrite, append. merge is the safe default."""
    checkpoint_location: str | None = None
    """Required for streaming writes."""
    trigger_interval_seconds: int = 30
    emit_metrics: bool = True


class DatabricksFSSink:
    """Feature table writer using Databricks Feature Engineering client."""

    def __init__(self, config: DatabricksFSSinkConfig):
        self.config = config
        self._client = None

    @property
    def client(self):
        """Lazy-initialize to avoid import when not on Databricks."""
        if self._client is None:
            try:
                from databricks.feature_engineering import FeatureEngineeringClient
            except ImportError as exc:
                raise RuntimeError(
                    "databricks.feature_engineering not available -- "
                    "run on a Databricks cluster with ML Runtime 14+"
                ) from exc
            self._client = FeatureEngineeringClient()
        return self._client

    def write_batch(self, df: DataFrame) -> dict[str, int]:
        """Write a batch DataFrame to the feature table."""
        start = time.time()
        count = df.count()

        self.client.write_table(
            name=self.config.table_name,
            df=df,
            mode=self.config.mode,
        )

        duration_ms = int((time.time() - start) * 1000)
        log.info(
            "databricks_fs_batch_done",
            table=self.config.table_name,
            records=count,
            duration_ms=duration_ms,
        )
        return {"records_ingested": count, "duration_ms": duration_ms}

    def write_stream(self, streaming_df: DataFrame):
        """Write a streaming DataFrame. Uses foreachBatch under the hood."""
        if not self.config.checkpoint_location:
            raise ValueError("checkpoint_location required for streaming writes")

        def _batch_fn(batch_df: DataFrame, batch_id: int) -> None:
            log.info(
                "databricks_fs_stream_batch",
                table=self.config.table_name,
                batch_id=batch_id,
            )
            self.client.write_table(
                name=self.config.table_name,
                df=batch_df,
                mode=self.config.mode,
            )

        return (
            streaming_df.writeStream
            .foreachBatch(_batch_fn)
            .option("checkpointLocation", self.config.checkpoint_location)
            .trigger(processingTime=f"{self.config.trigger_interval_seconds} seconds")
        )
