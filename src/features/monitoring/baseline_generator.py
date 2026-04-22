"""Generate training-data baseline statistics + SageMaker Model Monitor constraints.

Run once at training time. The resulting JSON files feed into:
  - SageMaker Model Monitor (baseline_statistics + constraint_violations JSONs)
  - Our custom drift_detector (baseline dataframe for PSI/KS comparison)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from features.utils.logging_config import get_logger

log = get_logger(__name__, component="monitoring.baseline_generator")


@dataclass
class BaselineConfig:
    input_path: str
    """Path to training data (parquet / CSV / Delta)."""
    output_dir: str
    """Directory where baseline.json + constraints.json are written."""
    feature_columns: list[str] | None = None
    """Columns to include. If None, all numeric columns."""


def generate_baseline_statistics(
    df: pd.DataFrame,
    feature_columns: list[str] | None = None,
) -> dict:
    """Per-feature statistics for the training baseline.

    Format is compatible with SageMaker Model Monitor's statistics.json.
    """
    if feature_columns is None:
        feature_columns = [
            c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])
        ]

    features: list[dict] = []
    for col in feature_columns:
        s = df[col].dropna()
        if len(s) == 0:
            continue
        feat_stat: dict = {
            "name": col,
            "inferred_type": "Fractional" if pd.api.types.is_float_dtype(s) else "Integral",
            "numerical_statistics": {
                "common": {
                    "num_present": len(s),
                    "num_missing": int(df[col].isna().sum()),
                },
                "mean": float(s.mean()),
                "sum": float(s.sum()),
                "std_dev": float(s.std(ddof=0)),
                "min": float(s.min()),
                "max": float(s.max()),
                "distribution": {
                    "kll": {
                        "buckets": _build_buckets(s),
                        "sketch": {"parameters": {"c": 0.64, "k": 2048}},
                    },
                },
            },
        }
        features.append(feat_stat)

    return {
        "version": 0.0,
        "dataset": {"item_count": len(df)},
        "features": features,
    }


def _build_buckets(series: pd.Series, n_buckets: int = 10) -> list[dict]:
    quantiles = np.quantile(series, np.linspace(0, 1, n_buckets + 1))
    buckets: list[dict] = []
    for i in range(n_buckets):
        lo = float(quantiles[i])
        hi = float(quantiles[i + 1])
        if hi <= lo:
            continue
        count = int(((series >= lo) & (series < hi)).sum())
        buckets.append({
            "lower_bound": lo,
            "upper_bound": hi,
            "count": count,
            "global_lower_bound": float(quantiles[0]),
            "global_upper_bound": float(quantiles[-1]),
        })
    return buckets


def generate_constraints(stats: dict) -> dict:
    """Generate Model Monitor constraints.json from baseline statistics.

    Defaults:
      - Completeness: feature must be present in >= 95% of records
      - Num missing: no increase in missingness
    """
    feature_constraints: list[dict] = []
    for feat in stats.get("features", []):
        n_present = feat["numerical_statistics"]["common"]["num_present"]
        n_missing = feat["numerical_statistics"]["common"]["num_missing"]
        total = n_present + n_missing
        baseline_completeness = n_present / total if total > 0 else 1.0

        feature_constraints.append({
            "name": feat["name"],
            "inferred_type": feat["inferred_type"],
            "completeness": max(0.95, baseline_completeness - 0.05),
            "num_constraints": {
                "is_non_negative": bool(feat["numerical_statistics"]["min"] >= 0),
            },
        })

    return {
        "version": 0.0,
        "features": feature_constraints,
        "monitoring_config": {
            "evaluate_constraints": "Enabled",
            "emit_metrics": "Enabled",
            "distribution_constraints": {
                "perform_comparison": "Enabled",
                "comparison_threshold": 0.1,
                "comparison_method": "Robust",
            },
        },
    }


def run(config: BaselineConfig) -> dict:
    """End-to-end: read data, compute stats, write JSON files."""
    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(config.input_path) if config.input_path.endswith(".parquet") \
        else pd.read_csv(config.input_path)

    log.info("baseline_generating", n_rows=len(df), n_cols=df.shape[1])

    stats = generate_baseline_statistics(df, config.feature_columns)
    constraints = generate_constraints(stats)

    stats_path = out_dir / "statistics.json"
    constraints_path = out_dir / "constraints.json"
    stats_path.write_text(json.dumps(stats, indent=2))
    constraints_path.write_text(json.dumps(constraints, indent=2))

    # Also save baseline parquet for custom drift detector
    baseline_parquet = out_dir / "baseline.parquet"
    df.to_parquet(baseline_parquet, index=False)

    log.info(
        "baseline_generated",
        stats_path=str(stats_path),
        constraints_path=str(constraints_path),
        baseline_path=str(baseline_parquet),
    )
    return {
        "stats_path": str(stats_path),
        "constraints_path": str(constraints_path),
        "baseline_path": str(baseline_parquet),
    }
