"""Wiring between the CLI and healthflow-agents: agent construction, batch
execution, and results persistence. No appeal logic lives here."""
import json
from datetime import date
from pathlib import Path
from typing import Sequence

from healthflow_agents import AppealAgent
from healthflow_agents.batch.prioritize import prioritize_worklist
from healthflow_agents.batch.runner import BatchRunner
from healthflow_agents.contracts.denial_record import (
    BatchResult,
    DenialRecord,
    RecordOutcome,
)

from overturn.dryrun import DryRunClient
from overturn.sinks import JsonlAuditSink, JsonlInvocationTracker

WORKLIST_SCHEMA = "overturn.worklist/v1"


def build_agent(audit_path: Path, *, dry_run: bool) -> AppealAgent:
    """Construct AppealAgent with Overturn's JSONL sinks injected.

    In dry-run mode the package-supported `client` injection point receives
    a stub, so no API key or network access is needed.
    """
    kwargs: dict = {
        "audit_sink": JsonlAuditSink(audit_path),
        "invocation_tracker": JsonlInvocationTracker(audit_path),
    }
    if dry_run:
        kwargs["client"] = DryRunClient()
    return AppealAgent(**kwargs)


def run_batch(
    records: Sequence[DenialRecord],
    *,
    agent: AppealAgent,
    today: date,
) -> tuple[BatchResult, list[RecordOutcome]]:
    """Run the batch and rank outcomes into a worklist (most urgent first)."""
    result = BatchRunner(agent).run(records)
    worklist = prioritize_worklist(result, today=today)
    return result, worklist


def worklist_payload(
    result: BatchResult, worklist: Sequence[RecordOutcome], *, today: date
) -> dict:
    """The worklist.json document: full BatchResult plus priority order."""
    return {
        "schema": WORKLIST_SCHEMA,
        "generated_on": today.isoformat(),
        "priority_order": [o.record.claim_id for o in worklist],
        "batch": result.model_dump(mode="json"),
    }


def write_results(
    output_dir: Path,
    result: BatchResult,
    worklist: Sequence[RecordOutcome],
    *,
    today: date,
) -> Path:
    """Write worklist.json and one appeal letter per drafted record.

    Returns the worklist.json path.
    """
    appeals_dir = output_dir / "appeals"
    appeals_dir.mkdir(parents=True, exist_ok=True)

    worklist_path = output_dir / "worklist.json"
    worklist_path.write_text(
        json.dumps(worklist_payload(result, worklist, today=today), indent=2),
        encoding="utf-8",
    )

    for outcome in result.outcomes:
        if outcome.appeal is None:
            continue
        letter_path = appeals_dir / f"{outcome.record.claim_id}.md"
        letter_path.write_text(
            _letter_markdown(outcome), encoding="utf-8"
        )
    return worklist_path


def _letter_markdown(outcome: RecordOutcome) -> str:
    """Package the letter and refined recommendation as one markdown file."""
    assert outcome.appeal is not None
    record = outcome.record
    return (
        f"# Appeal — claim {record.claim_id} ({record.carc_code}, {record.payer})\n\n"
        f"{outcome.appeal.appeal_letter}\n\n"
        "---\n\n"
        "## Refined recommendation\n\n"
        f"{outcome.appeal.refined_recommendation}\n"
    )
