"""Submit training jobs to Databricks ML.

Uses the Databricks Jobs REST API to trigger a one-off notebook run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

from features.utils.logging_config import get_logger

log = get_logger(__name__, component="training.databricks_runner")


@dataclass
class DatabricksTrainingConfig:
    workspace_url: str
    """e.g., https://dbc-xxx.cloud.databricks.com"""
    token: str
    notebook_path: str
    """e.g., /Shared/feature-platform/02_ml_training"""
    cluster_spec: dict
    """JSON cluster spec -- see existing job_cluster definitions."""
    notebook_params: dict[str, str]
    job_name_prefix: str = "feature-platform-training"
    instance_profile_arn: str | None = None
    timeout_seconds: int = 3600


class DatabricksTrainingRunner:
    def __init__(self, config: DatabricksTrainingConfig):
        self.config = config
        self.base_url = config.workspace_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {config.token}",
            "Content-Type": "application/json",
        }

    def submit(self) -> int:
        """Submit a one-off notebook run. Returns the run_id."""
        payload = {
            "run_name": f"{self.config.job_name_prefix}-{int(time.time())}",
            "new_cluster": self.config.cluster_spec,
            "notebook_task": {
                "notebook_path": self.config.notebook_path,
                "base_parameters": self.config.notebook_params,
            },
            "timeout_seconds": self.config.timeout_seconds,
            "max_retries": 1,
        }
        if self.config.instance_profile_arn:
            payload["new_cluster"]["aws_attributes"] = {
                "instance_profile_arn": self.config.instance_profile_arn,
                "availability": "SPOT_WITH_FALLBACK",
            }

        response = requests.post(
            f"{self.base_url}/api/2.1/jobs/runs/submit",
            headers=self.headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        run_id = response.json()["run_id"]
        log.info("databricks_training_submit", run_id=run_id,
                 notebook=self.config.notebook_path)
        return run_id

    def wait_for_completion(self, run_id: int, poll_seconds: int = 30) -> dict:
        """Block until the run terminates. Returns final state."""
        while True:
            response = requests.get(
                f"{self.base_url}/api/2.1/jobs/runs/get",
                headers=self.headers,
                params={"run_id": run_id},
                timeout=30,
            )
            response.raise_for_status()
            state = response.json().get("state", {})
            life_cycle = state.get("life_cycle_state", "")

            log.info("databricks_training_status", run_id=run_id,
                     state=life_cycle)

            if life_cycle in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
                return response.json()
            time.sleep(poll_seconds)
