import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    # Path of the file inside the indexed project; used verbatim in citations.
    source_path: Mapped[str] = mapped_column(String(1024))
    file_type: Mapped[str] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(Integer)
    # Content hash: detects duplicate ingestion.
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str | None] = mapped_column(String(512))
    page_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Chunk.chunk_index",
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    # Provenance for citations. Not every format has every field.
    section: Mapped[str | None] = mapped_column(String(1024))
    page: Mapped[int | None] = mapped_column(Integer)
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    # NULL until the chunk is embedded (a separate step from ingestion).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(get_settings().embedding_dim))

    document: Mapped[Document] = relationship(back_populates="chunks")


# ---- agent workflows (Milestone 10) -----------------------------------------------------------
# A run is one execution of a fixed workflow. Its steps are the audit trail, written as each step
# finishes so a crash mid-run still leaves a record. Steps store citations and counts, never
# document text. An action is a *drafted* consequential operation that only a human can execute.


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workflow: Mapped[str] = mapped_column(String(64))
    input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # running | awaiting_approval | completed | failed
    status: Mapped[str] = mapped_column(String(24), default="running")
    verdict: Mapped[str | None] = mapped_column(String(32))  # denormalised for list views
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    # Who ran it (an API key's name). NULL for runs made before authentication existed.
    requested_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    steps: Mapped[list["AgentStep"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentStep.seq",
    )
    actions: Mapped[list["AgentAction"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentAction.created_at",
    )


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # ok | skipped | error
    input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB)
    duration_ms: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[AgentRun] = relationship(back_populates="steps")


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # must be in the action registry to execute
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # pending | executed | rejected | failed
    status: Mapped[str] = mapped_column(String(16), default="pending")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(100))  # the approver or rejecter

    run: Mapped[AgentRun] = relationship(back_populates="actions")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)  # citations, no document text
    status: Mapped[str] = mapped_column(String(16), default="open")
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    created_by: Mapped[str | None] = mapped_column(String(100))  # who approved its creation
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---- authentication and accountability (Milestone 12) -----------------------------------------


class ApiKey(Base):
    """A credential. Only a SHA-256 hash of the secret is stored; the token is shown once, at
    creation. `key_prefix` identifies the key (in listings, logs and lookups) and is not secret."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))  # the person or service; shown in audit trails
    role: Mapped[str] = mapped_column(String(16))  # reader | editor | approver
    key_prefix: Mapped[str] = mapped_column(String(8), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    """Append-only record of who did what. Stores identifiers and counts, never document text."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    actor: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(16))
    key_prefix: Mapped[str | None] = mapped_column(String(8))
    action: Mapped[str] = mapped_column(String(48), index=True)  # e.g. document.delete
    target: Mapped[str | None] = mapped_column(String(200))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64))
