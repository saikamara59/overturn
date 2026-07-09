from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.api.deps import get_session
from server.api.runs import _ordered_claims
from server.models import AuditEvent, Run
from server.payloads import audit_entries, worklist_payload

router = APIRouter(prefix="/demo", tags=["demo"])


def _demo_run(session: Session) -> Run:
    run = session.scalars(select(Run).where(Run.is_demo.is_(True)).limit(1)).first()
    if run is None:
        raise HTTPException(status_code=404, detail="demo run not seeded")
    return run


@router.get("/claims")
def demo_claims(session: Session = Depends(get_session)) -> dict:
    run = _demo_run(session)
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.run_id == run.id).order_by(AuditEvent.id)
    ).all()
    return worklist_payload(
        run, _ordered_claims(session, run.id), None, date.today(), audit_entries(list(events))
    )


@router.get("/audit")
def demo_audit(session: Session = Depends(get_session)) -> list[dict]:
    run = _demo_run(session)
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.run_id == run.id).order_by(AuditEvent.id)
    ).all()
    return audit_entries(list(events))
