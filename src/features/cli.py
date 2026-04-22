"""Feature platform CLI."""

from __future__ import annotations

import json
from pathlib import Path

import click

from features.monitoring import (
    BaselineConfig,
    detect_drift,
    generate_baseline,
)
from features.registry import apply_registry, list_feature_views, validate_repo
from features.training import (
    SageMakerTrainingConfig,
    SageMakerTrainingRunner,
    TrainingConfig,
    run_training,
)
from features.utils.logging_config import get_logger

log = get_logger(__name__, component="cli")


@click.group()
def cli() -> None:
    """Feature platform CLI."""


# --------------------------------------------------------------------------
# Feast
# --------------------------------------------------------------------------
@cli.command("feast-sync")
@click.option("--repo-path", default="src/feast_repo")
@click.option("--dry-run", is_flag=True, help="Preview changes only")
def feast_sync(repo_path: str, dry_run: bool) -> None:
    """Sync Feast registry via `feast apply`."""
    if not validate_repo(repo_path):
        raise click.ClickException(f"Feast repo validation failed: {repo_path}")

    result = apply_registry(repo_path, dry_run=dry_run)
    click.echo(result["stdout"])
    if result["returncode"] != 0:
        click.echo(result["stderr"], err=True)
        raise click.ClickException(f"feast apply failed with code {result['returncode']}")

    click.echo(f"Feature views in repo: {', '.join(list_feature_views(repo_path))}")


# --------------------------------------------------------------------------
# Training
# --------------------------------------------------------------------------
@cli.command("train")
@click.option("--model-type", default="xgboost",
              type=click.Choice(["xgboost", "sklearn-logreg", "sklearn-rf"]))
@click.option("--training-data-path", required=True)
@click.option("--label-column", default="label")
@click.option("--test-size", default=0.2, type=float)
@click.option("--mlflow-tracking-uri", default="")
@click.option("--mlflow-experiment", default="feature-platform")
@click.option("--output-dir", default="./model-output")
def train(
    model_type: str,
    training_data_path: str,
    label_column: str,
    test_size: float,
    mlflow_tracking_uri: str,
    mlflow_experiment: str,
    output_dir: str,
) -> None:
    """Run training locally."""
    config = TrainingConfig(
        model_type=model_type,
        training_data_path=training_data_path,
        label_column=label_column,
        test_size=test_size,
        mlflow_tracking_uri=mlflow_tracking_uri,
        mlflow_experiment=mlflow_experiment,
        output_dir=output_dir,
    )
    metrics = run_training(config)
    click.echo(json.dumps(metrics, indent=2))


@cli.command("train-sagemaker")
@click.option("--job-name-prefix", required=True)
@click.option("--role-arn", required=True)
@click.option("--image-uri", required=True)
@click.option("--input-s3", required=True)
@click.option("--output-s3", required=True)
@click.option("--instance-type", default="ml.m5.xlarge")
@click.option("--spot/--no-spot", default=True)
@click.option("--wait/--no-wait", default=True)
def train_sagemaker(
    job_name_prefix: str,
    role_arn: str,
    image_uri: str,
    input_s3: str,
    output_s3: str,
    instance_type: str,
    spot: bool,
    wait: bool,
) -> None:
    """Submit a SageMaker Training Job."""
    config = SageMakerTrainingConfig(
        job_name_prefix=job_name_prefix,
        role_arn=role_arn,
        training_image_uri=image_uri,
        input_s3_path=input_s3,
        output_s3_path=output_s3,
        instance_type=instance_type,
        use_spot=spot,
    )
    runner = SageMakerTrainingRunner(config)
    job_name = runner.submit()
    click.echo(f"Submitted: {job_name}")
    if wait:
        final_state = runner.wait_for_completion(job_name)
        status = final_state["TrainingJobStatus"]
        click.echo(f"Final status: {status}")


# --------------------------------------------------------------------------
# Monitoring
# --------------------------------------------------------------------------
@cli.command("generate-baseline")
@click.option("--input-path", required=True)
@click.option("--output-dir", default="./baseline")
def generate_baseline_cmd(input_path: str, output_dir: str) -> None:
    """Generate training baseline for Model Monitor."""
    config = BaselineConfig(input_path=input_path, output_dir=output_dir)
    result = generate_baseline(config)
    click.echo(json.dumps(result, indent=2))


@cli.command("check-drift")
@click.option("--baseline-path", required=True)
@click.option("--current-path", required=True)
@click.option("--psi-threshold", default=0.25, type=float)
@click.option("--output-path", default="./drift-report.json")
def check_drift_cmd(
    baseline_path: str,
    current_path: str,
    psi_threshold: float,
    output_path: str,
) -> None:
    """Run PSI + KS drift detection between baseline and current data."""
    import pandas as pd
    baseline = pd.read_parquet(baseline_path)
    current = pd.read_parquet(current_path)

    report = detect_drift(baseline, current, psi_threshold=psi_threshold)
    Path(output_path).write_text(json.dumps(report.to_dict(), indent=2))
    click.echo(f"Drift detected: {report.any_drift}")
    if report.any_drift:
        click.echo(f"Drifted features: {', '.join(report.drifted_features)}")
    click.echo(f"Full report at: {output_path}")


# --------------------------------------------------------------------------
# Config validation
# --------------------------------------------------------------------------
@cli.command("validate-feature-views")
@click.option("--repo-path", default="src/feast_repo/feature_views")
def validate_feature_views_cmd(repo_path: str) -> None:
    """Validate feature view definitions."""
    import subprocess
    # fixed command; repo_path is internal input
    result = subprocess.run(
        ["python", "scripts/validate_feature_views.py", repo_path],
        capture_output=True, text=True, check=False,
    )
    click.echo(result.stdout)
    if result.returncode != 0:
        click.echo(result.stderr, err=True)
        raise click.ClickException("Validation failed")


if __name__ == "__main__":
    cli()
