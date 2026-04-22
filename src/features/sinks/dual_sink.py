"""Dual-write sink for running both SageMaker FS and Databricks FS in parallel.

Use case: teams migrating from one platform to the other, or running A/B
comparisons of inference behavior across backends.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from pyspark.sql import DataFrame

from features.core.types import FeatureRecord
from features.sinks.databricks_fs_sink import (
    DatabricksFSSink,
    DatabricksFSSinkConfig,
)
from features.sinks.sagemaker_fs_sink import (
    SageMakerFSSink,
    SageMakerFSSinkConfig,
    SageMakerFSSinkResult,
)
from features.utils.logging_config import get_logger

log = get_logger(__name__, component="sink.dual")


@dataclass
class DualSinkConfig:
    sagemaker: SageMakerFSSinkConfig
    databricks: DatabricksFSSinkConfig
    fail_on_either: bool = False
    """If True, a failure in either sink raises. Else both are attempted."""


@dataclass
class DualSinkResult:
    sagemaker: SageMakerFSSinkResult = field(default_factory=SageMakerFSSinkResult)
    databricks: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class DualSink:
    def __init__(self, config: DualSinkConfig):
        self.config = config
        self.sagemaker = SageMakerFSSink(config.sagemaker)
        self.databricks = DatabricksFSSink(config.databricks)

    def write_batch(
        self,
        records: list[FeatureRecord],
        df: DataFrame,
    ) -> DualSinkResult:
        """Write the same batch of features to both stores in parallel.

        `records` is the list format for SageMaker FS PutRecord.
        `df` is the DataFrame form for Databricks FS write_table.
        """
        result = DualSinkResult()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures: dict[Future[Any], str] = {
                pool.submit(self.sagemaker.write_batch, records): "sagemaker",
                pool.submit(self.databricks.write_batch, df): "databricks",
            }
            for future in as_completed(futures):
                backend = futures[future]
                try:
                    if backend == "sagemaker":
                        result.sagemaker = future.result()
                    else:
                        result.databricks = future.result()
                except Exception as exc:
                    msg = f"{backend}: {exc}"
                    result.errors.append(msg)
                    log.error("dual_sink_backend_failed", backend=backend, error=str(exc))
                    if self.config.fail_on_either:
                        raise

        return result
