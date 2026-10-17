# syntax=docker/dockerfile:1

# ---- build stage: resolve and install dependencies from the lockfile --------------------------
FROM python:3.14-slim AS builder
# Pinned to the uv release that produced uv.lock, so builds are reproducible.
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /srv
COPY pyproject.toml uv.lock ./
# --frozen: fail if the lockfile is out of date instead of silently re-resolving.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---- runtime stage: no uv, no build tools, no root ---------------------------------------------
FROM python:3.14-slim AS runtime
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /srv
COPY --from=builder --chown=app:app /srv/.venv /srv/.venv
COPY --chown=app:app app ./app
# The Evaluation page reads reports from here; mount a directory over it (see docker-compose.yml).
RUN mkdir -p eval/results && chown app:app eval/results

ENV PATH="/srv/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AIJP_LOG_FORMAT=json

USER app
EXPOSE 8000

# Liveness only (does not touch the database or Ollama); readiness is /health/ready.
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"]

# One worker: the Prometheus metrics are per-process (see app/metrics.py). Access logging is off
# because the app writes its own structured request log with a request id, and --log-config makes
# uvicorn's own lines JSON too, so the whole stream is one format for log shippers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--log-config", "app/uvicorn_logging.json"]
