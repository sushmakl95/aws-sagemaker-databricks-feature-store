"""OpenLineage emitter for feature-store jobs.

Every batch feature computation and online-store sync emits lineage events
with input datasets (raw event topics, Delta tables) and output datasets
(feature views). Consumed by Marquez / DataHub / OpenMetadata so a model
consumer can trace every feature back to its raw source.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureLineageConfig:
    url: str
    namespace: str
    api_key: str | None = None

    @classmethod
    def from_env(cls) -> FeatureLineageConfig:
        return cls(
            url=os.environ.get("OPENLINEAGE_URL", "http://marquez.internal:5000"),
            namespace=os.environ.get("OPENLINEAGE_NAMESPACE", "feature-platform"),
            api_key=os.environ.get("OPENLINEAGE_API_KEY"),
        )


def build_run_event(
    *,
    job_name: str,
    run_id: str,
    inputs: list[str],
    outputs: list[str],
    event_type: str = "COMPLETE",
    namespace: str = "feature-platform",
) -> dict:
    """Build a minimal OpenLineage RunEvent JSON payload.

    Intentionally avoids importing the openlineage-python SDK to keep CI fast;
    the SDK is used in runtime code paths (not in this helper).
    """
    return {
        "eventType": event_type,
        "eventTime": "",  # caller sets
        "run": {"runId": run_id},
        "job": {"namespace": namespace, "name": job_name},
        "inputs": [{"namespace": namespace, "name": i} for i in inputs],
        "outputs": [{"namespace": namespace, "name": o} for o in outputs],
        "producer": "https://github.com/sushmakl95/aws-sagemaker-databricks-feature-store",
    }
