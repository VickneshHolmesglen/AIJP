"""Drafted actions and the human approval gate.

A workflow may only DRAFT an action (an `agent_actions` row in `pending`). It is executed only when
a person approves it, and:

- Approval takes no payload. What is executed is exactly what the server drafted and stored, so a
  client cannot approve one thing and get another.
- Only kinds in `ACTION_REGISTRY` can be executed; anything else is refused. Adding a consequential
  action means adding it here, on purpose.
- The action row is locked (SELECT ... FOR UPDATE) while it is decided, so two simultaneous
  approvals cannot both execute it, and a decided action can never be decided again.
- Every decision is written to the run's audit trail.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.recorder import RunRecorder
from app.models import AgentAction, AgentRun, Task

log = logging.getLogger("app.agent")

_MAX_TITLE = 200


class ActionError(Exception):
    """Base class for approval-gate failures the API turns into HTTP errors."""


class ActionNotFoundError(ActionError):
    pass


class ActionConflictError(ActionError):
    """The action was already decided."""

    def __init__(self, status: str) -> None:
        super().__init__(f"Action was already {status}")
        self.status = status


def _create_task(session: Session, action: AgentAction) -> dict[str, Any]:
    payload = action.payload
    run = session.get(AgentRun, action.run_id)
    assert run is not None  # an action cannot exist without its run (foreign key)
    task = Task(
        project_id=run.project_id,  # a task lives in the project whose claim produced it
        title=str(payload["title"])[:_MAX_TITLE],
        description=str(payload["description"]),
        evidence=list(payload["evidence"]),
        source_run_id=action.run_id,
        created_by=action.decided_by,  # the approver: whoever authorised its creation
    )
    session.add(task)
    session.flush()
    return {"task_id": str(task.id)}


# The only actions that can ever be executed. Each takes (session, action) and returns a JSON-able
# result. Read-only workflow steps are not actions and are not listed here.
ACTION_REGISTRY: dict[str, Callable[[Session, AgentAction], dict[str, Any]]] = {
    "create_task": _create_task,
}


def decide(
    session: Session, action_id: uuid.UUID, approve: bool, actor: str | None = None
) -> AgentAction:
    """Approve (execute) or reject a pending action. Raises ActionNotFoundError or
    ActionConflictError; a failing executor marks the action `failed` instead of raising."""
    # populate_existing: if the caller already loaded this action (the API does, to authorise it),
    # the identity map would otherwise keep that stale copy and ignore the row the lock returns,
    # so a request that waited for a concurrent approval would still see "pending" and run it again.
    action = session.scalars(
        select(AgentAction)
        .where(AgentAction.id == action_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()
    if action is None:
        raise ActionNotFoundError("Action not found")
    if action.status != "pending":
        session.rollback()  # release the row lock
        raise ActionConflictError(action.status)

    run = session.get(AgentRun, action.run_id)
    decision = "approved" if approve else "rejected"
    action.decided_at = datetime.now(UTC)
    action.decided_by = actor
    if not approve:
        action.status = "rejected"
    else:
        executor = ACTION_REGISTRY.get(action.kind)
        if executor is None:
            action.status = "failed"
            action.result = {"error": f"Unknown action kind '{action.kind}'"}
        else:
            try:
                action.result = executor(session, action)
                action.status = "executed"
            except Exception:
                log.exception("action %s (%s) failed", action.id, action.kind)
                session.rollback()
                # rollback dropped the row lock and expired the objects: re-read and record failure
                reloaded = session.get(AgentAction, action_id)
                if reloaded is None:
                    raise ActionNotFoundError("Action not found") from None
                action = reloaded
                action.status = "failed"
                action.decided_at = datetime.now(UTC)
                action.decided_by = actor
                action.result = {"error": "The action failed; see the server log."}
                run = session.get(AgentRun, action.run_id)
    if run is not None and not any(a.status == "pending" for a in run.actions if a.id != action.id):
        run.status = "completed"
    session.commit()

    if run is not None:
        recorder = RunRecorder(session, run)
        with recorder.step(
            "human_decision", action_id=str(action.id), decision=decision, actor=actor
        ) as step:
            step.output = {"action_status": action.status, "result": action.result}
    return action
