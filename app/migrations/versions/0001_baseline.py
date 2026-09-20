"""Baseline: the schema as of Milestone 12.

Written out explicitly instead of calling `Base.metadata.create_all`: a migration must describe
the schema at ONE point in history, and `create_all` would silently change meaning whenever a model
changes. A test compares the result of this migration with the models, so drift is caught.

The embedding dimension comes from the current settings, because it is deployment configuration
(see docs/deployment.md: changing it later is a data migration, not just a schema change).

Revision ID: 0001
Revises:
"""

from typing import Any

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from app.config import get_settings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("source_path", sa.String(1024), nullable=False),
        sa.Column("file_type", sa.String(16), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512)),
        sa.Column("page_count", sa.Integer()),
        _created_at(),
        sa.UniqueConstraint("sha256"),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("section", sa.String(1024)),
        sa.Column("page", sa.Integer()),
        sa.Column("start_line", sa.Integer()),
        sa.Column("end_line", sa.Integer()),
        sa.Column("embedding", Vector(get_settings().embedding_dim)),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    # HNSW approximate-nearest-neighbour index for cosine search.
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)"
    )
    # Full-text index for lexical search; the expression must match app/retrieval.py.
    op.execute(
        "CREATE INDEX ix_chunks_fts ON chunks USING gin "
        "(to_tsvector('english'::regconfig, coalesce(section, '') || ' ' || content))"
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workflow", sa.String(64), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("verdict", sa.String(32)),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("requested_by", sa.String(100)),
        _created_at(),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("output", postgresql.JSONB(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_agent_steps_run_id", "agent_steps", ["run_id"])
    op.create_table(
        "agent_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", postgresql.JSONB()),
        _created_at(),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by", sa.String(100)),
    )
    op.create_index("ix_agent_actions_run_id", "agent_actions", ["run_id"])
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "source_run_id",
            sa.Uuid(),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("created_by", sa.String(100)),
        _created_at(),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("key_prefix", sa.String(8), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        _created_at(),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("key_prefix"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("key_prefix", sa.String(8)),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("target", sa.String(200)),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.Column("request_id", sa.String(64)),
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])


def downgrade() -> None:
    # Destroys all data. Kept so the baseline is reversible in development and in tests.
    for table in (
        "audit_events",
        "api_keys",
        "tasks",
        "agent_actions",
        "agent_steps",
        "agent_runs",
        "chunks",
        "documents",
    ):
        op.drop_table(table)
