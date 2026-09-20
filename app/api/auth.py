from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth import Principal, get_principal
from app.config import Settings, get_settings
from app.schemas import AuthConfig, Me

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/config", response_model=AuthConfig)
def auth_config(settings: Annotated[Settings, Depends(get_settings)]) -> AuthConfig:
    """Public. Lets the UI decide whether to show a sign-in screen before it has a key."""
    return AuthConfig(auth_enabled=settings.auth_enabled)


@router.get("/me", response_model=Me)
def me(
    principal: Annotated[Principal, Depends(get_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Me:
    """Who the presented key belongs to. Any valid key works; 401 otherwise."""
    return Me(
        name=principal.name,
        role=principal.role.name,
        key_prefix=principal.key_prefix,
        auth_enabled=settings.auth_enabled,
    )
