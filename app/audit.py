"""Append-only audit events: who did what, to what.

Only state-changing actions are recorded (uploads, deletes, embedding runs, consistency checks,
approvals), not reads. Events hold identifiers, paths and counts, never document text, question
text or key material. `detail` values are restricted to short scalars so nothing large or
structured can slip in by accident.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.auth import Principal
from app.models import AuditEvent
from app.observability import request_id_var

log = logging.getLogger("app.audit")

_MAX_VALUE = 200


def _scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)[:_MAX_VALUE]


def record_event(
    session: Session, principal: Principal, action: str, target: str | None = None, **detail: Any
) -> AuditEvent:
    request_id = request_id_var.get()
    event = AuditEvent(
        actor=principal.name,
        role=principal.role.name,
        key_prefix=principal.key_prefix,
        action=action,
        target=str(target)[:_MAX_VALUE] if target is not None else None,
        detail={k: _scalar(v) for k, v in detail.items()},
        request_id=request_id if request_id != "-" else None,
    )
    session.add(event)
    session.commit()
    log.info("audit", extra={"actor": principal.name, "action": action, "target": target})
    return event
