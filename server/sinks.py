"""DB implementations of healthflow-agents' AuditSink / InvocationTracker.

Third real implementation of the injection pattern (stdout, JSONL, now DB).
Contract parity: invocation rows are written on success or error, body
exceptions propagate, and failures inside the sink never break the caller.
Each write uses its own short-lived session so it cannot interfere with the
worker's claim transaction.
"""
import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from server.models import AuditEvent, utcnow


def _jsonable(details: dict) -> dict:
    return json.loads(json.dumps(details, default=str))


class DbAuditSink:
    def __init__(self, session_factory: Callable, run_id: uuid.UUID) -> None:
        self.session_factory = session_factory
        self.run_id = run_id

    def log(self, event_type: str, details: dict) -> None:
        try:
            with self.session_factory() as session:
                session.add(AuditEvent(
                    run_id=self.run_id, ts=utcnow(),
                    event_type=event_type, details=_jsonable(details),
                ))
                session.commit()
        except Exception:
            pass


@dataclass
class _InvocationRecord:
    details: dict[str, Any] = field(default_factory=dict)


class DbInvocationTracker:
    def __init__(self, session_factory: Callable, run_id: uuid.UUID) -> None:
        self.session_factory = session_factory
        self.run_id = run_id

    @contextmanager
    def __call__(
        self, *, agent: str, event_type: str, model: str | None = None
    ) -> Iterator[_InvocationRecord]:
        record = _InvocationRecord()
        error: str | None = None
        start = time.monotonic()
        try:
            yield record
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"[:512]
            raise
        finally:
            try:
                with self.session_factory() as session:
                    session.add(AuditEvent(
                        run_id=self.run_id, ts=utcnow(),
                        event_type="agent_invocation", agent=agent, model=model,
                        duration_ms=int((time.monotonic() - start) * 1000),
                        error=error,
                        details=_jsonable(
                            {"invocation_type": event_type, **record.details}
                        ),
                    ))
                    session.commit()
            except Exception:
                pass
