import pytest
from healthflow_agents.core.logging import AuditSink

from server.models import AuditEvent, Run
from server.sinks import DbAuditSink, DbInvocationTracker


@pytest.fixture()
def run_id(session_factory):
    with session_factory() as s:
        run = Run(filename="f.csv")
        s.add(run)
        s.commit()
        return run.id


def events(session_factory):
    with session_factory() as s:
        return s.query(AuditEvent).order_by(AuditEvent.id).all()


def test_satisfies_protocol_and_writes_rows(session_factory, run_id):
    sink = DbAuditSink(session_factory, run_id)
    assert isinstance(sink, AuditSink)
    sink.log("phi_redacted", {"count": 2})
    sink.log("batch_started", {"records": 5})
    evs = events(session_factory)
    assert [e.event_type for e in evs] == ["phi_redacted", "batch_started"]
    assert evs[0].details == {"count": 2}


def test_non_json_details_are_stringified(session_factory, run_id):
    from datetime import date

    DbAuditSink(session_factory, run_id).log("e", {"when": date(2026, 7, 8)})
    assert events(session_factory)[0].details["when"] == "2026-07-08"


def test_tracker_records_success(session_factory, run_id):
    tracker = DbInvocationTracker(session_factory, run_id)
    with tracker(agent="appeal", event_type="process_denial_record", model="m1") as inv:
        inv.details = {"code": "CO-50"}
    (ev,) = events(session_factory)
    assert ev.event_type == "agent_invocation"
    assert ev.agent == "appeal"
    assert ev.model == "m1"
    assert ev.details["invocation_type"] == "process_denial_record"
    assert ev.details["code"] == "CO-50"
    assert ev.error is None and isinstance(ev.duration_ms, int)


def test_tracker_records_error_and_propagates(session_factory, run_id):
    tracker = DbInvocationTracker(session_factory, run_id)
    with pytest.raises(ValueError, match="boom"):
        with tracker(agent="appeal", event_type="run"):
            raise ValueError("boom")
    (ev,) = events(session_factory)
    assert ev.error == "ValueError: boom"


def test_sink_failure_never_breaks_caller(run_id):
    def broken_factory():
        raise RuntimeError("db down")

    DbAuditSink(broken_factory, run_id).log("e", {})  # must not raise
    tracker = DbInvocationTracker(broken_factory, run_id)
    with tracker(agent="a", event_type="t") as inv:
        inv.details = {"ok": True}  # must complete without raising
