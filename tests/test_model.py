"""
Unit tests for Model training and evaluation.
"""

import sys
from pathlib import Path
import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model import FEATURE_NAMES, TARGET_NAME, generate_synthetic_data, train_model


def test_generate_synthetic_data():
    df = generate_synthetic_data(n_samples=500, random_state=42)
    assert len(df) == 500
    for feat in FEATURE_NAMES:
        assert feat in df.columns
    assert TARGET_NAME in df.columns
    assert set(df[TARGET_NAME].unique()).issubset({0, 1})


def test_train_model():
    df = generate_synthetic_data(n_samples=1000, random_state=42)
    pipeline, metrics, X_train, X_test = train_model(df)

    assert "roc_auc" in metrics
    assert "accuracy" in metrics
    assert metrics["roc_auc"] > 0.70
    assert metrics["accuracy"] > 0.70

    # Test single row inference
    sample = X_test.iloc[[0]]
    pred = pipeline.predict(sample)
    proba = pipeline.predict_proba(sample)

    assert pred[0] in [0, 1]
    assert proba.shape == (1, 2)
    assert np.isclose(proba.sum(), 1.0)
