"""Tests for the `overturn run` CLI command (LLM path stubbed via --dry-run)."""
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from overturn.cli import app
from tests.conftest import AS_OF

runner = CliRunner()


def run_cli(*args: str) -> "Result":  # noqa: F821 - click Result
    return runner.invoke(app, list(args))


class TestRunCommand:
    def test_dry_run_prints_table_and_writes_results(
        self, sample_csv: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "out"
        result = run_cli(
            "run", str(sample_csv), "--dry-run",
            "--output-dir", str(out), "--as-of", AS_OF,
        )

        assert result.exit_code == 0, result.output
        # Worklist order: overdue CLM-001 first, no-deadline CLM-003 last.
        assert result.output.index("CLM-001") < result.output.index("CLM-002")
        assert result.output.index("CLM-002") < result.output.index("CLM-003")
        assert "OVERDUE" in result.output

        assert (out / "worklist.json").exists()
        assert (out / "audit.jsonl").exists()
        assert len(list((out / "appeals").glob("*.md"))) == 3

    def test_limit_processes_first_n_records(
        self, sample_csv: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "out"
        result = run_cli(
            "run", str(sample_csv), "--dry-run", "--limit", "2",
            "--output-dir", str(out), "--as-of", AS_OF,
        )

        assert result.exit_code == 0, result.output
        payload = json.loads((out / "worklist.json").read_text())
        assert payload["batch"]["summary"]["total_records"] == 2

    def test_json_flag_emits_machine_readable_stdout(
        self, sample_csv: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "out"
        result = run_cli(
            "run", str(sample_csv), "--dry-run", "--json",
            "--output-dir", str(out), "--as-of", AS_OF,
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)  # entire stdout is JSON, no table
        assert payload["priority_order"][0] == "CLM-001"
        assert payload["batch"]["summary"]["total_records"] == 3

    def test_missing_api_key_fails_clearly_without_dry_run(
        self, sample_csv: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = run_cli("run", str(sample_csv), "--output-dir", str(tmp_path / "o"))

        assert result.exit_code != 0
        assert "ANTHROPIC_API_KEY" in result.output

    def test_unparseable_file_reports_row_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.csv"
        bad.write_text(
            "claim_id,payer,carc_code,rarc_codes,denial_reason_text,"
            "billed_amount,service_date,denial_date,appeal_deadline\n"
            "CLM-X,P,CO-50,,reason,not-a-number,2026-01-01,2026-01-02,\n"
        )
        result = run_cli("run", str(bad), "--dry-run", "--output-dir", str(tmp_path / "o"))

        assert result.exit_code != 0
        assert "row 0" in result.output
