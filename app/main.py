from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.responses import Response as FastAPIResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response
from starlette.types import Scope

from app.api import agent, ask, auth, documents, evaluation, health, search, system
from app.auth import RequestGateMiddleware, RequireReader, warn_if_auth_disabled
from app.config import get_settings
from app.db import get_engine, init_db
from app.observability import RequestContextMiddleware, configure_logging

STATIC_DIR = Path(__file__).parent / "static"

# The UI renders text from uploaded files and LLM output, so it gets a strict policy: only our own
# scripts/styles/fonts, no inline script or style, no framing, no plugins. Applied to /ui only so
# the Swagger page at /docs (which loads assets from a CDN) is unaffected.
UI_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class UIFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers.update(UI_HEADERS)
        return response


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    warn_if_auth_disabled(settings)
    init_db(get_engine())
    yield


app = FastAPI(title="Project Intelligence RAG", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(system.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(ask.router)
app.include_router(evaluation.router)
app.include_router(agent.router)
# The LAST one added is the outermost. Request context wraps everything, so a request the gate
# rejects still gets a request id, a log line and a metric; the gate runs before any body is read.
app.add_middleware(RequestGateMiddleware)
app.add_middleware(RequestContextMiddleware)
app.mount("/ui", UIFiles(directory=STATIC_DIR, html=True), name="ui")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/ui/")


@app.get("/metrics", include_in_schema=False, dependencies=[RequireReader])
def metrics_endpoint() -> FastAPIResponse:
    """Prometheus exposition. Unauthenticated like the rest of the API; see docs/deployment.md."""
    if not get_settings().metrics_enabled:
        return FastAPIResponse(status_code=404)
    return FastAPIResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
