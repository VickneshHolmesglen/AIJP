"""Structured logging and per-request context.

- One JSON log line per request (method, route, status, duration, request id). Never the query
  string or body: those can contain questions and document text.
- A request id on every log line and response (`X-Request-ID`). An incoming id is trusted only if it
  has a safe shape; otherwise a fresh one is generated, so a client cannot inject arbitrary text
  into logs.
- Standard library only: no logging framework dependency.
"""

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Literal

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import metrics

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
# Attributes every LogRecord has; anything else was passed via `extra=` and is logged as a field.
_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}
# uvicorn passes a colour-coded copy of the message in this extra; it is noise in JSON.
_NOISE = {"color_message"}

log = logging.getLogger("app.request")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        payload.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD | _NOISE})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str, fmt: Literal["json", "plain"]) -> None:
    """Route application logs to stdout. Called at startup, never at import (tests stay quiet)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if fmt == "json"
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


def _request_id(scope: Scope) -> str:
    headers: list[tuple[bytes, bytes]] = scope["headers"]
    for name, value in headers:
        if name == b"x-request-id":
            candidate = value.decode("latin-1")
            if _SAFE_REQUEST_ID.match(candidate):
                return candidate
    return uuid.uuid4().hex


class RequestContextMiddleware:
    """Pure ASGI middleware (not BaseHTTPMiddleware, which buffers responses and breaks contextvars
    across tasks): sets the request id, times the request, logs it and records HTTP metrics."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id(scope)
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500  # what we report if the app raises before sending a response

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append(
                    (b"x-request-id", request_id.encode("latin-1"))
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            duration = time.perf_counter() - started
            # The matched route *template* ("/documents/{document_id}"), never the raw path:
            # ids in labels would create unbounded metric cardinality.
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            method = scope["method"]
            metrics.HTTP_REQUESTS.labels(method, route, metrics.status_class(status)).inc()
            metrics.HTTP_DURATION.labels(method, route).observe(duration)
            actor = (scope.get("state") or {}).get("actor")  # set by the auth dependency
            log.info(
                "request",
                extra={
                    "actor": actor,
                    "method": method,
                    "route": route,
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": round(duration * 1000, 1),
                },
            )
            request_id_var.reset(token)
