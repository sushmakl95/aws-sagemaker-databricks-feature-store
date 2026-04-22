"""Unit tests for drift detection."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from features.monitoring.drift_detector import (
    compute_ks,
    compute_psi,
    detect_drift,
)

pytestmark = pytest.mark.unit


def test_psi_zero_when_distributions_identical():
    rng = np.random.default_rng(42)
    baseline = rng.normal(0, 1, 10_000)
    current = rng.normal(0, 1, 10_000)
    psi = compute_psi(baseline, current)
    assert psi < 0.05, f"PSI should be near 0 for same distribution, got {psi}"


def test_psi_large_when_distributions_shifted():
    rng = np.random.default_rng(42)
    baseline = rng.normal(0, 1, 10_000)
    current = rng.normal(3, 1, 10_000)  # mean shift
    psi = compute_psi(baseline, current)
    assert psi > 0.5, f"PSI should be large for shifted distribution, got {psi}"


def test_psi_handles_empty_arrays():
    psi = compute_psi(np.array([]), np.array([1, 2, 3]))
    assert psi == 0.0
    psi = compute_psi(np.array([1, 2, 3]), np.array([]))
    assert psi == 0.0


def test_ks_detects_shift():
    rng = np.random.default_rng(42)
    baseline = rng.normal(0, 1, 1000)
    current = rng.normal(2, 1, 1000)
    stat, pvalue = compute_ks(baseline, current)
    assert stat > 0.5
    assert pvalue < 0.01


def test_ks_no_shift_pvalue_high():
    rng = np.random.default_rng(42)
    baseline = rng.normal(0, 1, 1000)
    current = rng.normal(0, 1, 1000)
    _, pvalue = compute_ks(baseline, current)
    assert pvalue > 0.05


def test_detect_drift_identifies_drifted_feature():
    rng = np.random.default_rng(42)
    baseline = pd.DataFrame({
        "stable": rng.normal(0, 1, 5000),
        "shifted": rng.normal(0, 1, 5000),
    })
    current = pd.DataFrame({
        "stable": rng.normal(0, 1, 5000),
        "shifted": rng.normal(3, 1, 5000),
    })
    report = detect_drift(baseline, current, psi_threshold=0.25)
    assert report.any_drift
    assert "shifted" in report.drifted_features
    assert "stable" not in report.drifted_features


def test_drift_report_to_dict_structure():
    baseline = pd.DataFrame({"x": np.arange(1000)})
    current = pd.DataFrame({"x": np.arange(1000) + 500})
    report = detect_drift(baseline, current)
    data = report.to_dict()
    assert "any_drift" in data
    assert "drifted_features" in data
    assert "results" in data
    assert len(data["results"]) == 1
    assert data["results"][0]["feature"] == "x"
