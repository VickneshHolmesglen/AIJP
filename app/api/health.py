from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up. Does not touch the database."""
    return {"status": "ok"}


@router.get("/health/ready")
def ready(session: Annotated[Session, Depends(get_session)]) -> dict[str, str]:
    """Readiness: the database is reachable and pgvector is installed."""
    try:
        installed = session.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="database unavailable") from None
    if not installed:
        raise HTTPException(status_code=503, detail="pgvector extension not installed")
    return {"status": "ready"}
