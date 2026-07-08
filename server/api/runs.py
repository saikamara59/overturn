import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from healthflow_agents.tools.remittance_parser import (
    RemittanceParseError,
    parse_remittance_csv,
    parse_remittance_json,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.api.deps import get_session
from server.models import Claim, Run
from server.payloads import run_payload
from server.security import require_user

router = APIRouter(prefix="/runs", tags=["runs"])


def get_run_or_404(session: Session, run_id: uuid.UUID) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.post("", status_code=202)
async def create_run(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Form(False),
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
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
    if not dry_run and not settings.anthropic_api_key:
        raise HTTPException(
            422,
            detail="ANTHROPIC_API_KEY is not configured on this server; upload with dry_run",
        )

    run = Run(
        filename=file.filename or "upload",
        dry_run=dry_run,
        total_records=len(records),
        total_billed=round(sum(r.billed_amount for r in records), 2),
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
    _user: str = Depends(require_user),
) -> list[dict]:
    runs = session.scalars(select(Run).order_by(Run.created_at.desc())).all()
    return [run_payload(r) for r in runs]


@router.get("/{run_id}")
def get_run(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
) -> dict:
    return run_payload(get_run_or_404(session, run_id))


@router.post("/{run_id}/retry")
def retry_run(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
) -> dict:
    run = get_run_or_404(session, run_id)
    if run.is_demo:
        raise HTTPException(409, detail="demo run is read-only")
    requeued = 0
    for claim in run.claims:
        if claim.status not in ("draft_ready", "submitted"):
            claim.status = "queued"
            claim.error = None
            requeued += 1
    if requeued:
        run.status = "queued"
        run.error = None
        run.finished_at = None
    return {"requeued": requeued}
