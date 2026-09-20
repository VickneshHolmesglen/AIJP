from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import metrics, providers, retrieval, services
from app.audit import record_event
from app.auth import EditorDep, RequireReader
from app.config import Settings, get_settings
from app.db import get_session
from app.embeddings import EmbeddingError, EmbeddingProvider
from app.llm import LLMProvider
from app.presenters import to_search_hits
from app.rerank import LLMReranker, rerank_candidates
from app.schemas import EmbedResponse, SearchRequest, SearchResponse

router = APIRouter(tags=["search"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_embedder() -> EmbeddingProvider:
    """Dependency seam: tests override this with a deterministic fake."""
    return providers.embedder()


EmbedderDep = Annotated[EmbeddingProvider, Depends(get_embedder)]


def get_llm() -> LLMProvider:
    """Dependency seam: tests override this with a scripted fake. It lives beside the embedder
    because /search (reranking), /ask and the agent all need it and ask.py imports this module."""
    return providers.llm()


LLMDep = Annotated[LLMProvider, Depends(get_llm)]


@router.post("/embeddings", response_model=EmbedResponse)
def embed_pending(
    session: SessionDep, settings: SettingsDep, embedder: EmbedderDep, principal: EditorDep
) -> EmbedResponse:
    """Embed every chunk that does not have a vector yet."""
    try:
        count = services.embed_pending_chunks(session, embedder, settings.embed_batch_size)
    except EmbeddingError as exc:
        metrics.record_dependency_error("embedding")
        raise HTTPException(status_code=503, detail=str(exc)) from None
    record_event(session, principal, "embeddings.run", None, embedded=count)
    return EmbedResponse(embedded=count)


@router.post("/search", response_model=SearchResponse, dependencies=[RequireReader])
def search(
    body: SearchRequest,
    session: SessionDep,
    settings: SettingsDep,
    embedder: EmbedderDep,
    llm: LLMDep,
) -> SearchResponse:
    reranking = settings.rerank_enabled
    try:
        hits = retrieval.search(
            session,
            embedder,
            body.query,
            mode=body.mode or settings.retrieval_mode,
            top_k=max(body.top_k, settings.rerank_pool) if reranking else body.top_k,
            pool=settings.retrieval_pool,
            rrf_k=settings.rrf_k,
            document_id=body.document_id,
        )
        if reranking:
            hits, ok = rerank_candidates(
                LLMReranker(llm), body.query, hits, body.top_k, settings.rerank_pool
            )
            metrics.record_rerank(ok)
    except EmbeddingError as exc:
        metrics.record_dependency_error("embedding")
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return SearchResponse(query=body.query, hits=to_search_hits(hits))
