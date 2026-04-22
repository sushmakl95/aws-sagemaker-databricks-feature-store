"""Training entry point.

Runs locally (for dev), inside a SageMaker Training Job, or inside a Databricks
ML job. MLflow autologging captures params, metrics, artifacts.

Model types supported:
  - xgboost (default, tabular)
  - sklearn-logreg (baseline)
  - sklearn-rf (baseline)

Reads training data from:
  - SageMaker FS offline via Athena (when run via sagemaker_runner)
  - Databricks FS via spark.read.table (when run via databricks_runner)
  - Local parquet (for dev)
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

import mlflow
import mlflow.sklearn
import mlflow.xgboost
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split

from features.utils.logging_config import get_logger

log = get_logger(__name__, component="training.train")


@dataclass
class TrainingConfig:
    model_type: str = "xgboost"
    training_data_path: str = ""
    label_column: str = "label"
    exclude_columns: list[str] | None = None
    test_size: float = 0.2
    random_state: int = 42
    mlflow_tracking_uri: str = ""
    mlflow_experiment: str = "feature-platform"
    output_dir: str = "/opt/ml/model"
    """Where to save the trained model. SageMaker expects /opt/ml/model."""


def load_training_data(path: str) -> pd.DataFrame:
    """Load training data from a local path, S3, or a Delta table."""
    if path.startswith("s3://") or path.startswith("file://"):
        return pd.read_parquet(path)
    if path.endswith(".parquet"):
        return pd.read_parquet(path)
    if path.endswith(".csv"):
        return pd.read_csv(path)
    # Assume it's a Delta/Iceberg table name
    raise ValueError(
        f"Unsupported path format: {path} -- use Spark for Delta/Iceberg tables"
    )


def prepare_features(
    df: pd.DataFrame,
    label_col: str,
    exclude_cols: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Split into features X and labels y. Drops entity/timestamp columns."""
    exclude = set(exclude_cols or [])
    exclude.add(label_col)
    # Standard columns that should never be features
    for standard in ("entity_id", "event_time", "ingestion_time", "_row_id"):
        exclude.add(standard)

    feature_cols = [c for c in df.columns if c not in exclude]
    X = df[feature_cols].copy()
    y = df[label_col].copy()
    log.info("features_prepared", n_features=len(feature_cols), n_rows=len(X))
    return X, y


def train_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    model_type: str,
    random_state: int = 42,
):
    """Train a model based on the configured type."""
    if model_type == "xgboost":
        import xgboost as xgb
        model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            eval_metric="logloss",
            random_state=random_state,
            use_label_encoder=False,
        )
    elif model_type == "sklearn-logreg":
        model = LogisticRegression(max_iter=1000, random_state=random_state)
    elif model_type == "sklearn-rf":
        model = RandomForestClassifier(
            n_estimators=200,
            max_depth=10,
            random_state=random_state,
            n_jobs=-1,
        )
    else:
        raise ValueError(f"Unsupported model_type: {model_type}")

    log.info("training_start", model_type=model_type, n_rows=len(X_train))
    model.fit(X_train, y_train)
    return model


def evaluate_model(
    model,
    X_test: pd.DataFrame,
    y_test: pd.Series,
) -> dict[str, float]:
    """Evaluate on a held-out test set. Returns metric dict."""
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    metrics = {
        "accuracy": accuracy_score(y_test, y_pred),
        "f1": f1_score(y_test, y_pred, average="weighted"),
        "roc_auc": roc_auc_score(y_test, y_proba),
    }
    log.info("evaluation_done", **metrics)
    return metrics


def save_model(model, model_type: str, output_dir: str) -> str:
    """Save model artifact. Returns the path."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    if model_type == "xgboost":
        path = os.path.join(output_dir, "xgboost-model.json")
        model.save_model(path)
    else:
        import joblib
        path = os.path.join(output_dir, "model.joblib")
        joblib.dump(model, path)
    log.info("model_saved", path=path)
    return path


def run(config: TrainingConfig) -> dict[str, float]:
    """End-to-end training with MLflow logging."""
    if config.mlflow_tracking_uri:
        mlflow.set_tracking_uri(config.mlflow_tracking_uri)
    mlflow.set_experiment(config.mlflow_experiment)

    # Autolog enabled for the relevant library
    if config.model_type == "xgboost":
        mlflow.xgboost.autolog(log_input_examples=False)
    else:
        mlflow.sklearn.autolog(log_input_examples=False)

    with mlflow.start_run() as run:
        mlflow.log_params({
            "model_type": config.model_type,
            "test_size": config.test_size,
            "random_state": config.random_state,
        })

        df = load_training_data(config.training_data_path)
        X, y = prepare_features(df, config.label_column, config.exclude_columns)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y,
            test_size=config.test_size,
            random_state=config.random_state,
            stratify=y,
        )

        model = train_model(X_train, y_train, config.model_type, config.random_state)
        metrics = evaluate_model(model, X_test, y_test)
        for name, value in metrics.items():
            mlflow.log_metric(f"test_{name}", value)

        save_model(model, config.model_type, config.output_dir)

        # Log feature importances for XGBoost/RF
        if hasattr(model, "feature_importances_"):
            importances = dict(zip(X_train.columns, model.feature_importances_.tolist(), strict=False))
            mlflow.log_dict(importances, "feature_importances.json")

        log.info(
            "training_run_complete",
            run_id=run.info.run_id,
            **{f"test_{k}": v for k, v in metrics.items()},
        )
        return metrics


def _parse_args() -> TrainingConfig:
    p = argparse.ArgumentParser()
    p.add_argument("--model-type", default="xgboost",
                   choices=["xgboost", "sklearn-logreg", "sklearn-rf"])
    p.add_argument("--training-data-path", required=True)
    p.add_argument("--label-column", default="label")
    p.add_argument("--test-size", type=float, default=0.2)
    p.add_argument("--random-state", type=int, default=42)
    p.add_argument("--mlflow-tracking-uri", default="")
    p.add_argument("--mlflow-experiment", default="feature-platform")
    p.add_argument("--output-dir", default="/opt/ml/model")
    args = p.parse_args()
    return TrainingConfig(
        model_type=args.model_type,
        training_data_path=args.training_data_path,
        label_column=args.label_column,
        test_size=args.test_size,
        random_state=args.random_state,
        mlflow_tracking_uri=args.mlflow_tracking_uri,
        mlflow_experiment=args.mlflow_experiment,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    np.random.seed(42)
    config = _parse_args()
    run(config)
