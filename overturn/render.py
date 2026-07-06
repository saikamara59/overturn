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
