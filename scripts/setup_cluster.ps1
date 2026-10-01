<#
.SYNOPSIS
    Kubernetes Cluster Setup and Deployment Script for Windows PC.
.DESCRIPTION
    Creates a local Kind cluster, builds the model Docker image, loads it into Kind,
    and applies all Kubernetes manifests (ML service, Prometheus, Grafana).
#>

param (
    [string]$ClusterName = "mlops-cluster"
)

$ErrorActionPreference = "Stop"

Write-Host ">>> Checking Kind cluster status..." -ForegroundColor Cyan
$existingClusters = kind get clusters 2>$null

if ($existingClusters -contains $ClusterName) {
    Write-Host "Kind cluster '$ClusterName' is already running." -ForegroundColor Green
} else {
    Write-Host "Creating Kind cluster '$ClusterName'..." -ForegroundColor Yellow
    kind create cluster --name $ClusterName
}

# Ensure image is built
Write-Host ">>> Building Docker image 'ml-credit-service:latest'..." -ForegroundColor Cyan
docker build -t ml-credit-service:latest .

# Load image into Kind cluster
Write-Host ">>> Loading Docker image into Kind cluster '$ClusterName'..." -ForegroundColor Cyan
kind load docker-image ml-credit-service:latest --name $ClusterName

# Deploy manifests in dependency order
Write-Host ">>> Deploying Kubernetes manifests..." -ForegroundColor Cyan
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/prometheus/
kubectl apply -f k8s/grafana/
kubectl apply -f k8s/ml-deployment.yaml
kubectl apply -f k8s/ml-service.yaml
kubectl apply -f k8s/ml-hpa.yaml

Write-Host "`n>>> Deployment complete! Checking pod status in namespace 'mlops'..." -ForegroundColor Green
kubectl get pods -n mlops

Write-Host "`nTo access services via port-forwarding, run:" -ForegroundColor Yellow
Write-Host "  ML Service:  kubectl port-forward svc/ml-service 8000:8000 -n mlops" -ForegroundColor Cyan
Write-Host "  Prometheus:  kubectl port-forward svc/prometheus-service 9090:9090 -n mlops" -ForegroundColor Cyan
Write-Host "  Grafana:     kubectl port-forward svc/grafana-service 3000:3000 -n mlops" -ForegroundColor Cyan
