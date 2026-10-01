"""
Training Script for MLOps Pipeline.
Can be executed standalone or as part of CI/CD training gate.
"""

import argparse
import logging
from pathlib import Path
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model import (
    FEATURE_NAMES,
    generate_synthetic_data,
    save_artifacts,
    train_model,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("trainer")


def main():
    parser = argparse.ArgumentParser(description="Train Loan Default ML Model")
    parser.add_argument(
        "--samples", type=int, default=6000, help="Number of training samples"
    )
    parser.add_argument(
        "--artifact-dir",
        type=str,
        default="artifacts",
        help="Path to output artifacts directory",
    )
    parser.add_argument(
        "--version", type=str, default="1.0.0", help="Model version string"
    )
    parser.add_argument(
        "--min-roc-auc",
        type=float,
        default=0.75,
        help="Minimum ROC-AUC threshold for CI/CD gate",
    )
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir).resolve()
    logger.info(
        "Generating %d synthetic records with known distributions...", args.samples
    )
    df = generate_synthetic_data(n_samples=args.samples, random_state=42)

    logger.info(
        "Training HistGradientBoosting pipeline on %d features: %s",
        len(FEATURE_NAMES),
        FEATURE_NAMES,
    )
    pipeline, metrics, X_train, X_test = train_model(df)

    logger.info("==========================================")
    logger.info("Model Training Results (Version %s):", args.version)
    for k, v in metrics.items():
        logger.info("  %s: %.4f", k.upper(), v)
    logger.info("==========================================")

    # CI/CD Quality Gate Assertion
    if metrics["roc_auc"] < args.min_roc_auc:
        logger.error(
            "Model failed quality gate! ROC-AUC %.4f is below minimum threshold %.4f",
            metrics["roc_auc"],
            args.min_roc_auc,
        )
        sys.exit(1)

    logger.info(
        "Model passed quality gate (ROC-AUC %.4f >= %.4f)",
        metrics["roc_auc"],
        args.min_roc_auc,
    )
    save_artifacts(pipeline, X_train, metrics, artifact_dir, version=args.version)
    logger.info("Artifacts saved successfully in: %s", artifact_dir)


if __name__ == "__main__":
    main()
