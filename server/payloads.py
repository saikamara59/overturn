"""JSON payload builders. camelCase keys; claim entries reuse the static
report's island shape (see Task 6) so workbench components work unchanged."""
from server.models import Run


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
