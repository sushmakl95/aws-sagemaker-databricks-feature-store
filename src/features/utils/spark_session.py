"""Spark session factory tuned for feature engineering workloads."""

from __future__ import annotations

import os

from pyspark.sql import SparkSession


def get_spark_session(
    app_name: str = "feature-platform",
    master: str = "local[*]",
    extra_configs: dict | None = None,
) -> SparkSession:
    """Build a Spark session for batch feature engineering.

    Tuned for:
      - Delta Lake write performance (Delta extensions, optimized writes)
      - Wide aggregations (kryo serializer)
      - S3 + Glue catalog interop (when run on EMR/Databricks)
    """
    cores = os.cpu_count() or 4
    configs = {
        "spark.driver.memory": "4g",
        "spark.driver.bindAddress": "127.0.0.1",
        "spark.driver.host": "127.0.0.1",
        "spark.ui.enabled": "false",
        "spark.sql.shuffle.partitions": str(min(cores * 2, 32)),
        "spark.sql.adaptive.enabled": "true",
        "spark.sql.adaptive.skewJoin.enabled": "true",
        "spark.serializer": "org.apache.spark.serializer.KryoSerializer",
        "spark.jars.packages": "io.delta:delta-spark_2.12:3.2.0",
        "spark.sql.extensions": "io.delta.sql.DeltaSparkSessionExtension",
        "spark.sql.catalog.spark_catalog": (
            "org.apache.spark.sql.delta.catalog.DeltaCatalog"
        ),
        "spark.databricks.delta.optimizeWrite.enabled": "true",
        "spark.databricks.delta.autoCompact.enabled": "true",
    }
    if extra_configs:
        configs.update(extra_configs)

    builder = SparkSession.builder.appName(app_name).master(master)
    for k, v in configs.items():
        builder = builder.config(k, str(v))

    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
