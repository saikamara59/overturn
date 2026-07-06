"""Tests for Overturn's JSONL implementations of the package logging protocols."""
import json
from pathlib import Path

import pytest
from healthflow_agents.core.logging import AuditSink

from overturn.sinks import JsonlAuditSink, JsonlInvocationTracker


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


class TestJsonlAuditSink:
    def test_satisfies_package_protocol(self, tmp_path: Path) -> None:
        sink = JsonlAuditSink(tmp_path / "audit.jsonl")
        assert isinstance(sink, AuditSink)

    def test_log_appends_one_json_line_per_event(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        sink = JsonlAuditSink(path)

        sink.log("phi_redacted", {"names": 2})
        sink.log("batch_started", {"records": 5})

        entries = read_jsonl(path)
        assert len(entries) == 2
        assert entries[0]["event_type"] == "phi_redacted"
        assert entries[0]["details"] == {"names": 2}
        assert "timestamp" in entries[0]
        assert entries[1]["event_type"] == "batch_started"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "audit.jsonl"
        JsonlAuditSink(path).log("event", {})
        assert read_jsonl(path)[0]["event_type"] == "event"

    def test_serializes_non_json_details(self, tmp_path: Path) -> None:
        from datetime import date

        path = tmp_path / "audit.jsonl"
        JsonlAuditSink(path).log("event", {"when": date(2026, 7, 5)})
        assert read_jsonl(path)[0]["details"]["when"] == "2026-07-05"


class TestJsonlInvocationTracker:
    def test_records_successful_invocation(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        tracker = JsonlInvocationTracker(path)

        with tracker(agent="appeal", event_type="process_appeal", model="m1") as inv:
            inv.details = {"code": "CO-50"}

        (entry,) = read_jsonl(path)
        assert entry["event_type"] == "agent_invocation"
        assert entry["agent"] == "appeal"
        assert entry["invocation_type"] == "process_appeal"
        assert entry["model_used"] == "m1"
        assert entry["details"] == {"code": "CO-50"}
        assert entry["error"] is None
        assert isinstance(entry["duration_ms"], int)

    def test_error_is_recorded_and_exception_propagates(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        tracker = JsonlInvocationTracker(path)

        with pytest.raises(ValueError, match="boom"):
            with tracker(agent="appeal", event_type="run_batch"):
                raise ValueError("boom")

        (entry,) = read_jsonl(path)
        assert entry["error"] == "ValueError: boom"
        assert entry["model_used"] is None

    def test_tracker_write_failure_never_breaks_wrapped_operation(
        self, tmp_path: Path
    ) -> None:
        # A directory at the target path makes the JSONL append raise.
        path = tmp_path / "audit.jsonl"
        path.mkdir()
        tracker = JsonlInvocationTracker(path)

        with tracker(agent="appeal", event_type="process_appeal") as inv:
            inv.details = {"ok": True}  # must complete without raising
