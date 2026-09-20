from typing import Protocol

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Chunk, Document, Project
from app.schemas import (
    ConfigView,
    DatabaseStatus,
    ModelStatus,
    OllamaStatus,
    SystemStatus,
)


class OllamaProbe(Protocol):
    def __call__(self, settings: Settings) -> OllamaStatus: ...


def probe_ollama(settings: Settings) -> OllamaStatus:
    """Ask Ollama which models it has. Never raises: an unreachable server is a status, not an
    error, because the status page exists to show exactly that."""
    roles = [("embedding", settings.embedding_model), ("answer", settings.llm_model)]
    try:
        response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=2.0)
        response.raise_for_status()
        installed = {m["name"] for m in response.json()["models"]}
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return OllamaStatus(
            reachable=False,
            base_url=settings.ollama_base_url,
            models=[ModelStatus(role=r, name=n, installed=False) for r, n in roles],
        )

    def has(model: str) -> bool:
        return model in installed or f"{model}:latest" in installed

    return OllamaStatus(
        reachable=True,
        base_url=settings.ollama_base_url,
        models=[ModelStatus(role=r, name=n, installed=has(n)) for r, n in roles],
    )


def build_status(
    session: Session,
    settings: Settings,
    probe: OllamaProbe,
    project: Project | None = None,
) -> SystemStatus:
    """Database counts, Ollama reachability and non-secret config. Failures are reported in the
    result rather than raised. Never includes the database URL."""
    try:
        pgvector = bool(session.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")))
        in_project = [] if project is None else [Document.project_id == project.id]
        documents = (
            session.scalar(select(func.count()).select_from(Document).where(*in_project)) or 0
        )
        chunk_rows = (
            select(func.count()).select_from(Chunk).join(Document, Document.id == Chunk.document_id)
        )
        chunks = session.scalar(chunk_rows.where(*in_project)) or 0
        embedded = session.scalar(chunk_rows.where(Chunk.embedding.is_not(None), *in_project)) or 0
        database = DatabaseStatus(
            reachable=True,
            pgvector=pgvector,
            documents=documents,
            chunks=chunks,
            embedded_chunks=embedded,
            pending_chunks=chunks - embedded,
        )
    except SQLAlchemyError:
        database = DatabaseStatus(
            reachable=False,
            pgvector=False,
            documents=0,
            chunks=0,
            embedded_chunks=0,
            pending_chunks=0,
        )
    return SystemStatus(
        project=project.slug if project is not None else None,
        database=database,
        ollama=probe(settings),
        config=ConfigView(
            auth_enabled=settings.auth_enabled,
            retrieval_mode=settings.retrieval_mode,
            ask_top_k=settings.ask_top_k,
            min_evidence_score=settings.min_evidence_score,
            chunk_max_chars=settings.chunk_max_chars,
            chunk_overlap_chars=settings.chunk_overlap_chars,
            max_upload_bytes=settings.max_upload_bytes,
            embedding_model=settings.embedding_model,
            llm_model=settings.llm_model,
        ),
    )
