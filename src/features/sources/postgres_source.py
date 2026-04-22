"""Postgres source via JDBC for batch feature engineering from OLTP tables.

For real-time CDC, use the streaming platform's Debezium connector and
consume the resulting Kafka topic via KinesisSource or KafkaSource pattern.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql import DataFrame, SparkSession

from features.utils.logging_config import get_logger
from features.utils.secrets import get_secret

log = get_logger(__name__, component="source.postgres")


@dataclass
class PostgresSourceConfig:
    """Postgres JDBC source config.

    Either provide secret_id (preferred, fetches from Secrets Manager) or
    inline host + user + password.
    """
    secret_id: str | None = None
    host: str = ""
    port: int = 5432
    database: str = ""
    user: str = ""
    password: str = ""

    table: str = ""
    """Either a table name or a (SELECT ...) subquery wrapped in parens."""

    partition_column: str | None = None
    """For parallel reads — pick a numeric/date column with even distribution."""
    num_partitions: int = 8
    lower_bound: int | None = None
    upper_bound: int | None = None


class PostgresSource:
    def __init__(self, spark: SparkSession, config: PostgresSourceConfig):
        self.spark = spark
        self.config = config

    def read(self) -> DataFrame:
        if self.config.secret_id:
            secret = get_secret(self.config.secret_id)
            host = secret["host"]
            port = secret.get("port", 5432)
            database = secret["database"]
            user = secret["username"]
            password = secret["password"]
        else:
            host = self.config.host
            port = self.config.port
            database = self.config.database
            user = self.config.user
            password = self.config.password

        url = f"jdbc:postgresql://{host}:{port}/{database}"
        log.info("postgres_source_read", url=url, table=self.config.table)

        reader = (
            self.spark.read.format("jdbc")
            .option("url", url)
            .option("dbtable", self.config.table)
            .option("user", user)
            .option("password", password)
            .option("driver", "org.postgresql.Driver")
            .option("fetchsize", "10000")
        )

        if self.config.partition_column:
            if self.config.lower_bound is None or self.config.upper_bound is None:
                raise ValueError(
                    "partition_column requires lower_bound + upper_bound"
                )
            reader = (
                reader
                .option("partitionColumn", self.config.partition_column)
                .option("lowerBound", str(self.config.lower_bound))
                .option("upperBound", str(self.config.upper_bound))
                .option("numPartitions", str(self.config.num_partitions))
            )

        return reader.load()
