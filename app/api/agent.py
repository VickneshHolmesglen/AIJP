import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import metrics
from app.agent import actions
from app.agent.consistency import run_consistency_check
from app.api.scope import ProjectDep
from app.api.search import EmbedderDep, LLMDep
from app.audit import record_event
from app.auth import ApproverDep, EditorDep, Principal, ReaderDep, RequireReader
from app.config import Settings, get_settings
from app.db import get_session
from app.models import AgentAction, AgentRun, Task
from app.presenters import to_run_detail, to_run_summary
from app.schemas import (
    ActionOut,
    ConsistencyRequest,
    RunDetail,
    RunList,
    TaskList,
    TaskOut,
)

router = APIRouter(prefix="/agent", tags=["agent"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("/consistency-checks", response_model=RunDetail, status_code=201)
def create_consistency_check(
    body: ConsistencyRequest,
    session: SessionDep,
    settings: SettingsDep,
    embedder: EmbedderDep,
    llm: LLMDep,
    principal: EditorDep,
    project: ProjectDep,
) -> RunDetail:
    """Run the design-vs-code check and return the persisted run with its full audit trail.

    Always 201: a dependency outage produces a run with status `failed` (and the steps that did
    happen), because the record itself is the audit trail. A potential discrepancy comes back
    `awaiting_approval` with a DRAFT action; nothing is created until it is approved."""
    run = run_consistency_check(
        session,
        embedder,
        llm,
        settings,
        body.claim,
        project_id=project.id,
        requested_by=principal.name,
    )
    metrics.record_agent_run(run)
    record_event(
        session,
        principal,
        "agent.check",
        str(run.id),
        project=project.slug,
        status=run.status,
        verdict=run.verdict,
    )
    return to_run_detail(run)


@router.get("/runs", response_model=RunList, dependencies=[RequireReader])
def list_runs(
    session: SessionDep,
    project: ProjectDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunList:
    total = (
        session.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.project_id == project.id)
        )
        or 0
    )
    runs = session.scalars(
        select(AgentRun)
        .where(AgentRun.project_id == project.id)
        .order_by(AgentRun.created_at.desc(), AgentRun.id)
        .limit(limit)
        .offset(offset)
    )
    return RunList(items=[to_run_summary(r) for r in runs], total=total, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: uuid.UUID, session: SessionDep, principal: ReaderDep) -> RunDetail:
    run = session.get(AgentRun, run_id)
    if run is None or not principal.can_access(run.project_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return to_run_detail(run)


def _decide(
    session: Session, action_id: uuid.UUID, approve: bool, principal: Principal
) -> AgentAction:
    # Authorise by the action's own project BEFORE touching it: a key confined to one project must
    # not be able to approve (or even confirm the existence of) another project's action.
    owner = session.get(AgentAction, action_id)
    run = session.get(AgentRun, owner.run_id) if owner is not None else None
    if run is None or not principal.can_access(run.project_id):
        raise HTTPException(status_code=404, detail="Action not found")
    try:
        action = actions.decide(session, action_id, approve, actor=principal.name)
    except actions.ActionNotFoundError:
        raise HTTPException(status_code=404, detail="Action not found") from None
    except actions.ActionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    record_event(
        session,
        principal,
        "agent.approve" if approve else "agent.reject",
        str(action_id),
        kind=action.kind,
        status=action.status,
        run_id=str(action.run_id),
    )
    return action


@router.post("/actions/{action_id}/approve", response_model=ActionOut)
def approve_action(action_id: uuid.UUID, session: SessionDep, principal: ApproverDep) -> ActionOut:
    """Execute a drafted action. Deliberately takes no request body: what runs is exactly what the
    server stored when it drafted the action."""
    action = _decide(session, action_id, True, principal)
    metrics.record_action(action)
    return ActionOut.model_validate(action)


@router.post("/actions/{action_id}/reject", response_model=ActionOut)
def reject_action(action_id: uuid.UUID, session: SessionDep, principal: ApproverDep) -> ActionOut:
    action = _decide(session, action_id, False, principal)
    metrics.record_action(action)
    return ActionOut.model_validate(action)


@router.get("/tasks", response_model=TaskList, dependencies=[RequireReader])
def list_tasks(session: SessionDep, project: ProjectDep) -> TaskList:
    tasks = list(
        session.scalars(
            select(Task)
            .where(Task.project_id == project.id)
            .order_by(Task.created_at.desc(), Task.id)
        )
    )
    return TaskList(items=[TaskOut.model_validate(t) for t in tasks], total=len(tasks))
