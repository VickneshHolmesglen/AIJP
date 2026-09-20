import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import AgentRun, AgentStep

log = logging.getLogger("app.agent")

_ERROR_CHARS = 300


class StepHandle:
    """What a step reports about itself. `output` must hold only JSON-serialisable summaries:
    counts, ids and citations, never document text."""

    def __init__(self) -> None:
        self.output: dict[str, Any] = {}
        self.skipped = False

    def skip(self, reason: str) -> None:
        self.skipped = True
        self.output = {"reason": reason}


class RunRecorder:
    """Writes the audit trail of one run, one committed row per step, as each step finishes.

    Committing per step means a crash midway (or the process being killed) still leaves the steps
    that happened. The trail is append-only: nothing here updates or deletes a step."""

    def __init__(self, session: Session, run: AgentRun) -> None:
        self._session = session
        self.run = run
        last = session.scalar(
            select(func.coalesce(func.max(AgentStep.seq), 0)).where(AgentStep.run_id == run.id)
        )
        self._seq: int = last or 0

    @contextmanager
    def step(self, name: str, **step_input: Any) -> Iterator[StepHandle]:
        handle = StepHandle()
        started = datetime.now(UTC)
        clock = time.perf_counter()
        status = "ok"
        try:
            yield handle
            if handle.skipped:
                status = "skipped"
        except Exception as exc:
            status = "error"
            message = f"{type(exc).__name__}: {exc}"[:_ERROR_CHARS]
            handle.output = {**handle.output, "error": message}
            raise
        finally:
            self._persist(name, status, step_input, handle.output, started, clock)

    def _persist(
        self,
        name: str,
        status: str,
        step_input: dict[str, Any],
        output: dict[str, Any],
        started: datetime,
        clock: float,
    ) -> None:
        try:
            self._seq += 1
            self._session.add(
                AgentStep(
                    run_id=self.run.id,
                    seq=self._seq,
                    name=name,
                    status=status,
                    input=step_input,
                    output=output,
                    duration_ms=round((time.perf_counter() - clock) * 1000),
                    started_at=started,
                )
            )
            self._session.commit()
        except SQLAlchemyError:
            # Losing an audit row must never mask the error that is already propagating.
            self._session.rollback()
            log.exception("could not record step %s of run %s", name, self.run.id)
