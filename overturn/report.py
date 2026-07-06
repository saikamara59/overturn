"""HTML workbench report: maps a run's worklist.json + audit.jsonl into the
data island consumed by the Denial Workbench template (templates/workbench.html).

Presentation only — CARC descriptions come from the package's DenialCodeDB;
all appeal content comes from the recorded batch result verbatim.
"""
import importlib.resources
import json
from datetime import date, datetime
from pathlib import Path

from healthflow_agents.contracts.denial_record import BatchResult, RecordOutcome
from healthflow_agents.tools.denial_codes import DenialCodeDB

_STATUS_DRAFT = "Draft Ready"
_STATUS_FAILED = "Failed"


def _days_left(outcome: RecordOutcome, today: date) -> int | None:
    deadline = outcome.record.appeal_deadline
    if deadline is None:
        return None
    return (deadline - today).days


def _claim_entry(
    outcome: RecordOutcome, code_db: DenialCodeDB, today: date
) -> dict:
    record = outcome.record
    code_entry = code_db.lookup(record.carc_code)
    appeal = outcome.appeal
    return {
        "id": record.claim_id,
        "payer": record.payer,
        "carc": record.carc_code,
        "carcText": code_entry["description"] if code_entry else None,
        "rarcs": record.rarc_codes,
        "billed": record.billed_amount,
        "dos": record.service_date.isoformat(),
        "denialDate": record.denial_date.isoformat(),
        "deadline": (
            record.appeal_deadline.isoformat() if record.appeal_deadline else None
        ),
        "days": _days_left(outcome, today),
        "status": _STATUS_DRAFT if outcome.success else _STATUS_FAILED,
        "denialText": record.denial_reason_text,
        "letter": appeal.appeal_letter if appeal else None,
        "refined": appeal.refined_recommendation if appeal else None,
        "rule": appeal.argument.cms_rule if appeal else None,
        "error": outcome.error_message,
    }


def _audit_entry(entry: dict) -> dict:
    """One audit.jsonl line -> {time, type, detail} for the trail widget."""
    try:
        time = datetime.fromisoformat(entry["timestamp"]).strftime("%H:%M:%S")
    except (KeyError, ValueError):
        time = "—"
    event_type = entry.get("event_type", "event")
    details = entry.get("details", {}) or {}
    if event_type == "agent_invocation":
        parts = [entry.get("agent", ""), entry.get("invocation_type", "")]
        if entry.get("model_used"):
            parts.append(entry["model_used"])
        if entry.get("error"):
            parts.append(entry["error"])
        detail = " · ".join(p for p in parts if p)
    else:
        detail = " · ".join(f"{k}={v}" for k, v in details.items()) or event_type
    return {"time": time, "type": event_type, "detail": detail[:160]}


def build_report_data(
    payload: dict, audit_entries: list[dict], *, today: date
) -> dict:
    """Assemble the workbench data island from a run's persisted outputs."""
    result = BatchResult.model_validate(payload["batch"])
    order = {cid: i for i, cid in enumerate(payload.get("priority_order", []))}
    outcomes = sorted(
        result.outcomes,
        key=lambda o: order.get(o.record.claim_id, len(order)),
    )

    code_db = DenialCodeDB()
    claims = [_claim_entry(o, code_db, today) for o in outcomes]

    model = next(
        (
            e["model_used"]
            for e in audit_entries
            if e.get("event_type") == "agent_invocation" and e.get("model_used")
        ),
        None,
    )

    return {
        "generatedOn": payload.get("generated_on"),
        "asOf": today.isoformat(),
        "model": model,
        "totalBilled": result.summary.total_billed_amount,
        "claims": claims,
        "summary": {
            "processed": result.summary.total_records,
            "drafts": result.summary.succeeded,
            "failed": result.summary.failed,
        },
        "audit": [_audit_entry(e) for e in audit_entries],
    }


def render_report(data: dict) -> str:
    """Inject the data island into the workbench template."""
    template = (
        importlib.resources.files("overturn.templates")
        .joinpath("workbench.html")
        .read_text(encoding="utf-8")
    )
    # `</` must not terminate the script element early.
    island = json.dumps(data).replace("</", "<\\/")
    return template.replace("/*__OVERTURN_DATA__*/{}", island, 1)


def write_report(
    worklist_path: Path, output_path: Path, *, today: date
) -> Path:
    """Build and write workbench.html from a worklist.json (+ sibling audit)."""
    payload = json.loads(worklist_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "batch" not in payload:
        raise ValueError(f"{worklist_path} is not an Overturn worklist file")

    audit_path = worklist_path.parent / "audit.jsonl"
    audit_entries: list[dict] = []
    if audit_path.exists():
        audit_entries = [
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    data = build_report_data(payload, audit_entries, today=today)
    output_path.write_text(render_report(data), encoding="utf-8")
    return output_path
