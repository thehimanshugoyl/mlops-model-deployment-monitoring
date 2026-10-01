"""
Production FastAPI Model Serving Service with Real-time Prometheus Monitoring and Drift Detection.
"""

from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import joblib
import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from src.drift_detector import DriftDetector
from src.model import (
    FEATURE_NAMES,
    generate_synthetic_data,
    save_artifacts,
    train_model,
)
from src.monitoring import (
    BUFFER_SIZE,
    CONTENT_TYPE_LATEST,
    PREDICTION_ERRORS_TOTAL,
    PREDICTION_LATENCY,
    PREDICTION_PROBABILITY,
    PREDICTIONS_TOTAL,
    REQUESTS_TOTAL,
    get_metrics_payload,
    update_prometheus_drift_metrics,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ml_service")

# Directory paths
BASE_DIR = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = Path(os.getenv("MODEL_DIR", BASE_DIR / "artifacts"))
MODEL_PATH = ARTIFACTS_DIR / "model.joblib"
REF_DATA_PATH = ARTIFACTS_DIR / "reference_data.csv"
METADATA_PATH = ARTIFACTS_DIR / "model_metadata.json"

# Global runtime state
model_pipeline = None
drift_detector: Optional[DriftDetector] = None
model_metadata: Dict[str, Any] = {}
startup_time = time.time()


def load_or_initialize_model():
    """
    Loads saved model artifacts, or trains on-the-fly if artifacts are missing.
    """
    global model_pipeline, drift_detector, model_metadata

    if model_pipeline is not None and drift_detector is not None:
        return

    ref_df = None
    if not MODEL_PATH.exists() or not REF_DATA_PATH.exists():
        logger.warning(
            "Model artifacts not found in %s. Training baseline model...", ARTIFACTS_DIR
        )
        df = generate_synthetic_data(n_samples=5000, random_state=42)
        pipeline, metrics, X_train, _ = train_model(df)
        model_pipeline = pipeline
        ref_df = X_train
        model_metadata = {"model_version": "1.0.0", "features": FEATURE_NAMES}
        try:
            save_artifacts(pipeline, X_train, metrics, ARTIFACTS_DIR, version="1.0.0")
        except Exception as e:
            logger.warning("Could not persist model artifacts to disk: %s", e)

    if model_pipeline is None:
        logger.info("Loading model from %s", MODEL_PATH)
        model_pipeline = joblib.load(MODEL_PATH)
        ref_df = pd.read_csv(REF_DATA_PATH)

        if METADATA_PATH.exists():
            with open(METADATA_PATH, "r", encoding="utf-8") as f:
                model_metadata = json.load(f)
        else:
            model_metadata = {"model_version": "1.0.0", "features": FEATURE_NAMES}

    window_size = int(os.getenv("DRIFT_WINDOW_SIZE", "500"))
    min_samples = int(os.getenv("DRIFT_MIN_SAMPLES", "25"))

    drift_detector = DriftDetector(
        reference_df=ref_df,
        feature_names=FEATURE_NAMES,
        window_size=window_size,
        min_samples_to_evaluate=min_samples,
    )
    logger.info(
        "Model and DriftDetector initialized successfully. Buffer maxlen=%d",
        window_size,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_or_initialize_model()
    yield


app = FastAPI(
    title="MLOps Credit Default Risk Predictor",
    description="Production ML Model API with Prometheus Metrics and Real-time Drift Detection",
    version="1.0.0",
    lifespan=lifespan,
)


class LoanApplication(BaseModel):
    age: int = Field(
        ...,
        ge=18,
        le=100,
        json_schema_extra={"example": 35},
        description="Applicant age in years",
    )
    annual_income: float = Field(
        ...,
        gt=0,
        json_schema_extra={"example": 75000.0},
        description="Annual gross income in USD",
    )
    credit_score: int = Field(
        ...,
        ge=300,
        le=850,
        json_schema_extra={"example": 710},
        description="FICO/Bureau credit score",
    )
    loan_amount: float = Field(
        ...,
        gt=0,
        json_schema_extra={"example": 18000.0},
        description="Requested loan amount in USD",
    )
    loan_tenure_months: int = Field(
        ...,
        ge=6,
        le=120,
        json_schema_extra={"example": 36},
        description="Loan term in months",
    )
    debt_to_income_ratio: float = Field(
        ...,
        ge=0.0,
        le=2.0,
        json_schema_extra={"example": 0.28},
        description="Debt to income ratio (0-2)",
    )
    employment_years: float = Field(
        ...,
        ge=0.0,
        le=60.0,
        json_schema_extra={"example": 6.5},
        description="Years in continuous employment",
    )
    has_prior_default: int = Field(
        ...,
        ge=0,
        le=1,
        json_schema_extra={"example": 0},
        description="1 if applicant defaulted before, else 0",
    )


class LoanApplicationBatch(BaseModel):
    applications: List[LoanApplication]


class PredictionResult(BaseModel):
    prediction: int = Field(
        ..., description="0 = No Default (Approved), 1 = Default (High Risk)"
    )
    default_probability: float = Field(
        ..., description="Estimated probability of default"
    )
    risk_level: str = Field(..., description="Low, Medium, or High risk tier")
    model_version: str


class PredictionResponse(BaseModel):
    status: str
    results: List[PredictionResult]
    latency_ms: float


def ensure_model_loaded():
    """
    Ensures model and drift detector are loaded in memory (especially for serverless execution).
    """
    if model_pipeline is None or drift_detector is None:
        load_or_initialize_model()


@app.middleware("http")
async def monitor_requests(request: Request, call_next):
    start_t = time.time()
    response = None
    try:
        response = await call_next(request)
        status_code = str(response.status_code)
    except Exception as exc:
        status_code = "500"
        raise exc
    finally:
        REQUESTS_TOTAL.labels(
            endpoint=request.url.path,
            method=request.method,
            status=status_code,
        ).inc()
    return response


@app.get("/", tags=["General"])
def root():
    return {
        "service": "MLOps Model Deployment & Drift Monitoring Service",
        "model_version": model_metadata.get("model_version", "1.0.0"),
        "status": "healthy",
        "docs_url": "/docs",
        "metrics_url": "/metrics",
        "drift_url": "/drift",
    }


@app.get("/api/docs", include_in_schema=False)
def api_docs_redirect():
    return RedirectResponse(url="/docs")


@app.get("/api/openapi.json", include_in_schema=False)
def api_openapi_redirect():
    return RedirectResponse(url="/openapi.json")


@app.get("/health", tags=["Health"])
@app.get("/api/health", include_in_schema=False)
def health():
    """
    Readiness and health inspection endpoint.
    """
    ensure_model_loaded()
    if model_pipeline is None or drift_detector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Model not loaded"
        )

    buf_size = drift_detector.get_buffer_size()
    BUFFER_SIZE.set(buf_size)

    return {
        "status": "healthy",
        "uptime_seconds": round(time.time() - startup_time, 1),
        "model_loaded": True,
        "model_version": model_metadata.get("model_version", "1.0.0"),
        "buffer_size": buf_size,
        "metrics": model_metadata.get("metrics", {}),
    }


@app.get("/live", tags=["Health"])
@app.get("/api/live", include_in_schema=False)
def liveness():
    """
    Kubernetes Liveness Probe.
    """
    return {"status": "alive"}


@app.get("/metrics", tags=["Monitoring"])
@app.get("/api/metrics", include_in_schema=False)
def metrics():
    """
    Prometheus scrape endpoint.
    """
    ensure_model_loaded()
    if drift_detector is not None:
        BUFFER_SIZE.set(drift_detector.get_buffer_size())
    return Response(content=get_metrics_payload(), media_type=CONTENT_TYPE_LATEST)


def run_drift_background_check():
    """
    Runs drift detection in background and updates Prometheus gauges.
    """
    try:
        if drift_detector is not None:
            report = drift_detector.evaluate_drift()
            if report.get("status") == "evaluated":
                update_prometheus_drift_metrics(report)
    except Exception as e:
        logger.error("Error in background drift evaluation: %s", e)


@app.post("/predict", response_model=PredictionResponse, tags=["Inference"])
@app.post("/api/predict", response_model=PredictionResponse, include_in_schema=False)
def predict(
    application: LoanApplication,
    background_tasks: BackgroundTasks,
):
    """
    Predict loan default risk for a single applicant and buffer feature data for drift detection.
    """
    return predict_batch(
        LoanApplicationBatch(applications=[application]), background_tasks
    )


@app.post("/predict/batch", response_model=PredictionResponse, tags=["Inference"])
@app.post(
    "/api/predict/batch", response_model=PredictionResponse, include_in_schema=False
)
def predict_batch(
    batch: LoanApplicationBatch,
    background_tasks: BackgroundTasks,
):
    """
    Batch prediction endpoint.
    """
    ensure_model_loaded()
    if model_pipeline is None or drift_detector is None:
        PREDICTION_ERRORS_TOTAL.labels(error_type="model_unloaded").inc()
        raise HTTPException(status_code=503, detail="Model not initialized")

    if not batch.applications:
        PREDICTION_ERRORS_TOTAL.labels(error_type="empty_batch").inc()
        raise HTTPException(status_code=400, detail="Batch applications list is empty")

    start_t = time.time()
    version = model_metadata.get("model_version", "1.0.0")

    data = [app_item.model_dump() for app_item in batch.applications]
    df = pd.DataFrame(data)[FEATURE_NAMES]

    try:
        preds = model_pipeline.predict(df)
        probs = model_pipeline.predict_proba(df)[:, 1]
    except Exception as e:
        PREDICTION_ERRORS_TOTAL.labels(error_type="inference_failed").inc()
        logger.error("Inference failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Inference error: {str(e)}")

    duration = time.time() - start_t
    PREDICTION_LATENCY.labels(model_version=version).observe(duration)

    results = []
    for pred, prob in zip(preds, probs):
        p_val = float(prob)
        p_class = int(pred)

        PREDICTIONS_TOTAL.labels(
            model_version=version,
            predicted_class="default" if p_class == 1 else "no_default",
        ).inc()
        PREDICTION_PROBABILITY.labels(model_version=version).observe(p_val)

        if p_val < 0.35:
            risk = "Low"
        elif p_val < 0.65:
            risk = "Medium"
        else:
            risk = "High"

        results.append(
            PredictionResult(
                prediction=p_class,
                default_probability=round(p_val, 4),
                risk_level=risk,
                model_version=version,
            )
        )

    # Record into drift detector
    drift_detector.record_batch_features(data)
    BUFFER_SIZE.set(drift_detector.get_buffer_size())

    # Queue drift assessment in background
    background_tasks.add_task(run_drift_background_check)

    return PredictionResponse(
        status="success",
        results=results,
        latency_ms=round(duration * 1000, 2),
    )


@app.get("/drift", tags=["Drift Monitoring"])
@app.get("/api/drift", include_in_schema=False)
def get_drift():
    """
    Evaluates statistical drift against baseline reference data and updates Prometheus gauges.
    """
    ensure_model_loaded()
    if drift_detector is None:
        raise HTTPException(status_code=503, detail="Drift detector not initialized")

    report = drift_detector.evaluate_drift()
    if report.get("status") == "evaluated":
        update_prometheus_drift_metrics(report)

    return report


@app.post("/drift/reset", tags=["Drift Monitoring"])
@app.post("/api/drift/reset", include_in_schema=False)
def reset_drift_buffer():
    """
    Clears the production drift buffer.
    """
    ensure_model_loaded()
    if drift_detector is not None:
        drift_detector.reset_buffer()
        BUFFER_SIZE.set(0)
    return {"status": "buffer_cleared"}
