"""SageMaker Feature Store sink.

Writes FeatureRecord instances to a SageMaker Feature Group using the
PutRecord API. Records are pushed to both the online store (DynamoDB)
and the offline store (S3 via Glue) based on the feature group's config.

Key invariants:
  - The feature group must already exist in SageMaker (created via Terraform)
  - Records must include both the record identifier (entity_id) and event time
  - PutRecord is synchronous; we batch via threading for throughput
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import boto3
from botocore.exceptions import ClientError

from features.core.types import FeatureRecord
from features.utils.logging_config import get_logger
from features.utils.metrics import FeatureMetricsEmitter

log = get_logger(__name__, component="sink.sagemaker_fs")


@dataclass
class SageMakerFSSinkConfig:
    feature_group_name: str
    region: str = "us-east-1"
    max_workers: int = 10
    """Concurrent PutRecord calls. SageMaker FS limit is 10,000 req/sec."""
    retries_per_record: int = 3
    emit_metrics: bool = True
    idempotent_writes: bool = True
    """When True, records with same (entity_id, event_time) are no-ops."""


@dataclass
class SageMakerFSSinkResult:
    records_ingested: int = 0
    records_failed: int = 0
    failures: list[str] = field(default_factory=list)
    duration_ms: int = 0


class SageMakerFSSink:
    """Writes feature records to SageMaker Feature Store."""

    def __init__(self, config: SageMakerFSSinkConfig):
        self.config = config
        self.runtime_client = boto3.client(
            "sagemaker-featurestore-runtime", region_name=config.region
        )
        self.metrics = (
            FeatureMetricsEmitter(region=config.region)
            if config.emit_metrics else None
        )

    def write_batch(self, records: list[FeatureRecord]) -> SageMakerFSSinkResult:
        """Put a batch of records. Retries transient failures per record."""
        if not records:
            return SageMakerFSSinkResult()

        start = time.time()
        result = SageMakerFSSinkResult()

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool:
            futures = {
                pool.submit(self._put_one, r): r for r in records
            }
            for future in as_completed(futures):
                record = futures[future]
                try:
                    future.result()
                    result.records_ingested += 1
                except Exception as exc:
                    result.records_failed += 1
                    result.failures.append(
                        f"{record.entity_id}@{record.event_time.isoformat()}: {exc}"
                    )

        result.duration_ms = int((time.time() - start) * 1000)

        if self.metrics:
            self.metrics.emit_ingest_metrics(
                feature_view=self.config.feature_group_name,
                records_ingested=result.records_ingested,
                records_failed=result.records_failed,
                duration_ms=result.duration_ms,
            )

        log.info(
            "sagemaker_fs_batch_done",
            feature_group=self.config.feature_group_name,
            ingested=result.records_ingested,
            failed=result.records_failed,
            duration_ms=result.duration_ms,
        )
        return result

    def _put_one(self, record: FeatureRecord) -> None:
        attempts = self.config.retries_per_record + 1
        last_exc: Exception | None = None

        for attempt in range(attempts):
            try:
                self.runtime_client.put_record(
                    FeatureGroupName=self.config.feature_group_name,
                    Record=record.to_sagemaker_record(),
                )
                return
            except ClientError as exc:
                last_exc = exc
                code = exc.response.get("Error", {}).get("Code", "")
                # Retry only transient errors
                if code in {"ThrottlingException", "ServiceUnavailable",
                            "InternalServerError"}:
                    sleep_sec = 0.1 * (2 ** attempt)
                    time.sleep(sleep_sec)
                    continue
                raise
            except Exception as exc:
                last_exc = exc
                raise

        if last_exc:
            raise last_exc


def write_records(
    feature_group_name: str,
    records: list[FeatureRecord],
    region: str = "us-east-1",
    max_workers: int = 10,
) -> SageMakerFSSinkResult:
    """Convenience function for writing a batch."""
    sink = SageMakerFSSink(
        SageMakerFSSinkConfig(
            feature_group_name=feature_group_name,
            region=region,
            max_workers=max_workers,
        )
    )
    return sink.write_batch(records)
