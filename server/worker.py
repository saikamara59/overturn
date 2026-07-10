"""Worker: Postgres-backed queue loop.

Claims one queued run at a time (FOR UPDATE SKIP LOCKED — multiple workers
never double-claim), then drafts appeals claim-by-claim, committing after
every claim so the claims table is the checkpoint: a crash loses at most the
in-flight claim, and /runs/{id}/retry re-queues only unfinished ones.

Thin-host note: the per-record loop is transport (persistence + progress);
all appeal logic is inside AppealAgent.process_denial_record. Per-record
failure isolation mirrors the package BatchRunner's contract.
"""
import time
import uuid
from typing import Callable

import anthropic
from healthflow_agents import AppealAgent
from healthflow_agents.contracts.denial_record import DenialRecord
from healthflow_agents.tools.denial_codes import DenialCodeDB
from sqlalchemy import select
from sqlalchemy.orm import Session

from overturn.dryrun import DryRunClient
from server.models import Claim, Org, Run, utcnow
from server.sinks import DbAuditSink, DbInvocationTracker

POLL_INTERVAL_SECONDS = 2.0


class OrgKeyError(RuntimeError):
    pass


def _org_of(run: Run, session_factory: Callable) -> Org | None:
    with session_factory() as s:
        return s.get(Org, run.org_id)


def claim_next_run(session: Session) -> uuid.UUID | None:
    run = session.execute(
        select(Run)
        .join(Org, Org.id == Run.org_id)
        .where(Run.status == "queued", Run.is_demo.is_(False),
               Org.status == "active")
        .order_by(Run.created_at)
        .limit(1)
        .with_for_update(skip_locked=True, of=Run)
    ).scalar_one_or_none()
    if run is None:
        return None
    run.status = "running"
    run.started_at = utcnow()
    session.commit()
    return run.id


def _build_agent(
    run: Run, session_factory: Callable, client=None, key_vault=None
) -> AppealAgent:
    kwargs: dict = {
        "audit_sink": DbAuditSink(session_factory, run.id),
        "invocation_tracker": DbInvocationTracker(session_factory, run.id),
    }
    if client is not None:
        kwargs["client"] = client
    elif run.dry_run:
        kwargs["client"] = DryRunClient()
    else:
        org = _org_of(run, session_factory)
        if org is None or not org.anthropic_key_encrypted or key_vault is None:
            raise OrgKeyError("organization has no usable API key")
        try:
            api_key = key_vault.decrypt(org.anthropic_key_encrypted)
        except ValueError as exc:
            raise OrgKeyError("organization has no usable API key") from exc
        kwargs["client"] = anthropic.Anthropic(api_key=api_key)
    return AppealAgent(**kwargs)


def _record_for(claim: Claim) -> DenialRecord:
    return DenialRecord(
        claim_id=claim.claim_id,
        payer=claim.payer,
        carc_code=claim.carc_code,
        rarc_codes=list(claim.rarc_codes or []),
        denial_reason_text=claim.denial_reason_text,
        billed_amount=float(claim.billed_amount),
        service_date=claim.service_date,
        denial_date=claim.denial_date,
        appeal_deadline=claim.appeal_deadline,
    )


def process_run(
    run_id: uuid.UUID, *, session_factory: Callable, client=None, key_vault=None
) -> None:
    code_db = DenialCodeDB()
    with session_factory() as session:
        run = session.get(Run, run_id)
        if run is None:
            return
        try:
            agent = _build_agent(run, session_factory, client, key_vault)
        except OrgKeyError as exc:
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = utcnow()
            session.commit()
            return

        while True:
            claim = session.execute(
                select(Claim)
                .where(Claim.run_id == run_id, Claim.status == "queued")
                .order_by(
                    Claim.appeal_deadline.asc().nulls_last(),
                    Claim.billed_amount.desc(),
                )
                .limit(1)
            ).scalar_one_or_none()
            if claim is None:
                break
            claim.status = "drafting"
            session.commit()

            try:
                _analysis, argument, letter, refined = (
                    agent.process_denial_record(_record_for(claim))
                )
            except Exception as exc:
                claim.status = "failed"
                claim.error = f"{type(exc).__name__}: {exc}"[:512]
                run.failed_records += 1
            else:
                entry = code_db.lookup(claim.carc_code)
                claim.carc_text = entry["description"] if entry else None
                claim.letter = letter
                claim.letter_original = letter
                claim.refined = refined
                claim.rule = argument.cms_rule
                claim.status = "draft_ready"
                run.drafted += 1
            claim.updated_at = utcnow()
            session.commit()

        run.status = (
            "completed" if run.drafted > 0 or run.total_records == 0 else "failed"
        )
        if run.status == "failed":
            run.error = "all records failed"
        run.finished_at = utcnow()
        session.commit()


def run_worker_loop(
    session_factory: Callable,
    *,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    max_iterations: int | None = None,
    client=None,
    key_vault=None,
) -> None:
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        with session_factory() as session:
            run_id = claim_next_run(session)
        if run_id is not None:
            process_run(
                run_id, session_factory=session_factory, client=client,
                key_vault=key_vault,
            )
        else:
            time.sleep(poll_interval)


def main() -> None:  # pragma: no cover - production entrypoint
    from server.config import get_settings
    from server.crypto import KeyVault
    from server.db import make_engine, make_session_factory

    settings = get_settings()
    factory = make_session_factory(make_engine(settings.database_url))
    vault = KeyVault(settings.key_encryption_secret)
    print("overturn worker: polling for queued runs")
    run_worker_loop(factory, key_vault=vault)


if __name__ == "__main__":  # pragma: no cover
    main()
