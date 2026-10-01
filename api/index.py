import logging
from pathlib import Path
import sys
import urllib.parse
from starlette.types import ASGIApp, Receive, Scope, Send

# Add project root to sys.path so modules in src/ and artifacts/ are discovered
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app import app, load_or_initialize_model

logger = logging.getLogger("vercel_entrypoint")

# Initialize model and drift detector at serverless startup
try:
    load_or_initialize_model()
except Exception as e:
    logger.warning("Could not initialize model at import time: %s", e)


class VercelPathNormalizerMiddleware:
    """
    Normalizes ASGI scope path on Vercel so that rewrites correctly map
    to FastAPI routes including /docs, /metrics, /health, /predict, etc.
    """

    def __init__(self, asgi_app: ASGIApp):
        self.app = asgi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            # 1. Check for query parameter _vercel_path (deterministic rewrite routing)
            qs = scope.get("query_string", b"").decode("utf-8")
            if "_vercel_path=" in qs:
                params = urllib.parse.parse_qs(qs)
                if "_vercel_path" in params and params["_vercel_path"]:
                    resolved_path = params["_vercel_path"][0]
                    scope["path"] = resolved_path
                    scope["raw_path"] = resolved_path.encode("utf-8")
                    # Clean _vercel_path out of query string
                    filtered_params = {
                        k: v for k, v in params.items() if k != "_vercel_path"
                    }
                    new_qs = urllib.parse.urlencode(filtered_params, doseq=True)
                    scope["query_string"] = new_qs.encode("utf-8")

            # 2. Check x-matched-path header from Vercel CDN
            headers = dict(scope.get("headers", []))
            matched_path = headers.get(b"x-matched-path")
            current_path = scope.get("path", "")
            if matched_path and current_path in (
                "/api/index.py",
                "/api/index",
                "/api/index/",
                "",
            ):
                decoded = matched_path.decode("utf-8").split("?")[0]
                if not decoded.endswith(".py") and not decoded.startswith("/api/index"):
                    scope["path"] = decoded
                    scope["raw_path"] = decoded.encode("utf-8")

            # 3. Strip /api/ prefix if present so /api/docs -> /docs, /api/metrics -> /metrics
            p = scope.get("path", "")
            if p.startswith("/api/") and not p.startswith("/api/index"):
                stripped = p[4:]  # remove '/api'
                scope["path"] = stripped
                scope["raw_path"] = stripped.encode("utf-8")

        await self.app(scope, receive, send)


app.add_middleware(VercelPathNormalizerMiddleware)
