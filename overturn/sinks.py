"""JSONL implementations of healthflow-agents' injected logging protocols.

Overturn's second real implementation of the injection pattern: every audit
event and agent invocation lands as one JSON line in audit.jsonl under the
run's output directory. Mirrors the package's stdout defaults contractually —
invocation records are written on exit whether the body succeeded or raised,
body exceptions propagate, and failures in the sink itself never break the
wrapped operation.
"""
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class JsonlAuditSink:
    """AuditSink writing one JSON line per event to a .jsonl file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def log(self, event_type: str, details: dict) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "details": details,
        }
        _append_line(self.path, entry)


@dataclass
class _InvocationRecord:
    """Mutable record yielded to the wrapped block; exposes `details`."""

    details: dict[str, Any] = field(default_factory=dict)


class JsonlInvocationTracker:
    """InvocationTracker writing one JSON line per agent invocation."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def __call__(
        self,
        *,
        agent: str,
        event_type: str,
        model: str | None = None,
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
            _append_line(self.path, {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": "agent_invocation",
                "agent": agent,
                "invocation_type": event_type,
                "model_used": model,
                "details": record.details,
                "error": error,
                "duration_ms": int((time.monotonic() - start) * 1000),
            })


def _append_line(path: Path, entry: dict) -> None:
    """Append one JSON line; sink failures must never break the caller."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        pass
