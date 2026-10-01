"""
Unit tests for Statistical Drift Detector and PSI Calculation.
"""

import sys
from pathlib import Path
import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.drift_detector import DriftDetector, calculate_psi
from src.model import FEATURE_NAMES, generate_synthetic_data


def test_calculate_psi_no_drift():
    rng = np.random.RandomState(42)
    ref = rng.normal(100, 15, size=1000)
    curr = rng.normal(100, 15, size=1000)

    psi = calculate_psi(ref, curr)
    assert psi < 0.1, f"Expected PSI < 0.1 for identical distributions, got {psi}"


def test_calculate_psi_significant_drift():
    rng = np.random.RandomState(42)
    ref = rng.normal(100, 15, size=1000)
    curr = rng.normal(140, 20, size=1000)  # Major distribution shift

    psi = calculate_psi(ref, curr)
    assert psi >= 0.2, f"Expected PSI >= 0.2 for shifted distributions, got {psi}"


def test_drift_detector_insufficient_samples():
    df = generate_synthetic_data(n_samples=500, random_state=42)
    detector = DriftDetector(reference_df=df, feature_names=FEATURE_NAMES, min_samples_to_evaluate=30)

    # Initially buffer is empty
    report = detector.evaluate_drift()
    assert report["status"] == "insufficient_data"
    assert report["dataset_drift_detected"] is False

    # Add 10 samples (below minimum of 30)
    sample_rows = df[FEATURE_NAMES].head(10).to_dict(orient="records")
    detector.record_batch_features(sample_rows)
    report = detector.evaluate_drift()
    assert report["status"] == "insufficient_data"


def test_drift_detector_detection_under_shift():
    df = generate_synthetic_data(n_samples=1000, random_state=42)
    detector = DriftDetector(
        reference_df=df,
        feature_names=FEATURE_NAMES,
        min_samples_to_evaluate=30,
        drift_share_threshold=0.30,
    )

    # Generate drifted samples (e.g. drastic shift in income and credit score)
    shifted_data = df[FEATURE_NAMES].head(50).copy()
    shifted_data["annual_income"] = shifted_data["annual_income"] * 4.0
    shifted_data["credit_score"] = 350
    shifted_data["debt_to_income_ratio"] = 0.90

    detector.record_batch_features(shifted_data.to_dict(orient="records"))
    report = detector.evaluate_drift()

    assert report["status"] == "evaluated"
    assert report["features"]["annual_income"]["drift_detected"] is True
    assert report["features"]["credit_score"]["drift_detected"] is True
    assert report["features"]["debt_to_income_ratio"]["drift_detected"] is True
    assert report["dataset_drift_detected"] is True
