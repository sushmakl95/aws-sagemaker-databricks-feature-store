"""Lambda: Kinesis events -> feature computation -> SageMaker Feature Store PutRecord.

Event source: Kinesis Data Stream (configured via event source mapping).
Each batch of ~100 records is processed and fanned out to one feature group per
feature view defined in the FEATURE_GROUP_MAP environment variable.

Expected record format (after JSON decode):
  {
    "user_id": "U123",
    "event_type": "view|click|purchase",
    "product_id": "P456",
    "amount": 49.99,
    "event_ts": "2026-04-22T10:15:00Z"
  }

The Lambda computes streaming features (per-record recency features) by
maintaining a small per-user running state in DynamoDB. For true stateful
aggregations (rolling counts over 5 min), use Flink/KDA -- see the separate
streaming-platform repo.
"""

from __future__ import annotations

import base64
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import boto3

from features.core.types import FeatureRecord
from features.sinks.sagemaker_fs_sink import (
    SageMakerFSSink,
    SageMakerFSSinkConfig,
)
from features.utils.logging_config import get_logger

log = get_logger(__name__, component="lambda.streaming_pipeline")


# Environment configuration
FEATURE_GROUP_NAME = os.environ["FEATURE_GROUP_NAME"]
STATE_TABLE_NAME = os.environ["STATE_TABLE_NAME"]
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Lazy-initialized clients (reused across warm invocations)
_ddb = boto3.resource("dynamodb", region_name=AWS_REGION).Table(STATE_TABLE_NAME)
_sink = SageMakerFSSink(
    SageMakerFSSinkConfig(
        feature_group_name=FEATURE_GROUP_NAME,
        region=AWS_REGION,
        max_workers=5,
        retries_per_record=2,
    )
)


@dataclass
class UserState:
    """Compact per-user state kept in DynamoDB for feature computation."""
    last_event_ts: float = 0.0
    events_last_5min: int = 0
    events_last_1h: int = 0
    distinct_products_1h: list[str] | None = None
    total_order_value_1h: float = 0.0
    orders_last_1h: int = 0

    def to_ddb_item(self) -> dict[str, Any]:
        return {
            "last_event_ts": str(self.last_event_ts),
            "events_last_5min": self.events_last_5min,
            "events_last_1h": self.events_last_1h,
            "distinct_products_1h": ",".join(self.distinct_products_1h or []),
            "total_order_value_1h": str(self.total_order_value_1h),
            "orders_last_1h": self.orders_last_1h,
        }

    @classmethod
    def from_ddb_item(cls, item: dict[str, Any]) -> UserState:
        return cls(
            last_event_ts=float(item.get("last_event_ts", 0)),
            events_last_5min=int(item.get("events_last_5min", 0)),
            events_last_1h=int(item.get("events_last_1h", 0)),
            distinct_products_1h=(item.get("distinct_products_1h", "") or "").split(",")
                if item.get("distinct_products_1h") else [],
            total_order_value_1h=float(item.get("total_order_value_1h", 0)),
            orders_last_1h=int(item.get("orders_last_1h", 0)),
        )


def _load_state(user_id: str) -> UserState:
    response = _ddb.get_item(Key={"user_id": user_id})
    item = response.get("Item")
    if not item:
        return UserState()
    return UserState.from_ddb_item(item)


def _save_state(user_id: str, state: UserState) -> None:
    _ddb.put_item(Item={"user_id": user_id, **state.to_ddb_item()})


def _apply_window_decay(state: UserState, now_ts: float) -> UserState:
    """Reset 5min/1h counters if the last event is outside the window."""
    age = now_ts - state.last_event_ts
    if age > 3600:
        state.events_last_1h = 0
        state.distinct_products_1h = []
        state.total_order_value_1h = 0.0
        state.orders_last_1h = 0
    if age > 300:
        state.events_last_5min = 0
    return state


def _apply_event(state: UserState, event: dict, now_ts: float) -> UserState:
    state = _apply_window_decay(state, now_ts)
    state.events_last_5min += 1
    state.events_last_1h += 1

    product_id = event.get("product_id")
    if product_id:
        distinct = set(state.distinct_products_1h or [])
        distinct.add(product_id)
        state.distinct_products_1h = list(distinct)

    if event.get("event_type") == "purchase":
        amount = float(event.get("amount", 0))
        state.total_order_value_1h += amount
        state.orders_last_1h += 1

    state.last_event_ts = now_ts
    return state


def _build_feature_record(
    user_id: str, state: UserState, event_time: datetime
) -> FeatureRecord:
    avg_order_value = (
        state.total_order_value_1h / state.orders_last_1h
        if state.orders_last_1h > 0 else 0.0
    )
    seconds_since_last = int(event_time.timestamp() - state.last_event_ts)
    return FeatureRecord(
        feature_view="user_recency",
        entity_id=user_id,
        event_time=event_time,
        features={
            "events_last_5min": state.events_last_5min,
            "events_last_1h": state.events_last_1h,
            "distinct_products_last_1h": len(state.distinct_products_1h or []),
            "avg_order_value_last_1h": round(avg_order_value, 4),
            "seconds_since_last_event": max(seconds_since_last, 0),
        },
    )


def _parse_kinesis_record(raw: dict) -> dict | None:
    try:
        payload = base64.b64decode(raw["kinesis"]["data"]).decode("utf-8")
        return json.loads(payload)
    except Exception as exc:
        log.warning("parse_failed", error=str(exc))
        return None


def handler(event: dict, context: Any) -> dict:
    """Entry point for Kinesis event source mapping."""
    records = event.get("Records", [])
    if not records:
        return {"ok": True, "processed": 0}

    # Parse + group by user_id
    events_by_user: dict[str, list[dict]] = defaultdict(list)
    for raw in records:
        parsed = _parse_kinesis_record(raw)
        if not parsed or "user_id" not in parsed:
            continue
        events_by_user[parsed["user_id"]].append(parsed)

    feature_records: list[FeatureRecord] = []
    now = datetime.now(UTC)
    now_ts = now.timestamp()

    for user_id, events in events_by_user.items():
        state = _load_state(user_id)
        for evt in events:
            state = _apply_event(state, evt, now_ts)
        _save_state(user_id, state)

        feature_records.append(_build_feature_record(user_id, state, now))

    result = _sink.write_batch(feature_records)
    log.info(
        "lambda_batch_done",
        input_records=len(records),
        feature_records=len(feature_records),
        ingested=result.records_ingested,
        failed=result.records_failed,
    )
    return {
        "ok": result.records_failed == 0,
        "processed": len(records),
        "feature_records": len(feature_records),
        "ingested": result.records_ingested,
        "failed": result.records_failed,
    }
