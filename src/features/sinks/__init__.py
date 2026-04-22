"""Feature store sinks."""

from features.sinks.databricks_fs_sink import (
    DatabricksFSSink,
    DatabricksFSSinkConfig,
)
from features.sinks.dual_sink import DualSink, DualSinkConfig, DualSinkResult
from features.sinks.sagemaker_fs_sink import (
    SageMakerFSSink,
    SageMakerFSSinkConfig,
    SageMakerFSSinkResult,
    write_records,
)

__all__ = [
    "DatabricksFSSink",
    "DatabricksFSSinkConfig",
    "DualSink",
    "DualSinkConfig",
    "DualSinkResult",
    "SageMakerFSSink",
    "SageMakerFSSinkConfig",
    "SageMakerFSSinkResult",
    "write_records",
]
