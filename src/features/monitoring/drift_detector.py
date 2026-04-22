"""Drift detection helpers.

Two approaches:
  1. SageMaker Model Monitor (scheduled job, creates constraint violation reports)
  2. Custom drift detector (pure Python, for Databricks Lakehouse Monitoring)

The custom path uses Population Stability Index (PSI) and KS-divergence between
the live window and the training baseline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from features.utils.logging_config import get_logger

log = get_logger(__name__, component="monitoring.drift_detector")


@dataclass
class DriftResult:
    feature_name: str
    psi: float
    ks_stat: float
    ks_pvalue: float
    drift_detected: bool
    message: str = ""


@dataclass
class DriftReport:
    results: list[DriftResult] = field(default_factory=list)

    @property
    def any_drift(self) -> bool:
        return any(r.drift_detected for r in self.results)

    @property
    def drifted_features(self) -> list[str]:
        return [r.feature_name for r in self.results if r.drift_detected]

    def to_dict(self) -> dict:
        return {
            "any_drift": self.any_drift,
            "drifted_features": self.drifted_features,
            "results": [
                {
                    "feature": r.feature_name,
                    "psi": r.psi,
                    "ks_stat": r.ks_stat,
                    "ks_pvalue": r.ks_pvalue,
                    "drift_detected": r.drift_detected,
                    "message": r.message,
                }
                for r in self.results
            ],
        }


def compute_psi(
    baseline: np.ndarray,
    current: np.ndarray,
    bins: int = 10,
) -> float:
    """Population Stability Index.

    Bucket values, compare proportions. Rule of thumb:
      - PSI < 0.1  -> no significant drift
      - 0.1 <= PSI < 0.25 -> moderate drift
      - PSI >= 0.25 -> major drift (investigate + potentially retrain)
    """
    baseline = np.asarray(baseline, dtype=float)
    current = np.asarray(current, dtype=float)
    if len(baseline) == 0 or len(current) == 0:
        return 0.0

    # Use baseline's quantiles for bucket edges
    edges = np.unique(np.quantile(baseline, np.linspace(0, 1, bins + 1)))
    if len(edges) < 2:
        return 0.0

    eps = 1e-6
    b_counts, _ = np.histogram(baseline, bins=edges)
    c_counts, _ = np.histogram(current, bins=edges)

    b_frac = (b_counts / b_counts.sum()) + eps
    c_frac = (c_counts / c_counts.sum()) + eps
    return float(np.sum((c_frac - b_frac) * np.log(c_frac / b_frac)))


def compute_ks(baseline: np.ndarray, current: np.ndarray) -> tuple[float, float]:
    """Kolmogorov-Smirnov two-sample test. Returns (stat, p-value)."""
    from scipy import stats
    if len(baseline) == 0 or len(current) == 0:
        return 0.0, 1.0
    stat, pvalue = stats.ks_2samp(baseline, current)
    return float(stat), float(pvalue)


def detect_drift(
    baseline_df: pd.DataFrame,
    current_df: pd.DataFrame,
    feature_columns: list[str] | None = None,
    psi_threshold: float = 0.25,
    ks_pvalue_threshold: float = 0.01,
) -> DriftReport:
    """Run PSI + KS tests on each feature. Returns a drift report."""
    if feature_columns is None:
        # Pick numeric columns present in both
        numeric_cols = [
            c for c in baseline_df.columns
            if pd.api.types.is_numeric_dtype(baseline_df[c])
            and c in current_df.columns
            and pd.api.types.is_numeric_dtype(current_df[c])
        ]
        feature_columns = numeric_cols

    report = DriftReport()
    for col in feature_columns:
        b = baseline_df[col].dropna().to_numpy()
        c = current_df[col].dropna().to_numpy()
        psi = compute_psi(b, c)
        ks_stat, ks_pvalue = compute_ks(b, c)

        psi_breach = psi >= psi_threshold
        ks_breach = ks_pvalue < ks_pvalue_threshold
        drift = psi_breach or ks_breach

        msg_parts = []
        if psi_breach:
            msg_parts.append(f"PSI={psi:.3f} >= {psi_threshold}")
        if ks_breach:
            msg_parts.append(f"KS p-value={ks_pvalue:.4f} < {ks_pvalue_threshold}")

        result = DriftResult(
            feature_name=col,
            psi=psi,
            ks_stat=ks_stat,
            ks_pvalue=ks_pvalue,
            drift_detected=drift,
            message="; ".join(msg_parts),
        )
        report.results.append(result)

        if drift:
            log.warning(
                "drift_detected",
                feature=col,
                psi=psi,
                ks_stat=ks_stat,
                ks_pvalue=ks_pvalue,
            )

    return report
