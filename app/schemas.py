import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chunk_index: int
    content: str
    section: str | None
    page: int | None
    start_line: int | None
    end_line: int | None


class DocumentSummary(BaseModel):
    """Document columns only; safe to build from an ORM row without loading chunks."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    source_path: str
    file_type: str
    size_bytes: int
    sha256: str
    title: str | None
    page_count: int | None
    created_at: datetime


class DocumentOut(DocumentSummary):
    chunk_count: int


class DocumentDetail(DocumentOut):
    chunks: list[ChunkOut]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=50)
    document_id: uuid.UUID | None = None
    # None = the server's configured default (settings.retrieval_mode).
    mode: Literal["vector", "lexical", "hybrid"] | None = None


class Citation(BaseModel):
    """Everything needed to point a reader back at the exact source location."""

    document_id: uuid.UUID
    source_path: str
    section: str | None
    page: int | None
    start_line: int | None
    end_line: int | None


class SearchHit(BaseModel):
    chunk_id: uuid.UUID
    # Ranking score: cosine (vector), ts_rank_cd (lexical) or RRF (hybrid). Only comparable
    # within one response. `cosine` is the semantic similarity, null if the chunk is not embedded.
    score: float
    cosine: float | None
    # 0-3 relevance grade from the reranker; null when reranking is off or did not grade this hit.
    rerank_grade: int | None = None
    content: str
    citation: Citation


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    document_id: uuid.UUID | None = None


class AnswerSource(BaseModel):
    ref: int
    chunk_id: uuid.UUID
    score: float
    content: str
    citation: Citation


class ProjectOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    created_at: datetime
    documents: int = 0


class ProjectCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=100)


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int


class CalculationOut(BaseModel):
    """A step the model wrote and the server computed, so a derived number can be checked."""

    id: str
    expression: str
    result: str


class AskResponse(BaseModel):
    refused: bool
    answer: str | None
    reason: (
        Literal[
            "insufficient_evidence",
            "model_declined",
            "uncited_answer",
            "calculation_failed",
            "ungrounded_number",
            "answer_truncated",
        ]
        | None
    )
    sources: list[AnswerSource]
    top_score: float | None
    usage: Usage
    calculations: list[CalculationOut] = []
    # "used": a second, reasoning pass replaced the first answer. "fallback": it failed.
    escalated: Literal["used", "fallback"] | None = None


class DocumentPage(DocumentOut):
    """A document with a slice of its passages (MCP get_document: whole files can be huge)."""

    chunk_offset: int
    chunks: list[ChunkOut]
    has_more: bool


class SymbolMatch(BaseModel):
    kind: Literal["definition", "declaration"]
    chunk_id: uuid.UUID
    citation: Citation
    preview: str


class SymbolMatches(BaseModel):
    name: str
    matches: list[SymbolMatch]


class ModelStatus(BaseModel):
    role: Literal["embedding", "answer"]
    name: str
    installed: bool


class OllamaStatus(BaseModel):
    reachable: bool
    base_url: str
    models: list[ModelStatus]


class DatabaseStatus(BaseModel):
    reachable: bool
    pgvector: bool
    documents: int
    chunks: int
    embedded_chunks: int
    pending_chunks: int


class ConfigView(BaseModel):
    """Non-secret settings the UI displays and uses (e.g. the evidence gate on refusals)."""

    auth_enabled: bool
    retrieval_mode: Literal["vector", "lexical", "hybrid"]
    ask_top_k: int
    min_evidence_score: float
    chunk_max_chars: int
    chunk_overlap_chars: int
    max_upload_bytes: int
    embedding_model: str
    llm_model: str


class SystemStatus(BaseModel):
    project: str | None = None  # the project the document counts describe
    database: DatabaseStatus
    ollama: OllamaStatus
    config: ConfigView


class EvalReportSummary(BaseModel):
    name: str
    kind: Literal["retrieval", "qa", "consistency"]
    date: str
    smoke: bool
    size_bytes: int


class EvalReportList(BaseModel):
    items: list[EvalReportSummary]


class EvalReport(BaseModel):
    name: str
    markdown: str


class EmbedResponse(BaseModel):
    embedded: int


class DocumentList(BaseModel):
    items: list[DocumentOut]
    total: int
    limit: int
    offset: int


# ---- agent workflows (Milestone 10) -----------------------------------------------------------


class ConsistencyRequest(BaseModel):
    claim: str = Field(min_length=3, max_length=1000)


class EvidenceItem(BaseModel):
    """A passage the check considered: where it is, never what it says (open it via the viewer)."""

    ref: str
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    path: str
    section: str | None
    start_line: int | None
    end_line: int | None
    origin: Literal["search", "symbol"]
    score: float | None
    cosine: float | None
    cited: bool = False  # did the accepted verdict cite it


class ConsistencyResult(BaseModel):
    verdict: Literal["consistent", "potential_discrepancy", "insufficient_evidence"]
    explanation: str
    design_evidence: list[EvidenceItem]
    implementation_evidence: list[EvidenceItem]
    disclaimer: str
    downgrade_reason: str | None
    usage: Usage


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    name: str
    status: str
    input: dict[str, Any]
    output: dict[str, Any]
    duration_ms: int
    started_at: datetime


class ActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    status: str
    result: dict[str, Any] | None
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None


class RunSummary(BaseModel):
    id: uuid.UUID
    workflow: str
    claim: str
    requested_by: str | None
    status: str
    verdict: str | None
    created_at: datetime
    finished_at: datetime | None


class RunDetail(RunSummary):
    error: str | None
    result: ConsistencyResult | None
    steps: list[StepOut]
    actions: list[ActionOut]


class RunList(BaseModel):
    items: list[RunSummary]
    total: int
    limit: int
    offset: int


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str
    evidence: list[dict[str, Any]]
    status: str
    source_run_id: uuid.UUID | None
    created_by: str | None
    created_at: datetime


class TaskList(BaseModel):
    items: list[TaskOut]
    total: int


# ---- authentication (Milestone 12) ------------------------------------------------------------


class AuthConfig(BaseModel):
    auth_enabled: bool


class Me(BaseModel):
    name: str
    role: Literal["reader", "editor", "approver"]
    key_prefix: str | None
    auth_enabled: bool
