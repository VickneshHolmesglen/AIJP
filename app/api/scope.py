"""Which project a request is about, and whether the caller may touch it.

    ?project=<slug>   (default: "default")

One dependency does both jobs so no endpoint can resolve a project and forget to authorise it. A
project that does not exist and a project the key is not allowed to use give the SAME 404, so a
scoped key cannot probe which other projects exist.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import projects
from app.auth import Principal, get_principal
from app.db import get_session
from app.models import Project


def get_project(
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    project: Annotated[
        str | None,
        Query(
            max_length=40,
            description="Project slug. Defaults to the key's own project if it is scoped to one, "
            "otherwise to the 'default' project.",
        ),
    ] = None,
) -> Project:
    if project is None and principal.project_id is not None:
        found = session.get(Project, principal.project_id)  # a scoped key defaults to ITS project
    else:
        found = projects.resolve(session, project or projects.DEFAULT_SLUG)
    if found is None or not principal.can_access(found.id):
        raise HTTPException(status_code=404, detail="Project not found")
    return found


ProjectDep = Annotated[Project, Depends(get_project)]
