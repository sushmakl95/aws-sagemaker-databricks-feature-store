"""Kinesis source reader for streaming feature ingest.

Used by Lambda + Spark Structured Streaming to consume application events.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql import DataFrame, SparkSession

from features.utils.logging_config import get_logger

log = get_logger(__name__, component="source.kinesis")


@dataclass
class KinesisSourceConfig:
    """Kinesis source configuration."""
    stream_name: str
    region: str = "us-east-1"
    initial_position: str = "LATEST"
    timestamp_iso: str | None = None
    records_per_second: int = 10_000


class KinesisSource:
    """Spark Structured Streaming source for Kinesis."""

    def __init__(self, spark: SparkSession, config: KinesisSourceConfig):
        self.spark = spark
        self.config = config

    def read_stream(self) -> DataFrame:
        log.info(
            "kinesis_source_start",
            stream=self.config.stream_name,
            region=self.config.region,
        )
        reader = (
            self.spark.readStream
            .format("kinesis")
            .option("streamName", self.config.stream_name)
            .option("region", self.config.region)
            .option("startingPosition", self.config.initial_position)
            .option("kinesis.executor.maxFetchRecordsPerShard",
                    self.config.records_per_second)
        )
        if self.config.initial_position == "AT_TIMESTAMP":
            if not self.config.timestamp_iso:
                raise ValueError("AT_TIMESTAMP requires timestamp_iso")
            reader = reader.option("startingTimestamp", self.config.timestamp_iso)
        return reader.load()
