"""API-key authentication and role-based authorisation.

Keys look like `aijp_<8 hex prefix>_<43 char secret>`. Only a SHA-256 hash of the secret is stored:
the secret is 256 bits of randomness, so unlike a human-chosen password it needs no slow hash, and
comparison is constant-time. The prefix is not secret; it identifies the key in listings and logs.

Roles form a hierarchy, `reader < editor < approver`, and every endpoint except the health probes
and the static UI requires at least `reader`. A failed check is always the same generic 401 so the
response cannot be used to learn which keys exist; the real reason goes to the log and a metric.
"""

import hashlib
import hmac
import json
import logging
import re
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Receive, Scope, Send

from app import metrics
from app.config import Settings, get_settings
from app.db import get_session
from app.models import ApiKey

log = logging.getLogger("app.auth")


class Role(IntEnum):
    """The numeric order is the permission hierarchy: a higher role can do all a lower one can."""

    reader = 1  # ask, search, read documents, evaluation reports, runs, tasks, status
    editor = 2  # + upload, delete, embed, run consistency checks
    approver = 3  # + approve or reject drafted actions


_TOKEN = re.compile(r"^aijp_([0-9a-f]{8})_([A-Za-z0-9_-]{43})$")
_LAST_USED_GRANULARITY = timedelta(minutes=5)  # avoids a database write on every request
_DUMMY_HASH = hashlib.sha256(b"no such key").hexdigest()
_MAX_NAME = 100


class AuthError(Exception):
    """Why authentication failed. Logged and counted, never shown to the client."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Principal:
    name: str
    role: Role
    key_id: uuid.UUID | None
    key_prefix: str | None


# Used when authentication is disabled: everything is allowed, and the audit trail says so.
ANONYMOUS = Principal("anonymous (authentication disabled)", Role.approver, None, None)


# ------------------------------------------------------------------ tokens


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def generate_token() -> tuple[str, str, str]:
    """Return (token, prefix, hash). The token is shown once; only prefix and hash are stored."""
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    return f"aijp_{prefix}_{secret}", prefix, hash_secret(secret)


def parse_token(token: str) -> tuple[str, str] | None:
    match = _TOKEN.match(token)
    return (match.group(1), match.group(2)) if match else None


def _valid_name(name: str) -> str:
    # Check the RAW input: a name is an identity in audit records and logs, so a newline, tab or
    # other control character is rejected rather than quietly rewritten into something else.
    problem = ValueError(f"name must be 1-{_MAX_NAME} printable characters")
    if not name.isprintable():
        raise problem
    cleaned = " ".join(name.split())  # only tidies ordinary runs of spaces
    if not cleaned or len(cleaned) > _MAX_NAME:
        raise problem
    return cleaned


# ------------------------------------------------------------------ key management


def create_key(
    session: Session, name: str, role: Role, expires_at: datetime | None = None
) -> tuple[ApiKey, str]:
    """Create a key and return it with its one-time token. Names are unique among active keys, so
    an audit entry naming 'alice' always means one credential holder."""
    name = _valid_name(name)
    active = session.scalars(select(ApiKey).where(ApiKey.name == name, ApiKey.revoked_at.is_(None)))
    if active.first() is not None:
        raise ValueError(f"an active key named '{name}' already exists; revoke it first")
    for _ in range(5):  # a prefix collision is astronomically unlikely, but it is a unique column
        token, prefix, key_hash = generate_token()
        if session.scalar(select(ApiKey.id).where(ApiKey.key_prefix == prefix)) is None:
            key = ApiKey(
                name=name,
                role=role.name,
                key_prefix=prefix,
                key_hash=key_hash,
                expires_at=expires_at,
            )
            session.add(key)
            session.commit()
            return key, token
    raise RuntimeError("could not generate a unique key prefix")


def revoke_keys(session: Session, identifier: str) -> list[ApiKey]:
    """Revoke active keys matching an exact prefix or an exact name. Revoked keys stop working on
    the very next request (the key is looked up on every request, never cached)."""
    keys = list(
        session.scalars(
            select(ApiKey).where(
                ApiKey.revoked_at.is_(None),
                (ApiKey.key_prefix == identifier) | (ApiKey.name == identifier),
            )
        )
    )
    for key in keys:
        key.revoked_at = datetime.now(UTC)
    session.commit()
    return keys


# ------------------------------------------------------------------ verification


def authenticate(session: Session, token: str | None, now: datetime | None = None) -> Principal:
    """Resolve a bearer token to a Principal, or raise AuthError with the internal reason."""
    now = now or datetime.now(UTC)
    if not token:
        raise AuthError("missing")
    parsed = parse_token(token)
    if parsed is None:
        raise AuthError("malformed")
    prefix, secret = parsed

    candidate = hash_secret(secret)
    key = session.scalar(select(ApiKey).where(ApiKey.key_prefix == prefix))
    # Always run one constant-time comparison, even for an unknown prefix, so timing does not
    # reveal whether a prefix exists.
    matches = hmac.compare_digest(candidate, key.key_hash if key else _DUMMY_HASH)
    if key is None:
        raise AuthError("unknown")
    if not matches:
        raise AuthError("mismatch")
    if key.revoked_at is not None:
        raise AuthError("revoked")
    if key.expires_at is not None and key.expires_at <= now:
        raise AuthError("expired")

    if key.last_used_at is None or now - key.last_used_at > _LAST_USED_GRANULARITY:
        key.last_used_at = now
        session.commit()
    return Principal(key.name, Role[key.role], key.id, key.key_prefix)


# ------------------------------------------------------------------ FastAPI dependencies

_bearer = HTTPBearer(
    auto_error=False, description="An API key created with `python -m app.keys create`."
)


def get_principal(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if not settings.auth_enabled:
        request.state.actor = ANONYMOUS.name
        return ANONYMOUS
    try:
        principal = authenticate(session, credentials.credentials if credentials else None)
    except AuthError as exc:
        metrics.record_auth_failure(exc.reason)
        log.warning("authentication failed", extra={"reason": exc.reason})
        # One generic answer for every reason: no oracle for which keys exist or why one failed.
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    request.state.actor = principal.name  # the request log reads this
    return principal


def require_role(minimum: Role) -> Callable[[Principal], Principal]:
    """Dependency factory: `Depends(require_role(Role.editor))` returns the Principal or raises."""

    def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if principal.role < minimum:
            metrics.record_auth_denied(minimum.name)
            log.warning(
                "authorisation denied",
                extra={
                    "actor": principal.name,
                    "role": principal.role.name,
                    "needed": minimum.name,
                },
            )
            raise HTTPException(
                status_code=403, detail=f"This action requires the {minimum.name} role"
            )
        return principal

    return dependency


# For endpoints that only need gating (they do not use the principal):
#     @router.get(..., dependencies=[RequireReader])
RequireReader = Depends(require_role(Role.reader))
ReaderDep = Annotated[Principal, Depends(require_role(Role.reader))]
EditorDep = Annotated[Principal, Depends(require_role(Role.editor))]
ApproverDep = Annotated[Principal, Depends(require_role(Role.approver))]


def warn_if_auth_disabled(settings: Settings) -> bool:
    """Log a loud warning at startup when authentication is off. Returns whether it warned."""
    if settings.auth_enabled:
        return False
    log.warning(
        "AUTHENTICATION IS DISABLED (AIJP_AUTH_ENABLED=false): anyone who can reach this server "
        "can upload, delete and approve. Use this only on a machine nobody else can reach."
    )
    return True


# ------------------------------------------------------------------ pre-body gate

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# Multipart framing and form fields add a little on top of the file itself.
_BODY_SLACK_BYTES = 1024 * 1024


class RequestGateMiddleware:
    """Rejects unauthenticated or oversized requests BEFORE their body is read.

    FastAPI parses a request body (for uploads, spooling it to disk) before it resolves
    dependencies, so on its own the per-endpoint 401 would only fire after an anonymous client had
    pushed an arbitrarily large upload through the parser. This gate is deliberately cheap and
    does not touch the database: it only checks that a mutating request carries a well-formed
    bearer token, and that a declared Content-Length is not absurd. Real verification (is this key
    valid, unrevoked, allowed?) still happens in the dependencies. A client that sends a
    well-formed but fake token, or a chunked body with no Content-Length, still reaches the parser,
    so also cap request bodies at the reverse proxy (see docs/deployment.md).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _MUTATING:
            await self.app(scope, receive, send)
            return

        # Settings are looked up per request so test overrides (and env changes) are honoured.
        app = scope["app"]
        settings_factory = app.dependency_overrides.get(get_settings, get_settings)
        settings: Settings = settings_factory()

        headers = {k.lower(): v for k, v in scope["headers"]}
        if settings.auth_enabled:
            auth = headers.get(b"authorization", b"").decode("latin-1")
            scheme, _, token = auth.partition(" ")
            if scheme.lower() != "bearer" or parse_token(token.strip()) is None:
                metrics.record_auth_failure("missing" if not auth else "malformed")
                await _reject(send, 401, "Invalid or missing API key", bearer=True)
                return

        declared = headers.get(b"content-length", b"").decode("latin-1")
        limit = settings.max_upload_bytes + _BODY_SLACK_BYTES
        if declared.isdigit() and int(declared) > limit:
            await _reject(send, 413, "Request body is too large")
            return

        await self.app(scope, receive, send)


async def _reject(send: Send, status: int, detail: str, bearer: bool = False) -> None:
    body = json.dumps({"detail": detail}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if bearer:
        headers.append((b"www-authenticate", b"Bearer"))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
