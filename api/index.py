import json
import logging
from pathlib import Path
import sys
from fastapi import BackgroundTasks, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from starlette.responses import JSONResponse

# Add project root to sys.path so modules in src/ and artifacts/ are discovered
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app import (  # noqa: E402
    app,
    health,
    liveness,
    metrics,
    get_drift,
    reset_drift_buffer,
    predict,
    predict_batch,
    root,
    load_or_initialize_model,
    LoanApplication,
    LoanApplicationBatch,
)

logger = logging.getLogger("vercel_entrypoint")

# Initialize model and drift detector at cold start
try:
    load_or_initialize_model()
except Exception as e:
    logger.warning("Cold start model load warning: %s", e)


def resolve_requested_path(request: Request) -> str:
    """
    Resolves the intended client path whether rewritten via _vercel_path query param,
    x-matched-path header, or raw request path.
    """
    # 1. Query parameter _vercel_path (highest precision from vercel.json)
    vp = request.query_params.get("_vercel_path")
    if vp:
        return vp.split("?")[0]

    # 2. Vercel CDN x-matched-path header
    mp = request.headers.get("x-matched-path")
    if mp:
        cleaned = mp.split("?")[0]
        if not cleaned.endswith(".py") and not cleaned.startswith("/api/index"):
            return cleaned

    # 3. Path from request url
    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/index"):
        return path[4:]  # strip /api

    return path


@app.get("/api/index.py", include_in_schema=False)
@app.get("/api/index", include_in_schema=False)
@app.get("/api", include_in_schema=False)
async def vercel_entrypoint_get(request: Request):
    """
    Catches Vercel serverless function entrypoint GET requests and dispatches to
    the appropriate endpoint handler based on rewritten path.
    """
    target = resolve_requested_path(request)

    if target in ("/docs", "/api/docs"):
        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title="MLOps Credit Default Risk Predictor - Swagger UI",
        )

    if target in ("/openapi.json", "/api/openapi.json"):
        return JSONResponse(
            content=get_openapi(
                title=app.title,
                version=app.version,
                openapi_version=app.openapi_version,
                description=app.description,
                routes=app.routes,
            )
        )

    if target in ("/metrics", "/api/metrics"):
        return metrics()

    if target in ("/health", "/api/health"):
        return health()

    if target in ("/live", "/api/live"):
        return liveness()

    if target in ("/drift", "/api/drift"):
        return get_drift()

    return root()


@app.post("/api/index.py", include_in_schema=False)
@app.post("/api/index", include_in_schema=False)
@app.post("/api", include_in_schema=False)
async def vercel_entrypoint_post(request: Request, background_tasks: BackgroundTasks):
    """
    Catches Vercel serverless function entrypoint POST requests and dispatches
    to inference or drift management.
    """
    target = resolve_requested_path(request)

    if target in ("/drift/reset", "/api/drift/reset"):
        return reset_drift_buffer()

    body_bytes = await request.body()
    if not body_bytes:
        return JSONResponse(status_code=400, content={"detail": "Empty body"})

    try:
        data = json.loads(body_bytes.decode("utf-8"))
    except Exception as e:
        return JSONResponse(
            status_code=400, content={"detail": f"Invalid JSON payload: {e}"}
        )

    if "applications" in data:
        batch = LoanApplicationBatch(**data)
        return predict_batch(batch, background_tasks)

    app_single = LoanApplication(**data)
    return predict(app_single, background_tasks)
