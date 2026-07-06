"""Tests for terminal presentation: days-remaining formatting and the table."""
from datetime import date

from rich.console import Console

from overturn.render import build_worklist_table, format_days_remaining

TODAY = date(2026, 7, 5)


class TestFormatDaysRemaining:
    def test_future_deadline_shows_days(self) -> None:
        assert format_days_remaining(10.0) == "10"

    def test_overdue_is_flagged(self) -> None:
        assert format_days_remaining(-5.0) == "OVERDUE 5d"

    def test_no_deadline_shows_dash(self) -> None:
        assert format_days_remaining(float("inf")) == "—"


class TestWorklistTable:
    def test_table_shows_records_in_worklist_order(self, tmp_path) -> None:
        from healthflow_agents.tools.remittance_parser import parse_remittance_csv
        from healthflow_agents.contracts.denial_record import RecordOutcome
        from tests.conftest import SAMPLE_CSV

        records = parse_remittance_csv(SAMPLE_CSV)
        outcomes = [
            RecordOutcome(record=r, success=(r.claim_id != "CLM-002"),
                          error_type=None if r.claim_id != "CLM-002" else "APIError",
                          error_message=None if r.claim_id != "CLM-002" else "x")
            for r in records
        ]

        table = build_worklist_table(outcomes, today=TODAY)
        console = Console(record=True, width=200)
        console.print(table)
        text = console.export_text()

        # All seven spec'd columns present.
        for header in ("Claim", "Payer", "CARC", "Billed", "Deadline",
                       "Days Left", "Status"):
            assert header in text
        # Rows render in the order given, with formatted values.
        assert text.index("CLM-001") < text.index("CLM-002") < text.index("CLM-003")
        assert "$12,500.00" in text
        assert "OVERDUE 5d" in text  # CLM-001 vs 2026-07-05
        assert "drafted" in text and "failed" in text
