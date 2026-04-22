"""Predictor (inference handler) for SageMaker Endpoint container.

SageMaker's Python SDK calls 4 functions:
  - model_fn(model_dir)          -- load the model once at startup
  - input_fn(body, content_type) -- parse the request
  - predict_fn(data, model)      -- produce predictions
  - output_fn(pred, accept)      -- serialize the response

This module exports those four. The inference container runs this at runtime.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from features.serving.online_lookup import OnlineFeatureLookup, OnlineLookupConfig
from features.utils.logging_config import get_logger

log = get_logger(__name__, component="serving.predictor")


# Feast repo is bundled into the container at /opt/ml/code/feast_repo
FEAST_REPO_PATH = os.environ.get("FEAST_REPO_PATH", "/opt/ml/code/feast_repo")
FEATURE_LIST_JSON = os.environ.get("FEATURE_LIST_JSON", "/opt/ml/code/feature_list.json")

# Lazy-initialized at first request
_online_lookup: OnlineFeatureLookup | None = None
_feature_list: list[str] | None = None


def _get_online_lookup() -> OnlineFeatureLookup:
    global _online_lookup
    if _online_lookup is None:
        _online_lookup = OnlineFeatureLookup(
            OnlineLookupConfig(feast_repo_path=FEAST_REPO_PATH)
        )
    return _online_lookup


def _get_feature_list() -> list[str]:
    global _feature_list
    if _feature_list is None:
        with Path(FEATURE_LIST_JSON).open() as f:
            _feature_list = json.load(f)["features"]
    return _feature_list


def model_fn(model_dir: str):
    """Load the trained model from disk. Called once at endpoint startup."""
    model_files = list(Path(model_dir).iterdir())
    log.info("model_fn_start", model_dir=model_dir,
             files=[f.name for f in model_files])

    json_file = next((f for f in model_files if f.name.endswith(".json")), None)
    joblib_file = next((f for f in model_files if f.name.endswith(".joblib")), None)

    if json_file:
        import xgboost as xgb
        model = xgb.XGBClassifier()
        model.load_model(str(json_file))
        return {"type": "xgboost", "model": model}

    if joblib_file:
        import joblib
        return {"type": "sklearn", "model": joblib.load(joblib_file)}

    raise RuntimeError(f"No model file found in {model_dir}")


def input_fn(request_body: str | bytes, content_type: str) -> dict:
    """Parse request. Expects JSON: {"entity_rows": [{"user_id": "U1"}, ...]}."""
    if content_type != "application/json":
        raise ValueError(f"Unsupported content type: {content_type}")

    if isinstance(request_body, bytes):
        request_body = request_body.decode("utf-8")
    return json.loads(request_body)


def predict_fn(data: dict, model_container: dict) -> dict:
    """Fetch online features, then predict."""
    entity_rows = data.get("entity_rows", [])
    if not entity_rows:
        return {"predictions": [], "error": "no entity_rows provided"}

    lookup = _get_online_lookup()
    feature_list = _get_feature_list()

    feature_dict = lookup.get_online_features(
        features=feature_list,
        entity_rows=entity_rows,
        full_feature_names=True,
    )

    # Convert Feast's column-oriented dict to row-oriented array
    entity_keys = set()
    for row in entity_rows:
        entity_keys.update(row.keys())

    feature_matrix = []
    for i in range(len(entity_rows)):
        row_features = []
        for feat in feature_list:
            feat_name = feat.split(":")[-1]
            values = feature_dict.get(feat_name, [None] * len(entity_rows))
            row_features.append(values[i] if i < len(values) else None)
        feature_matrix.append(row_features)

    model = model_container["model"]
    if model_container["type"] == "xgboost":
        import numpy as np
        X = np.array(feature_matrix, dtype=float)
        probs = model.predict_proba(X)[:, 1].tolist()
    else:
        probs = model.predict_proba(feature_matrix)[:, 1].tolist()

    return {"predictions": probs}


def output_fn(prediction: dict, accept: str) -> str:
    """Serialize the response. Default to JSON."""
    if accept == "application/json" or accept == "*/*":
        return json.dumps(prediction)
    raise ValueError(f"Unsupported accept type: {accept}")
