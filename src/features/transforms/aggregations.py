"""Aggregation transforms for feature engineering.

Standard patterns:
  - rolling_window: count/sum/avg of an event over a time window
  - ratio: ratio of event A count vs event B count
  - recency: time since last event
  - distinct_count: approximate count distinct over a window
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from features.utils.logging_config import get_logger

log = get_logger(__name__, component="transforms.aggregations")


def rolling_count(
    df: DataFrame,
    entity_col: str,
    event_time_col: str,
    window_duration: str = "1 hour",
    slide_duration: str | None = None,
    output_col: str = "rolling_count",
) -> DataFrame:
    """Count events per entity in rolling time windows.

    Produces: entity_col, window_start, window_end, output_col
    """
    window_spec = (
        F.window(event_time_col, window_duration, slide_duration)
        if slide_duration
        else F.window(event_time_col, window_duration)
    )
    result = (
        df.groupBy(entity_col, window_spec.alias("w"))
        .agg(F.count("*").alias(output_col))
        .withColumn("window_start", F.col("w.start"))
        .withColumn("window_end", F.col("w.end"))
        .drop("w")
    )
    return result


def rolling_sum(
    df: DataFrame,
    entity_col: str,
    event_time_col: str,
    value_col: str,
    window_duration: str = "1 hour",
    slide_duration: str | None = None,
    output_col: str | None = None,
) -> DataFrame:
    """Sum a numeric column per entity in rolling time windows."""
    output = output_col or f"rolling_sum_{value_col}"
    window_spec = (
        F.window(event_time_col, window_duration, slide_duration)
        if slide_duration
        else F.window(event_time_col, window_duration)
    )
    return (
        df.groupBy(entity_col, window_spec.alias("w"))
        .agg(F.sum(value_col).alias(output))
        .withColumn("window_start", F.col("w.start"))
        .withColumn("window_end", F.col("w.end"))
        .drop("w")
    )


def rolling_avg(
    df: DataFrame,
    entity_col: str,
    event_time_col: str,
    value_col: str,
    window_duration: str = "1 hour",
    output_col: str | None = None,
) -> DataFrame:
    """Average a numeric column per entity over a rolling window."""
    output = output_col or f"rolling_avg_{value_col}"
    return (
        df.groupBy(entity_col, F.window(event_time_col, window_duration).alias("w"))
        .agg(F.avg(value_col).alias(output))
        .withColumn("window_start", F.col("w.start"))
        .withColumn("window_end", F.col("w.end"))
        .drop("w")
    )


def ratio_feature(
    df: DataFrame,
    entity_col: str,
    event_type_col: str,
    event_time_col: str,
    numerator_type: str,
    denominator_type: str,
    window_duration: str = "7 days",
    output_col: str = "event_ratio",
) -> DataFrame:
    """Ratio of events of two different types per entity.

    Example: purchases / visits over 7 days = conversion rate.
    """
    windowed = df.groupBy(
        entity_col,
        F.window(event_time_col, window_duration).alias("w"),
    ).agg(
        F.sum(F.when(F.col(event_type_col) == numerator_type, 1).otherwise(0)).alias("num_cnt"),
        F.sum(F.when(F.col(event_type_col) == denominator_type, 1).otherwise(0)).alias("denom_cnt"),
    )
    return (
        windowed.withColumn(
            output_col,
            F.when(F.col("denom_cnt") > 0, F.col("num_cnt") / F.col("denom_cnt")).otherwise(0.0),
        )
        .withColumn("window_start", F.col("w.start"))
        .withColumn("window_end", F.col("w.end"))
        .drop("w")
    )


def time_since_last_event(
    df: DataFrame,
    entity_col: str,
    event_time_col: str,
    reference_time_col: str,
    output_col: str = "seconds_since_last_event",
) -> DataFrame:
    """Seconds since the entity's last event.

    Assumes df has current observations with reference_time_col.
    Returns one row per entity with the gap to their prior event.
    """
    w = Window.partitionBy(entity_col).orderBy(event_time_col)
    return (
        df.withColumn("prev_event_ts", F.lag(event_time_col).over(w))
        .withColumn(
            output_col,
            (F.col(reference_time_col).cast("long") - F.col("prev_event_ts").cast("long")),
        )
    )


def distinct_count_rolling(
    df: DataFrame,
    entity_col: str,
    event_time_col: str,
    distinct_col: str,
    window_duration: str = "30 days",
    output_col: str | None = None,
) -> DataFrame:
    """Approximate count distinct per entity over a rolling window.

    Uses HyperLogLog++ for memory efficiency at scale.
    """
    output = output_col or f"distinct_{distinct_col}_count"
    return (
        df.groupBy(entity_col, F.window(event_time_col, window_duration).alias("w"))
        .agg(F.approx_count_distinct(distinct_col).alias(output))
        .withColumn("window_start", F.col("w.start"))
        .withColumn("window_end", F.col("w.end"))
        .drop("w")
    )
