"""Maps domain results (Hit, qa.Answer) onto response schemas.

One place, used by both the HTTP API and the MCP server, so the two interfaces cannot drift apart
in what a citation or a search hit looks like.
"""

from app.models import AgentRun, Chunk, Document
from app.qa import Answer
from app.retrieval import Hit
from app.schemas import (
    ActionOut,
    AnswerSource,
    AskResponse,
    CalculationOut,
    Citation,
    ConsistencyResult,
    DocumentOut,
    DocumentSummary,
    RunDetail,
    RunSummary,
    SearchHit,
    StepOut,
    Usage,
)


def to_citation(chunk: Chunk, doc: Document) -> Citation:
    return Citation(
        document_id=doc.id,
        source_path=doc.source_path,
        section=chunk.section,
        page=chunk.page,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
    )


def to_document_out(doc: Document, chunk_count: int) -> DocumentOut:
    return DocumentOut(**DocumentSummary.model_validate(doc).model_dump(), chunk_count=chunk_count)


def to_search_hits(hits: list[Hit]) -> list[SearchHit]:
    return [
        SearchHit(
            chunk_id=h.chunk.id,
            score=h.score,
            cosine=h.cosine,
            rerank_grade=h.rerank_grade,
            content=h.chunk.content,
            citation=to_citation(h.chunk, h.document),
        )
        for h in hits
    ]


def to_ask_response(result: Answer) -> AskResponse:
    return AskResponse(
        refused=result.refused,
        answer=result.answer,
        reason=result.reason,
        sources=[
            AnswerSource(
                ref=e.ref,
                chunk_id=e.chunk.id,
                score=e.score,
                content=e.chunk.content,
                citation=to_citation(e.chunk, e.document),
            )
            for e in result.sources
        ],
        top_score=result.top_score,
        escalated=result.escalated,
        calculations=[
            CalculationOut(id=c.id, expression=c.expression, result=c.result)
            for c in result.calculations
        ],
        usage=Usage(prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens),
    )


def to_run_summary(run: AgentRun) -> RunSummary:
    return RunSummary(
        id=run.id,
        workflow=run.workflow,
        claim=str(run.input.get("claim", "")),
        requested_by=run.requested_by,
        status=run.status,
        verdict=run.verdict,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


def to_run_detail(run: AgentRun) -> RunDetail:
    return RunDetail(
        **to_run_summary(run).model_dump(),
        error=run.error,
        result=ConsistencyResult.model_validate(run.result) if run.result else None,
        steps=[StepOut.model_validate(s) for s in run.steps],
        actions=[ActionOut.model_validate(a) for a in run.actions],
    )
