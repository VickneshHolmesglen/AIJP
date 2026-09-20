from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import metrics, qa
from app.api.scope import ProjectDep
from app.api.search import EmbedderDep, LLMDep
from app.api.search import get_llm as get_llm  # re-exported: tests override it from here
from app.auth import RequireReader
from app.config import Settings, get_settings
from app.db import get_session
from app.embeddings import EmbeddingError
from app.llm import LLMError
from app.presenters import to_ask_response
from app.rerank import LLMReranker
from app.schemas import AskRequest, AskResponse

router = APIRouter(tags=["ask"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("/ask", response_model=AskResponse, dependencies=[RequireReader])
def ask(
    body: AskRequest,
    session: SessionDep,
    settings: SettingsDep,
    embedder: EmbedderDep,
    llm: LLMDep,
    project: ProjectDep,
) -> AskResponse:
    try:
        result = qa.ask(
            session,
            embedder,
            llm,
            body.question,
            top_k=settings.ask_top_k,
            min_score=settings.min_evidence_score,
            mode=settings.retrieval_mode,
            pool=settings.retrieval_pool,
            rrf_k=settings.rrf_k,
            document_id=body.document_id,
            project_id=project.id,
            reranker=LLMReranker(llm) if settings.rerank_enabled else None,
            rerank_pool=settings.rerank_pool,
            calculator=settings.ask_calculator,
        )
    except EmbeddingError as exc:
        metrics.record_dependency_error("embedding")
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except LLMError as exc:
        metrics.record_dependency_error("llm")
        raise HTTPException(status_code=503, detail=str(exc)) from None
    metrics.record_ask(result)
    return to_ask_response(result)
