"""Unit tests for core feature types."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from features.core.types import (
    Feature,
    FeatureRecord,
    FeatureValueType,
    FeatureView,
    StoreType,
)

pytestmark = pytest.mark.unit


def test_feature_value_type_enum_values_match_sm_and_feast():
    assert FeatureValueType.STRING.value == "string"
    assert FeatureValueType.INT64.value == "int64"
    assert FeatureValueType.FLOAT_LIST.value == "float_list"


def test_store_type_both_means_dual_write():
    assert StoreType.BOTH.value == "both"


def test_feature_view_post_init_rejects_offline_only_plus_online():
    with pytest.raises(ValueError, match="offline_only is incompatible"):
        FeatureView(
            name="bad_fv",
            entities=["user"],
            features=[Feature(name="x", value_type=FeatureValueType.INT64)],
            ttl_seconds=3600,
            online=True,
            offline_only=True,
        )


def test_feature_view_allows_online_and_not_offline_only():
    fv = FeatureView(
        name="good_fv",
        entities=["user"],
        features=[Feature(name="x", value_type=FeatureValueType.INT64)],
        ttl_seconds=3600,
        online=True,
    )
    assert fv.online
    assert not fv.offline_only


def test_feature_record_to_sagemaker_record_format():
    now = datetime(2026, 4, 22, 10, 0, 0, tzinfo=UTC)
    record = FeatureRecord(
        feature_view="user_recency",
        entity_id="U123",
        event_time=now,
        features={
            "events_last_5min": 3,
            "avg_order_value_last_1h": 42.5,
            "seconds_since_last_event": 120,
        },
    )
    sm = record.to_sagemaker_record()

    # First two entries are always entity_id and event_time
    assert sm[0] == {"FeatureName": "entity_id", "ValueAsString": "U123"}
    assert sm[1]["FeatureName"] == "event_time"
    assert "2026-04-22T10:00:00" in sm[1]["ValueAsString"]

    # Features follow
    feature_dict = {s["FeatureName"]: s["ValueAsString"] for s in sm[2:]}
    assert feature_dict["events_last_5min"] == "3"
    assert feature_dict["avg_order_value_last_1h"] == "42.5"
    assert feature_dict["seconds_since_last_event"] == "120"


def test_feature_record_to_sagemaker_handles_none():
    now = datetime(2026, 4, 22, 10, 0, 0, tzinfo=UTC)
    record = FeatureRecord(
        feature_view="fv",
        entity_id="U1",
        event_time=now,
        features={"maybe_null": None, "real_value": 7},
    )
    sm = record.to_sagemaker_record()
    feature_dict = {s["FeatureName"]: s["ValueAsString"] for s in sm[2:]}
    assert feature_dict["maybe_null"] == ""
    assert feature_dict["real_value"] == "7"


def test_feature_record_to_dict_has_entity_and_features():
    now = datetime(2026, 4, 22, 10, 0, 0, tzinfo=UTC)
    record = FeatureRecord(
        feature_view="fv",
        entity_id="U1",
        event_time=now,
        features={"f1": 1, "f2": "hello"},
    )
    d = record.to_dict()
    assert d["entity_id"] == "U1"
    assert d["event_time"] == now
    assert d["f1"] == 1
    assert d["f2"] == "hello"
    assert "ingestion_time" in d
