"""
Integration tests for FastAPI endpoints, Prometheus metrics, and drift monitoring.
"""

import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app import app, load_or_initialize_model


@pytest.fixture(scope="module")
def client():
    load_or_initialize_model()
    with TestClient(app) as test_client:
        yield test_client


def test_root_endpoint(client):
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "model_version" in data


def test_health_and_liveness(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["model_loaded"] is True

    res_live = client.get("/live")
    assert res_live.status_code == 200
    assert res_live.json() == {"status": "alive"}


def test_metrics_endpoint(client):
    res = client.get("/metrics")
    assert res.status_code == 200
    content = res.text
    assert "ml_requests_total" in content
    assert "ml_production_buffer_size" in content


def test_single_prediction_valid(client):
    payload = {
        "age": 32,
        "annual_income": 82000.0,
        "credit_score": 720,
        "loan_amount": 15000.0,
        "loan_tenure_months": 36,
        "debt_to_income_ratio": 0.22,
        "employment_years": 5.0,
        "has_prior_default": 0,
    }
    res = client.post("/predict", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert len(data["results"]) == 1
    assert data["results"][0]["prediction"] in [0, 1]
    assert 0.0 <= data["results"][0]["default_probability"] <= 1.0
    assert data["results"][0]["risk_level"] in ["Low", "Medium", "High"]


def test_batch_prediction_and_drift_flow(client):
    # Reset buffer first
    client.post("/drift/reset")

    payloads = [
        {
            "age": 30 + i % 10,
            "annual_income": 60000.0 + i * 100,
            "credit_score": 680,
            "loan_amount": 20000.0,
            "loan_tenure_months": 36,
            "debt_to_income_ratio": 0.30,
            "employment_years": 4.0,
            "has_prior_default": 0,
        }
        for i in range(30)
    ]
    res = client.post("/predict/batch", json={"applications": payloads})
    assert res.status_code == 200
    assert len(res.json()["results"]) == 30

    # Test drift evaluation endpoint
    drift_res = client.get("/drift")
    assert drift_res.status_code == 200
    report = drift_res.json()
    assert report["status"] == "evaluated"
    assert report["sample_count"] >= 30
    assert "features" in report

    # Verify metrics reflect the buffer
    metrics_res = client.get("/metrics")
    assert "ml_predictions_total" in metrics_res.text


def test_invalid_prediction_payload(client):
    # Missing required field or invalid credit score (e.g. 1000 is > 850)
    invalid_payload = {
        "age": 32,
        "annual_income": 82000.0,
        "credit_score": 950,  # Invalid
        "loan_amount": 15000.0,
        "loan_tenure_months": 36,
        "debt_to_income_ratio": 0.22,
        "employment_years": 5.0,
        "has_prior_default": 0,
    }
    res = client.post("/predict", json=invalid_payload)
    assert res.status_code == 422
