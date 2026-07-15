import csv
import io
import json
import uuid
import zipfile
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from healthflow_agents.tools.remittance_parser import (
    RemittanceParseError,
    parse_remittance_csv,
    parse_remittance_json,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.api.deps import OrgContext, current_org, get_session, scoped_run
from server.api.org import upsert_csv_mapping
from server.ingest import apply_mapping
from server.models import AuditEvent, Claim, Org, Run, utcnow
from server.payloads import audit_entries, letter_markdown, run_payload, worklist_payload

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", status_code=202)
async def create_run(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Form(False),
    mapping: Optional[str] = Form(None),
    save_mapping: bool = Form(False),
    session: Session = Depends(get_session),
    ctx: OrgContext = Depends(current_org),
) -> dict:
    settings = request.app.state.settings
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".csv", ".json"):
        raise HTTPException(415, detail=f"unsupported file type {suffix!r} (use .csv or .json)")

    text = (await file.read()).decode("utf-8", errors="replace")
    if mapping is not None:
        if suffix != ".csv":
            raise HTTPException(422, detail="mapping applies to CSV uploads only")
        try:
            mapping_obj = json.loads(mapping)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, detail=f"mapping is not valid JSON: {exc}")
        if not isinstance(mapping_obj, dict):
            raise HTTPException(422, detail="mapping must be a JSON object of {field: column}")
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []
        rows = list(reader)
        try:
            mapped = apply_mapping(
                headers, rows, mapping_obj,
                default_appeal_days=ctx.org.default_appeal_days,
            )
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc))
        if mapped.errors:
            raise HTTPException(422, detail={
                "errors": [e.as_dict() for e in mapped.errors[:20]],
                "totalErrors": len(mapped.errors),
            })
        records = mapped.records
        import_notes = mapped.notes
        if save_mapping:
            upsert_csv_mapping(session, ctx.org.id, headers, mapping_obj)
    else:
        import_notes = []
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
    if import_notes:
        session.add(AuditEvent(
            run_id=run.id, ts=utcnow(), event_type="csv_import_notes",
            details={"count": len(import_notes),
                     "notes": [n.as_dict() for n in import_notes[:20]]},
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


class GenerateRequest(BaseModel):
    claimIds: list[str]


GENERATABLE = ("draft_ready", "failed")


@router.post("/{run_id}/generate")
def generate_appeals(
    body: GenerateRequest,
    run: Run = Depends(scoped_run),
    session: Session = Depends(get_session),
) -> dict:
    """Requeue selected claims for (re)drafting; the worker picks them up."""
    if run.is_demo:
        raise HTTPException(409, detail="demo run is read-only")
    if not body.claimIds:
        raise HTTPException(422, detail="claimIds must not be empty")
    if not run.dry_run:
        org = session.get(Org, run.org_id)
        if org is None or not org.anthropic_key_encrypted:
            raise HTTPException(
                422,
                detail=(
                    "organization has no API key configured; add a key in "
                    "Org Settings or re-upload as a dry run"
                ),
            )
    try:
        wanted = {uuid.UUID(cid) for cid in body.claimIds}
    except ValueError:
        raise HTTPException(422, detail="claimIds must be claim UUIDs")
    by_id = {c.id: c for c in run.claims}
    unknown = wanted - by_id.keys()
    if unknown:
        raise HTTPException(422, detail=f"{len(unknown)} claim id(s) not in this run")

    queued_ids: list[str] = []
    skipped = 0
    for cid in wanted:
        claim = by_id[cid]
        if claim.status in GENERATABLE:
            claim.status = "queued"
            claim.error = None
            claim.updated_at = utcnow()
            queued_ids.append(claim.claim_id)
        else:
            skipped += 1
    if queued_ids:
        run.status = "queued"
        run.error = None
        run.finished_at = None
        # mirror retry: recompute so the worker's increments stay correct
        run.drafted = sum(1 for c in run.claims if c.status in ("draft_ready", "submitted"))
        run.failed_records = sum(1 for c in run.claims if c.status == "failed")
        session.add(AuditEvent(
            run_id=run.id, ts=utcnow(), event_type="regeneration_requested",
            details={"count": len(queued_ids), "claim_ids": sorted(queued_ids)[:20]},
        ))
    return {"queued": len(queued_ids), "skipped": skipped}


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
            if claim.letter and claim.status != "dismissed":
                z.writestr(f"{claim.claim_id}-appeal.md", letter_markdown(claim))
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="letters.zip"'},
    )
