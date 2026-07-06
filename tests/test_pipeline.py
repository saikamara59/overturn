"""Tests for pipeline wiring: agent construction, batch run, results writing."""
import json
from datetime import date
from pathlib import Path

from healthflow_agents.tools.remittance_parser import make_synthetic_denials

from overturn.dryrun import DRY_RUN_NOTE, DryRunClient
from overturn.pipeline import build_agent, run_batch, write_results
from overturn.sinks import JsonlAuditSink, JsonlInvocationTracker

TODAY = date(2026, 7, 5)


def make_dry_agent(tmp_path: Path):
    return build_agent(tmp_path / "audit.jsonl", dry_run=True)


class TestBuildAgent:
    def test_wires_jsonl_sinks_and_stub_client(self, tmp_path: Path) -> None:
        agent = make_dry_agent(tmp_path)
        assert isinstance(agent.audit, JsonlAuditSink)
        assert isinstance(agent.invocations, JsonlInvocationTracker)
        assert isinstance(agent.client, DryRunClient)


class TestRunBatch:
    def test_processes_records_and_prioritizes(self, tmp_path: Path) -> None:
        records = make_synthetic_denials(4, seed=7)
        agent = make_dry_agent(tmp_path)

        result, worklist = run_batch(records, agent=agent, today=TODAY)

        assert result.summary.total_records == 4
        assert result.summary.succeeded == 4
        assert len(worklist) == 4
        # Every successful outcome carries a letter and the dry-run marker.
        for outcome in worklist:
            assert outcome.appeal is not None
            assert outcome.appeal.appeal_letter
            assert outcome.appeal.refined_recommendation == DRY_RUN_NOTE

    def test_audit_jsonl_captures_batch_events(self, tmp_path: Path) -> None:
        records = make_synthetic_denials(2, seed=1)
        agent = make_dry_agent(tmp_path)

        run_batch(records, agent=agent, today=TODAY)

        events = [
            json.loads(line)["event_type"]
            for line in (tmp_path / "audit.jsonl").read_text().splitlines()
        ]
        assert "batch_started" in events
        assert "batch_completed" in events
        assert "phi_redacted" in events
        assert "agent_invocation" in events


class TestWriteResults:
    def test_writes_worklist_json_and_appeal_letters(self, tmp_path: Path) -> None:
        records = make_synthetic_denials(3, seed=3)
        agent = make_dry_agent(tmp_path)
        result, worklist = run_batch(records, agent=agent, today=TODAY)
        out = tmp_path / "results"

        write_results(out, result, worklist, today=TODAY)

        payload = json.loads((out / "worklist.json").read_text())
        assert payload["generated_on"] == "2026-07-05"
        assert payload["batch"]["summary"]["total_records"] == 3
        assert payload["priority_order"] == [o.record.claim_id for o in worklist]

        letters = sorted((out / "appeals").glob("*.md"))
        assert len(letters) == 3
        assert letters[0].stem in {r.claim_id for r in records}
        assert "Formal Appeal" in letters[0].read_text()

    def test_failed_records_get_no_letter(self, tmp_path: Path) -> None:
        from healthflow_agents.contracts.denial_record import (
            BatchResult, RecordOutcome)
        from healthflow_agents.batch.runner import summarize_outcomes

        record = make_synthetic_denials(1, seed=5)[0]
        outcome = RecordOutcome(
            record=record, success=False,
            error_type="RuntimeError", error_message="synthetic failure",
        )
        result = BatchResult(
            outcomes=[outcome], summary=summarize_outcomes([outcome])
        )
        out = tmp_path / "results"

        write_results(out, result, [outcome], today=TODAY)

        assert not list((out / "appeals").glob("*.md"))
        payload = json.loads((out / "worklist.json").read_text())
        assert payload["batch"]["summary"]["failed"] == 1
