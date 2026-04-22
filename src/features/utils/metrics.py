"""CloudWatch metrics emitter for feature pipeline."""

from __future__ import annotations

from typing import Any

import boto3

from features.utils.logging_config import get_logger

log = get_logger(__name__, component="metrics")


class FeatureMetricsEmitter:
    """Emit custom feature pipeline metrics to CloudWatch."""

    def __init__(self, namespace: str = "FeaturePlatform", region: str = "us-east-1"):
        self.namespace = namespace
        self.region = region
        self.client = boto3.client("cloudwatch", region_name=region)

    def emit_ingest_metrics(
        self,
        feature_view: str,
        records_ingested: int,
        records_failed: int,
        duration_ms: int,
    ) -> None:
        dims = [{"Name": "FeatureView", "Value": feature_view}]
        data = [
            {"MetricName": "RecordsIngested", "Value": records_ingested,
             "Unit": "Count", "Dimensions": dims},
            {"MetricName": "RecordsFailed", "Value": records_failed,
             "Unit": "Count", "Dimensions": dims},
            {"MetricName": "IngestDurationMs", "Value": duration_ms,
             "Unit": "Milliseconds", "Dimensions": dims},
        ]
        self._put(data)

    def emit_lookup_metrics(
        self,
        feature_view: str,
        lookup_count: int,
        cache_hits: int,
        avg_latency_ms: float,
    ) -> None:
        dims = [{"Name": "FeatureView", "Value": feature_view}]
        data = [
            {"MetricName": "OnlineLookupCount", "Value": lookup_count,
             "Unit": "Count", "Dimensions": dims},
            {"MetricName": "OnlineCacheHits", "Value": cache_hits,
             "Unit": "Count", "Dimensions": dims},
            {"MetricName": "OnlineLookupLatencyMs", "Value": avg_latency_ms,
             "Unit": "Milliseconds", "Dimensions": dims},
        ]
        self._put(data)

    def _put(self, data: list[dict[str, Any]]) -> None:
        try:
            for chunk_start in range(0, len(data), 20):
                chunk = data[chunk_start : chunk_start + 20]
                self.client.put_metric_data(Namespace=self.namespace, MetricData=chunk)
        except Exception as exc:
            log.warning("metric_emit_failed", error=str(exc))
