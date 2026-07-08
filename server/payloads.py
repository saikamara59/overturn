"""JSON payload builders. camelCase keys; claim entries reuse the static
report's island shape (see Task 6) so workbench components work unchanged."""
from datetime import date, datetime

from server.models import AuditEvent, Claim, Run


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def run_payload(run: Run) -> dict:
    return {
        "id": str(run.id),
        "filename": run.filename,
        "dryRun": run.dry_run,
        "isDemo": run.is_demo,
        "status": run.status,
        "totalRecords": run.total_records,
        "drafted": run.drafted,
        "failedRecords": run.failed_records,
        "totalBilled": float(run.total_billed),
        "error": run.error,
        "createdAt": _iso(run.created_at),
        "startedAt": _iso(run.started_at),
        "finishedAt": _iso(run.finished_at),
    }


DISPLAY_STATUS = {
    "queued": "Queued",
    "drafting": "Drafting",
    "draft_ready": "Draft Ready",
    "failed": "Failed",
    "submitted": "Submitted",
}


def claim_entry(claim: Claim, today: date) -> dict:
    days = (claim.appeal_deadline - today).days if claim.appeal_deadline else None
    return {
        "id": claim.claim_id,
        "dbId": str(claim.id),
        "payer": claim.payer,
        "carc": claim.carc_code,
        "carcText": claim.carc_text,
        "rarcs": list(claim.rarc_codes or []),
        "billed": float(claim.billed_amount),
        "dos": claim.service_date.isoformat(),
        "denialDate": claim.denial_date.isoformat(),
        "deadline": claim.appeal_deadline.isoformat() if claim.appeal_deadline else None,
        "days": days,
        "status": DISPLAY_STATUS[claim.status],
        "denialText": claim.denial_reason_text,
        "letter": claim.letter,
        "refined": claim.refined,
        "rule": claim.rule,
        "error": claim.error,
    }


def worklist_payload(
    run: Run, claims: list[Claim], model: str | None, today: date
) -> dict:
    return {
        "generatedOn": run.created_at.date().isoformat(),
        "asOf": today.isoformat(),
        "model": model,
        "totalBilled": float(run.total_billed),
        "claims": [claim_entry(c, today) for c in claims],
        "summary": {
            "processed": run.total_records,
            "drafts": run.drafted,
            "failed": run.failed_records,
        },
    }


def audit_entries(events: list[AuditEvent]) -> list[dict]:
    out = []
    for e in events:
        if e.event_type == "agent_invocation":
            parts = [e.agent, (e.details or {}).get("invocation_type"), e.model, e.error]
            detail = " · ".join(str(p) for p in parts if p)
        else:
            detail = " · ".join(f"{k}={v}" for k, v in (e.details or {}).items()) or e.event_type
        out.append({
            "time": e.ts.strftime("%H:%M:%S"),
            "type": e.event_type,
            "detail": detail[:160],
        })
    return out


def letter_markdown(claim: Claim) -> str:
    body = (
        f"# Appeal — claim {claim.claim_id} ({claim.carc_code}, {claim.payer})\n\n"
        f"{claim.letter or ''}\n"
    )
    if claim.refined:
        body += f"\n---\n\n## Refined recommendation\n\n{claim.refined}\n"
    return body
