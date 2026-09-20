from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.scope import ProjectDep
from app.auth import RequireReader
from app.config import Settings, get_settings
from app.db import get_session
from app.schemas import SystemStatus
from app.system_status import OllamaProbe, build_status, probe_ollama

router = APIRouter(tags=["system"])


def get_ollama_probe() -> OllamaProbe:
    """Dependency seam so tests do not need a running Ollama."""
    return probe_ollama


@router.get("/status", response_model=SystemStatus, dependencies=[RequireReader])
def status(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    probe: Annotated[OllamaProbe, Depends(get_ollama_probe)],
    project: ProjectDep,
) -> SystemStatus:
    """Everything the UI's System page needs in one call. Always 200; failures are in the body."""
    return build_status(session, settings, probe, project)
