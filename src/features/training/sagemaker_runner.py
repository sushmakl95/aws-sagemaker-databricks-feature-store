"""Submit training jobs to SageMaker.

Wraps SageMaker SDK's Estimator with our defaults and MLflow tracking URI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import boto3

from features.utils.logging_config import get_logger

log = get_logger(__name__, component="training.sagemaker_runner")


@dataclass
class SageMakerTrainingConfig:
    job_name_prefix: str
    role_arn: str
    """Execution role with SM + S3 + Feature Store access."""
    training_image_uri: str
    """ECR URI of the training container."""
    input_s3_path: str
    """Training data on S3 -- typically the SageMaker FS offline store."""
    output_s3_path: str
    """Where SageMaker writes the model artifact."""
    instance_type: str = "ml.m5.xlarge"
    instance_count: int = 1
    use_spot: bool = True
    max_runtime_seconds: int = 3600
    max_wait_seconds: int = 7200
    """Total time budget when use_spot=True (includes spot wait)."""
    region: str = "us-east-1"
    model_type: str = "xgboost"
    mlflow_tracking_uri: str = ""
    mlflow_experiment: str = "feature-platform"
    tags: dict[str, str] | None = None


class SageMakerTrainingRunner:
    def __init__(self, config: SageMakerTrainingConfig):
        self.config = config
        self.client = boto3.client("sagemaker", region_name=config.region)

    def submit(self) -> str:
        """Submit a training job. Returns the job name."""
        ts = int(time.time())
        job_name = f"{self.config.job_name_prefix}-{ts}"

        checkpoint_config = {}
        stopping_condition: dict[str, int] = {
            "MaxRuntimeInSeconds": self.config.max_runtime_seconds,
        }
        if self.config.use_spot:
            stopping_condition["MaxWaitTimeInSeconds"] = self.config.max_wait_seconds
            checkpoint_config = {
                "S3Uri": f"{self.config.output_s3_path}/checkpoints/{job_name}/",
            }

        hyperparams = {
            "model-type": self.config.model_type,
            "training-data-path": "/opt/ml/input/data/train/",
            "output-dir": "/opt/ml/model",
            "mlflow-tracking-uri": self.config.mlflow_tracking_uri,
            "mlflow-experiment": self.config.mlflow_experiment,
        }

        request = {
            "TrainingJobName": job_name,
            "RoleArn": self.config.role_arn,
            "AlgorithmSpecification": {
                "TrainingImage": self.config.training_image_uri,
                "TrainingInputMode": "File",
            },
            "HyperParameters": {k: str(v) for k, v in hyperparams.items()},
            "InputDataConfig": [{
                "ChannelName": "train",
                "DataSource": {
                    "S3DataSource": {
                        "S3DataType": "S3Prefix",
                        "S3Uri": self.config.input_s3_path,
                        "S3DataDistributionType": "FullyReplicated",
                    },
                },
            }],
            "OutputDataConfig": {
                "S3OutputPath": self.config.output_s3_path,
            },
            "ResourceConfig": {
                "InstanceType": self.config.instance_type,
                "InstanceCount": self.config.instance_count,
                "VolumeSizeInGB": 30,
            },
            "StoppingCondition": stopping_condition,
            "EnableManagedSpotTraining": self.config.use_spot,
            "Tags": [
                {"Key": k, "Value": v}
                for k, v in (self.config.tags or {}).items()
            ],
        }
        if checkpoint_config:
            request["CheckpointConfig"] = checkpoint_config

        log.info("sagemaker_training_submit", job_name=job_name,
                 spot=self.config.use_spot, instance=self.config.instance_type)

        self.client.create_training_job(**request)
        return job_name

    def wait_for_completion(self, job_name: str, poll_seconds: int = 30) -> dict:
        """Block until the job terminates. Returns the final Describe response."""
        while True:
            response = self.client.describe_training_job(TrainingJobName=job_name)
            status = response["TrainingJobStatus"]
            log.info("sagemaker_training_status", job_name=job_name, status=status)
            if status in {"Completed", "Failed", "Stopped"}:
                return response
            time.sleep(poll_seconds)
