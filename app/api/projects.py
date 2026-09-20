from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import projects
from app.audit import record_event
from app.auth import ApproverDep, ReaderDep
from app.db import get_session
from app.models import Project
from app.schemas import ProjectCreate, ProjectOut

router = APIRouter(prefix="/projects", tags=["projects"])

SessionDep = Annotated[Session, Depends(get_session)]


def _out(session: Session, project: Project) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        slug=project.slug,
        name=project.name,
        created_at=project.created_at,
        documents=projects.counts(session, project.id).documents,
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(session: SessionDep, principal: ReaderDep) -> list[ProjectOut]:
    """The projects this key may use: all of them, or just its own if it is project-scoped."""
    projects.get_or_create_default(session)
    return [_out(session, p) for p in projects.list_projects(session, principal.project_id)]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, session: SessionDep, principal: ApproverDep) -> ProjectOut:
    """Create a project. Only an approver key that is not confined to one project may do this;
    deleting a project is deliberately CLI-only (`python -m app.projects delete`)."""
    if principal.project_id is not None:
        raise HTTPException(status_code=403, detail="A project-scoped key cannot create projects")
    try:
        project = projects.create_project(session, body.slug, body.name)
    except projects.ProjectError as exc:
        status = 409 if "already exists" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from None
    record_event(session, principal, "project.create", project.slug, name=project.name)
    return _out(session, project)
