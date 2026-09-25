"""Retrieval: vector, lexical (PostgreSQL full-text) and hybrid (Reciprocal Rank Fusion).

Every Hit carries `cosine` (semantic similarity to the query, when the chunk is embedded) *and*
`score` (what the ranking used: cosine, ts_rank_cd, or the fused RRF value). The evidence gate in
`qa.py` works on `cosine`, because RRF scores are only meaningful relative to each other and cannot
be compared with a fixed threshold.
"""

import uuid
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from sqlalchemy import Select, Text, cast, func, literal_column, null, select
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import ColumnClause

from app.embeddings import EmbeddingProvider
from app.models import Chunk, Document

RetrievalMode = Literal["vector", "lexical", "hybrid"]
T = TypeVar("T", bound=Hashable)

_ENGLISH: ColumnClause[Any] = literal_column("'english'::regconfig")
# Must stay textually identical to the GIN index expression created in `db.init_db`, or PostgreSQL
# will not use the index. The section (symbol path) is indexed so a later chunk of a long function
# is still findable by the function's name.
_DOC_TSVECTOR = func.to_tsvector(_ENGLISH, func.coalesce(Chunk.section, "") + " " + Chunk.content)


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    document: Document
    score: float
    cosine: float | None
    # Set only by a reranker (app/rerank.py): the 0-3 grade it gave this chunk.
    rerank_grade: int | None = None


def reciprocal_rank_fusion(rankings: Sequence[Sequence[T]], k: int = 60) -> dict[T, float]:
    """Fuse ranked lists: score(item) = sum over lists of 1 / (k + rank), rank starting at 1.

    Needs only ranks, not scores, so it can combine cosine similarity and ts_rank_cd, which live on
    incompatible scales. k damps the influence of top ranks (60 is the value from the original
    paper; it is a default, not something we tuned).
    """
    scores: dict[T, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


def _scope(
    stmt: Select[Any],
    project_id: uuid.UUID | None,
    document_id: uuid.UUID | None,
    file_types: Sequence[str] | None,
) -> Select[Any]:
    """Filters shared by every retriever, applied in SQL so top-k stays a true top-k.

    `project_id` is what keeps one project's text out of another's results. Every caller must
    pass it explicitly (there is no default): None means "all projects" and is only for tools that
    deliberately span them, such as the evaluation runners over one scratch database."""
    if project_id is not None:
        stmt = stmt.where(Document.project_id == project_id)
    if document_id is not None:
        stmt = stmt.where(Chunk.document_id == document_id)
    if file_types:
        stmt = stmt.where(Document.file_type.in_(file_types))
    return stmt


def vector_search(
    session: Session,
    query_vector: list[float],
    limit: int,
    document_id: uuid.UUID | None = None,
    file_types: Sequence[str] | None = None,
    *,
    project_id: uuid.UUID | None,
) -> list[Hit]:
    distance = Chunk.embedding.cosine_distance(query_vector)
    stmt = (
        select(Chunk, Document, (1 - distance).label("cosine"))
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    stmt = _scope(stmt, project_id, document_id, file_types)
    return [Hit(c, d, float(cos), float(cos)) for c, d, cos in session.execute(stmt).all()]


def lexical_search(
    session: Session,
    query: str,
    query_vector: list[float] | None,
    limit: int,
    document_id: uuid.UUID | None = None,
    file_types: Sequence[str] | None = None,
    *,
    project_id: uuid.UUID | None,
) -> list[Hit]:
    """Full-text search. Query terms are OR-ed (plainto_tsquery ANDs them, which would make a
    natural-language question match nothing); ts_rank_cd then favours chunks matching more terms."""
    ts_query = cast(
        func.replace(cast(func.plainto_tsquery(_ENGLISH, query), Text), " & ", " | "), TSQUERY
    )
    rank = func.ts_rank_cd(_DOC_TSVECTOR, ts_query)
    cosine = (
        (1 - Chunk.embedding.cosine_distance(query_vector)) if query_vector is not None else None
    )
    stmt = (
        select(Chunk, Document, rank.label("rank"), (cosine if cosine is not None else null()))
        .join(Document, Document.id == Chunk.document_id)
        .where(_DOC_TSVECTOR.op("@@")(ts_query))
        # Ties (common: short queries hit the same few terms) are broken by location, which is
        # the same in every ingest. Chunk.id is a random UUID minted at ingest, so ordering by it
        # alone made lexical results a coin flip per ingest; it stays last only for two documents
        # that share a path (possible across projects).
        .order_by(rank.desc(), Document.source_path, Chunk.chunk_index, Chunk.id)
        .limit(limit)
    )
    stmt = _scope(stmt, project_id, document_id, file_types)
    return [
        Hit(c, d, float(r), float(cos) if cos is not None else None)
        for c, d, r, cos in session.execute(stmt).all()
    ]


def hybrid_search(
    session: Session,
    query: str,
    query_vector: list[float],
    top_k: int,
    pool: int,
    rrf_k: int,
    document_id: uuid.UUID | None = None,
    file_types: Sequence[str] | None = None,
    *,
    project_id: uuid.UUID | None,
) -> list[Hit]:
    vector_hits = vector_search(
        session, query_vector, pool, document_id, file_types, project_id=project_id
    )
    lexical_hits = lexical_search(
        session, query, query_vector, pool, document_id, file_types, project_id=project_id
    )
    fused = reciprocal_rank_fusion(
        [[h.chunk.id for h in vector_hits], [h.chunk.id for h in lexical_hits]], rrf_k
    )
    by_id = {h.chunk.id: h for h in [*lexical_hits, *vector_hits]}
    # RRF ties are common (rank r in one list only scores the same whatever the list): break
    # them by location, as lexical_search does, not by the random chunk id.
    ranked = sorted(
        fused,
        key=lambda cid: (
            -fused[cid],
            by_id[cid].document.source_path,
            by_id[cid].chunk.chunk_index,
            str(cid),
        ),
    )[:top_k]
    return [Hit(by_id[c].chunk, by_id[c].document, fused[c], by_id[c].cosine) for c in ranked]


def search(
    session: Session,
    embedder: EmbeddingProvider,
    query: str,
    *,
    mode: RetrievalMode,
    top_k: int,
    pool: int = 20,
    rrf_k: int = 60,
    document_id: uuid.UUID | None = None,
    file_types: Sequence[str] | None = None,
    project_id: uuid.UUID | None,
) -> list[Hit]:
    """Top-k chunks for `query`, best first. May raise EmbeddingError (vector/hybrid/lexical all
    embed the query, since the gate needs each hit's cosine)."""
    (query_vector,) = embedder.embed([query])
    if mode == "vector":
        return vector_search(
            session, query_vector, top_k, document_id, file_types, project_id=project_id
        )
    if mode == "lexical":
        return lexical_search(
            session, query, query_vector, top_k, document_id, file_types, project_id=project_id
        )
    return hybrid_search(
        session,
        query,
        query_vector,
        top_k,
        max(pool, top_k),
        rrf_k,
        document_id,
        file_types,
        project_id=project_id,
    )
