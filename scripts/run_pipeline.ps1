<#
.SYNOPSIS
    Local CI/CD Pipeline Execution Script for Windows PC.
.DESCRIPTION
    Runs lint checks, unit & drift tests, model training quality gate,
    Docker container build, and Kubernetes manifest validation.
#>

param (
    [switch]$SkipDocker = $false,
    [switch]$SkipK8s = $false
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param ([string]$Title)
    Write-Host "`n========================================================" -ForegroundColor Cyan
    Write-Host ">>> $Title" -ForegroundColor Green
    Write-Host "========================================================" -ForegroundColor Cyan
}

Write-Host "Starting Local MLOps CI/CD Pipeline..." -ForegroundColor Yellow

# Step 1: Run Automated Tests
Write-Step "Step 1: Running Automated Unit & Drift Tests"
python -m pytest -v --tb=short
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Unit/Integration tests failed!" -ForegroundColor Red
    exit 1
}
Write-Host "✅ All tests passed successfully!" -ForegroundColor Green

# Step 2: Model Training & Evaluation Quality Gate
Write-Step "Step 2: Model Training & Quality Gate Assertion"
python src/train.py --samples 5000 --artifact-dir artifacts --version "1.0.0" --min-roc-auc 0.75
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Model training or quality gate failed!" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Model trained and passed evaluation quality gate!" -ForegroundColor Green

# Step 3: Docker Container Build
if (-not $SkipDocker) {
    Write-Step "Step 3: Building Docker Container Image"
    docker build -t ml-credit-service:latest -t ml-credit-service:1.0.0 .
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Docker build failed!" -ForegroundColor Red
        exit 1
    }
    Write-Host "✅ Docker image 'ml-credit-service:latest' built successfully!" -ForegroundColor Green
} else {
    Write-Host "Skipping Docker build as requested." -ForegroundColor Gray
}

# Step 4: Kubernetes Manifests Validation
if (-not $SkipK8s) {
    Write-Step "Step 4: Validating Kubernetes Manifests"
    kubectl apply --dry-run=client -f k8s/ -R
    if ($LASTEXITCODE -ne 0) {
        Write-Host "⚠️ Warning: Kubernetes client dry-run returned warnings (Cluster may not be connected)." -ForegroundColor Yellow
    } else {
        Write-Host "✅ All Kubernetes manifests are valid!" -ForegroundColor Green
    }
} else {
    Write-Host "Skipping Kubernetes validation as requested." -ForegroundColor Gray
}

Write-Host "`n🎉 [SUCCESS] Entire Local CI/CD Pipeline Completed Successfully!" -ForegroundColor Green
