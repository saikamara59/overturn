"""Seed the public read-only demo run: 50 synthetic denials, dry-run drafted.

Synthetic data only — every name, claim id, and dollar figure is invented by
the package's seeded generator.
"""
import uuid
from datetime import date
from typing import Callable

from healthflow_agents.tools.remittance_parser import make_synthetic_denials
from sqlalchemy import select

from overturn.dryrun import DryRunClient
from server.models import Claim, Org, Run
from server.seed import DEFAULT_ORG_NAME
from server.worker import process_run

DEMO_SEED = 2026
DEMO_SIZE = 50


def seed_demo(session_factory: Callable) -> uuid.UUID:
    with session_factory() as session:
        existing = session.scalars(
            select(Run).where(Run.is_demo.is_(True)).limit(1)
        ).first()
        if existing is not None:
            return existing.id

        org = session.scalars(
            select(Org).where(Org.name == DEFAULT_ORG_NAME)
        ).first()
        if org is None:
            org = Org(name=DEFAULT_ORG_NAME)
            session.add(org)
            session.flush()

        records = make_synthetic_denials(
            DEMO_SIZE, seed=DEMO_SEED, base_date=date.today()
        )
        run = Run(
            filename="demo-synthetic.csv", dry_run=True, is_demo=True,
            status="running", total_records=len(records),
            total_billed=round(sum(r.billed_amount for r in records), 2),
            org_id=org.id,
        )
        session.add(run)
        session.flush()
        for r in records:
            session.add(Claim(
                run_id=run.id, claim_id=r.claim_id, payer=r.payer,
                carc_code=r.carc_code, rarc_codes=list(r.rarc_codes),
                billed_amount=r.billed_amount, service_date=r.service_date,
                denial_date=r.denial_date, appeal_deadline=r.appeal_deadline,
                denial_reason_text=r.denial_reason_text,
            ))
        session.commit()
        run_id = run.id

    process_run(run_id, session_factory=session_factory, client=DryRunClient())
    return run_id
