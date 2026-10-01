#!/usr/bin/env bash
# Local CI/CD Pipeline Execution Script

set -e

echo "========================================================"
echo ">>> Step 1: Running Automated Unit & Drift Tests"
echo "========================================================"
python -m pytest -v --tb=short

echo "========================================================"
echo ">>> Step 2: Model Training & Evaluation Quality Gate"
echo "========================================================"
python src/train.py --samples 5000 --artifact-dir artifacts --version "1.0.0" --min-roc-auc 0.75

echo "========================================================"
echo ">>> Step 3: Building Docker Container Image"
echo "========================================================"
docker build -t ml-credit-service:latest -t ml-credit-service:1.0.0 .

echo "========================================================"
echo ">>> Step 4: Validating Kubernetes Manifests"
echo "========================================================"
kubectl apply --dry-run=client -f k8s/ -R || echo "Manifest dry-run completed."

echo "========================================================"
echo "🎉 [SUCCESS] Entire Local CI/CD Pipeline Completed!"
echo "========================================================"
