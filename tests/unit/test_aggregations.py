"""Unit tests for aggregation transforms."""

from __future__ import annotations

import pytest
from pyspark.sql import functions as F

from features.transforms.aggregations import (
    rolling_avg,
    rolling_count,
    rolling_sum,
)

pytestmark = pytest.mark.unit


def _events_df(spark):
    rows = [
        ("U1", "2026-04-22 10:00:00", 1.0),
        ("U1", "2026-04-22 10:05:00", 2.0),
        ("U1", "2026-04-22 10:30:00", 3.0),
        ("U2", "2026-04-22 10:00:00", 5.0),
    ]
    return (
        spark.createDataFrame(rows, ["user_id", "ts_str", "amount"])
        .withColumn("event_time", F.to_timestamp("ts_str"))
        .drop("ts_str")
    )


def test_rolling_count_one_hour_window(spark):
    df = _events_df(spark)
    result = rolling_count(
        df=df,
        entity_col="user_id",
        event_time_col="event_time",
        window_duration="1 hour",
        output_col="count_1h",
    ).collect()

    result_by_user = {}
    for r in result:
        user = r["user_id"]
        result_by_user.setdefault(user, []).append(r["count_1h"])

    assert "U1" in result_by_user
    assert "U2" in result_by_user
    assert sum(result_by_user["U1"]) == 3  # 3 events total for U1
    assert sum(result_by_user["U2"]) == 1


def test_rolling_sum_aggregates_amounts(spark):
    df = _events_df(spark)
    result = rolling_sum(
        df=df,
        entity_col="user_id",
        event_time_col="event_time",
        value_col="amount",
        window_duration="1 hour",
        output_col="sum_amount_1h",
    ).collect()

    total_by_user = {}
    for r in result:
        user = r["user_id"]
        total_by_user[user] = total_by_user.get(user, 0) + r["sum_amount_1h"]

    assert total_by_user["U1"] == 6.0
    assert total_by_user["U2"] == 5.0


def test_rolling_avg_computes_mean(spark):
    df = _events_df(spark)
    result = rolling_avg(
        df=df,
        entity_col="user_id",
        event_time_col="event_time",
        value_col="amount",
        window_duration="1 hour",
        output_col="avg_amount_1h",
    )
    assert "avg_amount_1h" in result.columns
    assert "window_start" in result.columns
    assert "window_end" in result.columns
