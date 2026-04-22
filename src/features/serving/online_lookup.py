"""Online feature lookup via Feast.

This is the client used inside inference containers. Feast abstracts over the
configured online store (DynamoDB for SageMaker FS, Online Tables for Databricks FS).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from features.utils.logging_config import get_logger
from features.utils.metrics import FeatureMetricsEmitter

log = get_logger(__name__, component="serving.online_lookup")


@dataclass
class OnlineLookupConfig:
    feast_repo_path: str
    """Path to the Feast repo (for loading FeatureStore)."""
    emit_metrics: bool = True


@dataclass
class LookupStats:
    total_lookups: int = 0
    cache_hits: int = 0
    total_latency_ms: float = 0.0
    failures: list[str] = field(default_factory=list)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / max(self.total_lookups, 1)


class OnlineFeatureLookup:
    """Feast-backed online feature lookup wrapper."""

    def __init__(self, config: OnlineLookupConfig):
        self.config = config
        self._feature_store = None
        self.metrics = FeatureMetricsEmitter() if config.emit_metrics else None
        self.stats = LookupStats()

    @property
    def feature_store(self):
        """Lazy-initialize feature store."""
        if self._feature_store is None:
            from feast import FeatureStore
            self._feature_store = FeatureStore(repo_path=self.config.feast_repo_path)
        return self._feature_store

    def get_online_features(
        self,
        features: list[str],
        entity_rows: list[dict],
        full_feature_names: bool = True,
    ) -> dict:
        """Fetch online features for a batch of entity rows.

        `features` format: ["fv_name:feature_name", ...]
        `entity_rows` format: [{"user_id": "U123"}, ...]
        """
        start = time.time()
        try:
            response = self.feature_store.get_online_features(
                features=features,
                entity_rows=entity_rows,
                full_feature_names=full_feature_names,
            )
            result = response.to_dict()

            duration_ms = (time.time() - start) * 1000
            self.stats.total_lookups += len(entity_rows)
            self.stats.total_latency_ms += duration_ms

            log.info(
                "online_lookup_ok",
                n_entities=len(entity_rows),
                n_features=len(features),
                duration_ms=int(duration_ms),
            )
            return result
        except Exception as exc:
            self.stats.failures.append(str(exc))
            log.error("online_lookup_failed", error=str(exc))
            raise

    def flush_metrics(self, feature_view: str = "all") -> None:
        """Emit accumulated stats to CloudWatch."""
        if not self.metrics or self.stats.total_lookups == 0:
            return
        self.metrics.emit_lookup_metrics(
            feature_view=feature_view,
            lookup_count=self.stats.total_lookups,
            cache_hits=self.stats.cache_hits,
            avg_latency_ms=self.stats.avg_latency_ms,
        )
        self.stats = LookupStats()
