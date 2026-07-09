from datetime import date
from types import SimpleNamespace

import pytest
from healthflow_agents.tools.remittance_parser import make_synthetic_denials

from overturn.dryrun import DRY_RUN_NOTE, DryRunClient
from server.models import AuditEvent, Claim, Run
from server.worker import claim_next_run, process_run, run_worker_loop


def seed_run(session_factory, n=3, **run_over):
    records = make_synthetic_denials(n, seed=7, base_date=date(2026, 7, 8))
    with session_factory() as s:
        run = Run(filename="r.csv", dry_run=True, total_records=n,
                  total_billed=round(sum(r.billed_amount for r in records), 2),
                  **run_over)
        s.add(run)
        s.flush()
        for r in records:
            s.add(Claim(
                run_id=run.id, claim_id=r.claim_id, payer=r.payer,
                carc_code=r.carc_code, rarc_codes=list(r.rarc_codes),
                billed_amount=r.billed_amount, service_date=r.service_date,
                denial_date=r.denial_date, appeal_deadline=r.appeal_deadline,
                denial_reason_text=r.denial_reason_text,
            ))
        s.commit()
        return run.id


def test_claim_next_run_claims_oldest_and_marks_running(session_factory):
    run_id = seed_run(session_factory)
    with session_factory() as s:
        assert claim_next_run(s) == run_id
    with session_factory() as s:
        assert s.get(Run, run_id).status == "running"
        assert s.get(Run, run_id).started_at is not None
        assert claim_next_run(s) is None  # nothing left queued


def test_claim_next_run_skips_demo_runs(session_factory):
    seed_run(session_factory, is_demo=True)
    with session_factory() as s:
        assert claim_next_run(s) is None


def test_process_run_drafts_all_claims_and_updates_counters(session_factory):
    run_id = seed_run(session_factory)
    with session_factory() as s:
        claim_next_run(s)
    process_run(run_id, session_factory=session_factory, client=DryRunClient())
    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == "completed"
        assert run.drafted == 3 and run.failed_records == 0
        assert run.finished_at is not None
        for c in s.query(Claim).all():
            assert c.status == "draft_ready"
            assert c.letter and c.letter == c.letter_original
            assert c.refined == DRY_RUN_NOTE
            assert c.rule
        assert s.query(AuditEvent).filter_by(event_type="agent_invocation").count() >= 3


def test_process_run_isolates_failures_per_claim(session_factory):
    run_id = seed_run(session_factory)

    class ExplodingClient:
        calls = 0

        @property
        def messages(self):
            outer = self

            class M:
                def create(self, **kwargs):
                    outer.calls += 1
                    if outer.calls == 1:
                        raise RuntimeError("api down")
                    return SimpleNamespace(
                        content=[SimpleNamespace(text="refined")]
                    )
            return M()

    with session_factory() as s:
        claim_next_run(s)
    process_run(run_id, session_factory=session_factory, client=ExplodingClient())
    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == "completed"          # some succeeded
        assert run.drafted == 2 and run.failed_records == 1
        failed = [c for c in s.query(Claim).all() if c.status == "failed"]
        assert len(failed) == 1 and "RuntimeError" in failed[0].error


def test_process_run_all_failures_marks_run_failed(session_factory):
    run_id = seed_run(session_factory, n=2)

    class AlwaysBroken:
        @property
        def messages(self):
            class M:
                def create(self, **kwargs):
                    raise RuntimeError("no")
            return M()

    with session_factory() as s:
        claim_next_run(s)
    process_run(run_id, session_factory=session_factory, client=AlwaysBroken())
    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == "failed"
        assert run.failed_records == 2


def test_worker_loop_processes_queued_run(session_factory):
    run_id = seed_run(session_factory)
    run_worker_loop(
        session_factory, poll_interval=0.01, max_iterations=3,
        client=DryRunClient(),
    )
    with session_factory() as s:
        assert s.get(Run, run_id).status == "completed"
