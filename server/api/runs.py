import io
import uuid
import zipfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from healthflow_agents.tools.remittance_parser import (
    RemittanceParseError,
    parse_remittance_csv,
    parse_remittance_json,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.api.deps import OrgContext, current_org, get_session, scoped_run
from server.models import AuditEvent, Claim, Run
from server.payloads import audit_entries, letter_markdown, run_payload, worklist_payload

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", status_code=202)
async def create_run(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Form(False),
    session: Session = Depends(get_session),
    ctx: OrgContext = Depends(current_org),
) -> dict:
    settings = request.app.state.settings
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".csv", ".json"):
        raise HTTPException(415, detail=f"unsupported file type {suffix!r} (use .csv or .json)")

    text = (await file.read()).decode("utf-8", errors="replace")
    try:
        records = (
            parse_remittance_csv(text) if suffix == ".csv" else parse_remittance_json(text)
        )
    except RemittanceParseError as exc:
        raise HTTPException(422, detail=str(exc))
    except ValueError as exc:  # includes json.JSONDecodeError
        raise HTTPException(422, detail=f"could not parse file: {exc}")
    if not records:
        raise HTTPException(422, detail="file contains no denial records")
    if len(records) > settings.max_upload_records:
        raise HTTPException(
            413,
            detail=(
                f"{len(records)} records exceeds the per-upload cap of "
                f"{settings.max_upload_records}"
            ),
        )
    if not dry_run and not ctx.org.anthropic_key_encrypted:
        raise HTTPException(
            422,
            detail=(
                "organization has no API key configured; upload with dry_run "
                "or add a key in Org Settings"
            ),
        )

    run = Run(
        filename=file.filename or "upload",
        dry_run=dry_run,
        total_records=len(records),
        total_billed=round(sum(r.billed_amount for r in records), 2),
        org_id=ctx.org.id,
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
    return {"runId": str(run.id)}


@router.get("")
def list_runs(
    session: Session = Depends(get_session),
    ctx: OrgContext = Depends(current_org),
) -> list[dict]:
    runs = session.scalars(
        select(Run).where(Run.org_id == ctx.org.id).order_by(Run.created_at.desc())
    ).all()
    return [run_payload(r) for r in runs]


@router.get("/{run_id}")
def get_run(run: Run = Depends(scoped_run)) -> dict:
    return run_payload(run)


@router.post("/{run_id}/retry")
def retry_run(run: Run = Depends(scoped_run)) -> dict:
    if run.is_demo:
        raise HTTPException(409, detail="demo run is read-only")
    requeued = 0
    for claim in run.claims:
        if claim.status not in ("draft_ready", "submitted", "dismissed"):
            claim.status = "queued"
            claim.error = None
            requeued += 1
    if requeued:
        run.status = "queued"
        run.error = None
        run.finished_at = None
    run.drafted = sum(1 for c in run.claims if c.status in ("draft_ready", "submitted"))
    run.failed_records = sum(1 for c in run.claims if c.status == "failed")
    return {"requeued": requeued}


def _ordered_claims(session: Session, run_id: uuid.UUID) -> list[Claim]:
    return list(session.scalars(
        select(Claim)
        .where(Claim.run_id == run_id)
        .order_by(Claim.appeal_deadline.asc().nulls_last(), Claim.billed_amount.desc())
    ))


@router.get("/{run_id}/claims")
def run_claims(
    run: Run = Depends(scoped_run),
    session: Session = Depends(get_session),
) -> dict:
    model = session.scalars(
        select(AuditEvent.model)
        .where(AuditEvent.run_id == run.id, AuditEvent.model.is_not(None))
        .order_by(AuditEvent.id)
        .limit(1)
    ).first()
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.run_id == run.id).order_by(AuditEvent.id)
    ).all()
    return worklist_payload(
        run, _ordered_claims(session, run.id), model, date.today(), audit_entries(list(events))
    )


@router.get("/{run_id}/audit")
def run_audit(
    run: Run = Depends(scoped_run),
    session: Session = Depends(get_session),
) -> list[dict]:
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.run_id == run.id).order_by(AuditEvent.id)
    ).all()
    return audit_entries(list(events))


@router.get("/{run_id}/letters.zip")
def run_letters_zip(
    run: Run = Depends(scoped_run),
    session: Session = Depends(get_session),
) -> Response:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for claim in _ordered_claims(session, run.id):
            if claim.letter:
                z.writestr(f"{claim.claim_id}-appeal.md", letter_markdown(claim))
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="letters.zip"'},
    )
