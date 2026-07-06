"""Tests for `overturn summary <worklist.json>`."""
import json
from pathlib import Path

from typer.testing import CliRunner

from overturn.cli import app
from tests.conftest import AS_OF

runner = CliRunner()


def make_worklist(tmp_path: Path, sample_csv: Path) -> Path:
    out = tmp_path / "out"
    result = runner.invoke(app, [
        "run", str(sample_csv), "--dry-run",
        "--output-dir", str(out), "--as-of", AS_OF,
    ])
    assert result.exit_code == 0, result.output
    return out / "worklist.json"


class TestSummaryCommand:
    def test_prints_batch_stats(self, sample_csv: Path, tmp_path: Path) -> None:
        worklist = make_worklist(tmp_path, sample_csv)

        result = runner.invoke(app, ["summary", str(worklist), "--as-of", AS_OF])

        assert result.exit_code == 0, result.output
        out = result.output
        assert "3" in out                       # total records
        assert "$21,230.25" in out              # total dollars at stake
        # CARC grouping with dollars per group.
        assert "CO-50" in out and "CO-29" in out and "CO-97" in out
        assert "$12,500.00" in out
        # Deadline buckets relative to --as-of 2026-07-05:
        # CLM-001 overdue, CLM-002 in 10 days (<30), CLM-003 no deadline.
        assert "Overdue" in out
        assert "<30 days" in out
        assert "No deadline" in out

    def test_rejects_non_worklist_json(self, tmp_path: Path) -> None:
        bogus = tmp_path / "not-worklist.json"
        bogus.write_text(json.dumps({"foo": "bar"}))

        result = runner.invoke(app, ["summary", str(bogus)])

        assert result.exit_code != 0
        assert "worklist" in result.output.lower()
