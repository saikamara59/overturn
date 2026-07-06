"""Terminal presentation: the prioritized worklist as a rich table."""
from datetime import date
from typing import Sequence

from healthflow_agents.batch.prioritize import days_until_deadline
from healthflow_agents.contracts.denial_record import RecordOutcome
from rich.table import Table


def format_days_remaining(days: float) -> str:
    """Human form of prioritize.days_until_deadline output."""
    if days == float("inf"):
        return "—"
    if days < 0:
        return f"OVERDUE {int(-days)}d"
    return str(int(days))


def format_money(amount: float) -> str:
    return f"${amount:,.2f}"


DEADLINE_BUCKETS = ("Overdue", "<7 days", "<30 days", "30+ days", "No deadline")


def deadline_bucket(days: float) -> str:
    """Bucket a days_until_deadline value for the summary view."""
    if days == float("inf"):
        return "No deadline"
    if days < 0:
        return "Overdue"
    if days < 7:
        return "<7 days"
    if days < 30:
        return "<30 days"
    return "30+ days"


def build_carc_table(
    records_by_carc: dict[str, int], billed_by_carc: dict[str, float]
) -> Table:
    """Per-CARC rollup, largest dollars first."""
    table = Table(title="Records by CARC group")
    table.add_column("CARC", no_wrap=True)
    table.add_column("Records", justify="right")
    table.add_column("Billed", justify="right")
    for carc in sorted(billed_by_carc, key=billed_by_carc.get, reverse=True):
        table.add_row(
            carc, str(records_by_carc[carc]), format_money(billed_by_carc[carc])
        )
    return table


def build_deadline_table(
    outcomes: Sequence[RecordOutcome], *, today: date
) -> Table:
    """Deadline-proximity buckets over a batch's records."""
    counts = {bucket: 0 for bucket in DEADLINE_BUCKETS}
    billed = {bucket: 0.0 for bucket in DEADLINE_BUCKETS}
    for outcome in outcomes:
        bucket = deadline_bucket(days_until_deadline(outcome.record, today=today))
        counts[bucket] += 1
        billed[bucket] += outcome.record.billed_amount

    table = Table(title=f"Appeal deadlines (as of {today})")
    table.add_column("Bucket")
    table.add_column("Records", justify="right")
    table.add_column("Billed", justify="right")
    for bucket in DEADLINE_BUCKETS:
        style = "red" if bucket == "Overdue" and counts[bucket] else None
        table.add_row(
            bucket, str(counts[bucket]), format_money(billed[bucket]), style=style
        )
    return table


def build_worklist_table(
    worklist: Sequence[RecordOutcome], *, today: date
) -> Table:
    """Render worklist outcomes (already prioritized) as the spec'd table."""
    table = Table(title=f"Appeal worklist — most urgent first (as of {today})")
    table.add_column("Claim", no_wrap=True)
    table.add_column("Payer")
    table.add_column("CARC", no_wrap=True)
    table.add_column("Billed", justify="right")
    table.add_column("Deadline", no_wrap=True)
    table.add_column("Days Left", justify="right")
    table.add_column("Status")

    for outcome in worklist:
        record = outcome.record
        days = days_until_deadline(record, today=today)
        days_text = format_days_remaining(days)
        status = "drafted" if outcome.success else "failed"
        style = "red" if days < 0 else ("yellow" if days <= 7 else None)
        table.add_row(
            record.claim_id,
            record.payer,
            record.carc_code,
            format_money(record.billed_amount),
            record.appeal_deadline.isoformat() if record.appeal_deadline else "—",
            days_text,
            status,
            style=style,
        )
    return table
