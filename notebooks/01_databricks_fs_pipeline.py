# Databricks notebook source
# MAGIC %md
# MAGIC # Databricks Feature Store: User Behavior FE Pipeline
# MAGIC
# MAGIC DLT (Delta Live Tables) pipeline that ingests events from Kinesis,
# MAGIC computes user behavioral features, and writes them to the Databricks
# MAGIC Feature Store via Unity Catalog.
# MAGIC
# MAGIC Mirrors the SageMaker track (Lambda -> SageMaker FS) but uses DLT's
# MAGIC built-in expectations + medallion architecture.
# MAGIC
# MAGIC Parameters (set on the DLT pipeline):
# MAGIC - kinesis_stream_name
# MAGIC - catalog_name
# MAGIC - schema_name
# MAGIC - fs_table_user_recency

# COMMAND ----------

import dlt
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

EVENT_SCHEMA = StructType([
    StructField("user_id", StringType()),
    StructField("event_type", StringType()),
    StructField("product_id", StringType()),
    StructField("amount", DoubleType()),
    StructField("event_ts", TimestampType()),
])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Bronze: raw Kinesis events

# COMMAND ----------

@dlt.table(
    name="user_events_bronze",
    comment="Raw decoded Kinesis user events",
    table_properties={"quality": "bronze"},
)
def user_events_bronze():
    return (
        spark.readStream
        .format("kinesis")
        .option("streamName", spark.conf.get("pipelines.kinesis.stream"))
        .option("region", spark.conf.get("pipelines.kinesis.region"))
        .option("initialPosition", "LATEST")
        .load()
        .select(
            F.from_json(F.col("data").cast("string"), EVENT_SCHEMA).alias("event"),
            F.col("approximateArrivalTimestamp").alias("arrival_ts"),
        )
    )


# COMMAND ----------

# MAGIC %md
# MAGIC ## Silver: parsed + DQ enforced

# COMMAND ----------

@dlt.table(
    name="user_events_silver",
    comment="Parsed events with DQ rules",
    table_properties={"quality": "silver"},
)
@dlt.expect_or_drop("event_not_null", "event IS NOT NULL")
@dlt.expect_or_drop("user_id_not_null", "event.user_id IS NOT NULL")
@dlt.expect("valid_event_type",
            "event.event_type IN ('view', 'click', 'purchase', 'cart_add')")
@dlt.expect("amount_positive_for_purchase",
            "event.event_type != 'purchase' OR event.amount > 0")
def user_events_silver():
    return (
        dlt.read_stream("user_events_bronze")
        .select(
            F.col("event.user_id").alias("user_id"),
            F.col("event.event_type").alias("event_type"),
            F.col("event.product_id").alias("product_id"),
            F.col("event.amount").alias("amount"),
            F.col("event.event_ts").alias("event_ts"),
            F.col("arrival_ts"),
        )
    )


# COMMAND ----------

# MAGIC %md
# MAGIC ## Gold: user recency features (aggregated)

# COMMAND ----------

@dlt.table(
    name="user_recency_features",
    comment="User recency features for online serving",
    table_properties={
        "quality": "gold",
        "delta.enableChangeDataFeed": "true",
        "delta.autoOptimize.optimizeWrite": "true",
    },
)
def user_recency_features():
    return (
        dlt.read_stream("user_events_silver")
        .withWatermark("event_ts", "10 minutes")
        .groupBy(
            F.window(F.col("event_ts"), "1 hour", "5 minutes").alias("w"),
            F.col("user_id"),
        )
        .agg(
            F.count("*").alias("events_last_1h"),
            F.count(F.when(F.col("event_ts") > F.current_timestamp() - F.expr("INTERVAL 5 MINUTES"), 1))
                .alias("events_last_5min"),
            F.approx_count_distinct("product_id").alias("distinct_products_last_1h"),
            F.avg(F.when(F.col("event_type") == "purchase", F.col("amount")))
                .alias("avg_order_value_last_1h"),
            F.max("event_ts").alias("last_event_ts"),
        )
        .select(
            F.col("user_id"),
            F.col("w.end").alias("event_time"),
            F.current_timestamp().alias("ingestion_time"),
            F.col("events_last_5min"),
            F.col("events_last_1h"),
            F.col("distinct_products_last_1h"),
            F.coalesce(F.col("avg_order_value_last_1h"), F.lit(0.0))
                .alias("avg_order_value_last_1h"),
            (F.unix_timestamp(F.current_timestamp()) -
                F.unix_timestamp(F.col("last_event_ts")))
                .cast("int")
                .alias("seconds_since_last_event"),
        )
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Publish to Feature Store (run as a separate job after DLT pipeline)
# MAGIC
# MAGIC The DLT table above is already accessible to Databricks ML training via
# MAGIC Unity Catalog. To expose it to Online Tables for low-latency serving,
# MAGIC run the `FeatureEngineeringClient.publish_table()` call from a regular
# MAGIC Databricks Notebook job after DLT commits.
