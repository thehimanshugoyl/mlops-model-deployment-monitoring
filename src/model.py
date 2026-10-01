"""
Machine Learning Model Training, Evaluation, and Pipeline Definition.
Loan Default / Credit Risk Classification.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Tuple, Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

FEATURE_NAMES = [
    "age",
    "annual_income",
    "credit_score",
    "loan_amount",
    "loan_tenure_months",
    "debt_to_income_ratio",
    "employment_years",
    "has_prior_default",
]

TARGET_NAME = "loan_default"


def generate_synthetic_data(n_samples: int = 5000, random_state: int = 42) -> pd.DataFrame:
    """
    Generate a realistic credit default dataset with known distributions.
    This serves as our baseline/training dataset.
    """
    rng = np.random.RandomState(random_state)

    age = rng.randint(21, 65, size=n_samples)
    annual_income = np.clip(rng.normal(65000, 22000, size=n_samples), 18000, 250000)
    credit_score = np.clip(rng.normal(680, 75, size=n_samples), 350, 850).astype(int)
    loan_amount = np.clip(rng.normal(20000, 9000, size=n_samples), 2000, 60000)
    loan_tenure_months = rng.choice([12, 24, 36, 48, 60], size=n_samples, p=[0.1, 0.2, 0.4, 0.2, 0.1])
    debt_to_income_ratio = np.clip(rng.beta(2, 5, size=n_samples) * 0.7, 0.05, 0.85)
    employment_years = np.clip(rng.exponential(5, size=n_samples), 0, 35)
    has_prior_default = rng.binomial(1, 0.12, size=n_samples)

    # Latent logit for default probability based on realistic financial factors
    z = (
        -1.5
        - 0.000025 * (annual_income - 65000)
        - 0.015 * (credit_score - 650)
        + 0.00004 * (loan_amount - 20000)
        + 3.5 * (debt_to_income_ratio - 0.3)
        - 0.08 * employment_years
        + 1.8 * has_prior_default
        + 0.015 * (loan_tenure_months - 36)
        + rng.normal(0, 0.5, size=n_samples)
    )

    prob = 1.0 / (1.0 + np.exp(-z))
    loan_default = (prob > 0.5).astype(int)

    df = pd.DataFrame(
        {
            "age": age,
            "annual_income": np.round(annual_income, 2),
            "credit_score": credit_score,
            "loan_amount": np.round(loan_amount, 2),
            "loan_tenure_months": loan_tenure_months,
            "debt_to_income_ratio": np.round(debt_to_income_ratio, 4),
            "employment_years": np.round(employment_years, 1),
            "has_prior_default": has_prior_default,
            TARGET_NAME: loan_default,
        }
    )

    return df


def build_pipeline() -> Pipeline:
    """
    Constructs scikit-learn training pipeline.
    """
    return Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "classifier",
                HistGradientBoostingClassifier(
                    max_iter=120,
                    learning_rate=0.08,
                    max_leaf_nodes=31,
                    min_samples_leaf=20,
                    random_state=42,
                ),
            ),
        ]
    )


def train_model(
    df: pd.DataFrame,
) -> Tuple[Pipeline, Dict[str, float], pd.DataFrame, pd.DataFrame]:
    """
    Trains and evaluates the model pipeline.
    Returns:
        pipeline: Trained scikit-learn Pipeline
        metrics: Dictionary of test metrics
        X_train: Training features
        X_test: Test features
    """
    X = df[FEATURE_NAMES]
    y = df[TARGET_NAME]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )

    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)
    y_prob = pipeline.predict_proba(X_test)[:, 1]

    metrics = {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1_score": float(f1_score(y_test, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, y_prob)),
    }

    return pipeline, metrics, X_train, X_test


def save_artifacts(
    pipeline: Pipeline,
    reference_data: pd.DataFrame,
    metrics: Dict[str, float],
    artifact_dir: Path,
    version: str = "1.0.0",
) -> None:
    """
    Saves the trained pipeline, baseline reference dataset, and metadata.
    """
    artifact_dir.mkdir(parents=True, exist_ok=True)

    model_path = artifact_dir / "model.joblib"
    ref_data_path = artifact_dir / "reference_data.csv"
    meta_path = artifact_dir / "model_metadata.json"

    joblib.dump(pipeline, model_path)
    reference_data.to_csv(ref_data_path, index=False)

    metadata: Dict[str, Any] = {
        "model_name": "loan_default_risk_predictor",
        "model_version": version,
        "features": FEATURE_NAMES,
        "target": TARGET_NAME,
        "metrics": metrics,
        "reference_samples": len(reference_data),
    }

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    logger.info("Saved model artifacts to %s", artifact_dir)
