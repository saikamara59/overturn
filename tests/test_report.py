"""Tests for the HTML workbench report: data mapping and rendering."""
import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from overturn.cli import app
from overturn.report import build_report_data, render_report
from tests.conftest import AS_OF

runner = CliRunner()
TODAY = date(2026, 7, 5)


@pytest.fixture
def results_dir(tmp_path: Path, sample_csv: Path) -> Path:
    out = tmp_path / "out"
    res = runner.invoke(app, [
        "run", str(sample_csv), "--dry-run",
        "--output-dir", str(out), "--as-of", AS_OF,
    ])
    assert res.exit_code == 0, res.output
    return out


def load_payload(results_dir: Path) -> dict:
    return json.loads((results_dir / "worklist.json").read_text())


def load_audit(results_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (results_dir / "audit.jsonl").read_text().splitlines()
    ]


class TestBuildReportData:
    def test_maps_claims_in_priority_order(self, results_dir: Path) -> None:
        data = build_report_data(
            load_payload(results_dir), load_audit(results_dir), today=TODAY
        )

        assert [c["id"] for c in data["claims"]] == ["CLM-001", "CLM-002", "CLM-003"]
        first = data["claims"][0]
        assert first["payer"] == "Synthetic Payer A"
        assert first["carc"] == "CO-50"
        assert first["billed"] == 12500.0
        assert first["days"] == -5          # overdue vs 2026-07-05
        assert first["status"] == "Draft Ready"
        assert "Formal Appeal" in first["letter"]
        assert first["rule"]                # cms_rule from CoverageArgument
        assert first["denialText"]          # raw denial_reason_text

    def test_no_deadline_claim_has_null_days(self, results_dir: Path) -> None:
        data = build_report_data(
            load_payload(results_dir), load_audit(results_dir), today=TODAY
        )
        clm3 = next(c for c in data["claims"] if c["id"] == "CLM-003")
        assert clm3["days"] is None
        assert clm3["deadline"] is None

    def test_failed_claim_maps_to_failed_status(self, results_dir: Path) -> None:
        payload = load_payload(results_dir)
        outcome = payload["batch"]["outcomes"][0]
        outcome["success"] = False
        outcome["appeal"] = None
        outcome["error_type"] = "APIError"
        outcome["error_message"] = "boom"

        data = build_report_data(payload, [], today=TODAY)
        failed = next(c for c in data["claims"] if c["status"] == "Failed")
        assert failed["letter"] is None
        assert failed["error"] == "boom"

    def test_totals_and_audit_events(self, results_dir: Path) -> None:
        data = build_report_data(
            load_payload(results_dir), load_audit(results_dir), today=TODAY
        )
        assert data["totalBilled"] == 21230.25
        assert data["summary"] == {"processed": 3, "drafts": 3, "failed": 0}
        types = {e["type"] for e in data["audit"]}
        assert "batch_started" in types and "batch_completed" in types
        assert all("time" in e and "detail" in e for e in data["audit"])


class TestRenderReport:
    def test_embeds_data_island_and_is_self_contained(
        self, results_dir: Path
    ) -> None:
        data = build_report_data(
            load_payload(results_dir), load_audit(results_dir), today=TODAY
        )
        html = render_report(data)

        assert html.startswith("<!DOCTYPE html>")
        assert 'id="overturn-data"' in html
        embedded = html.split('id="overturn-data" type="application/json">')[1]
        embedded = embedded.split("</script>")[0]
        assert json.loads(embedded)["claims"][0]["id"] == "CLM-001"

    def test_data_injected_exactly_once(self, results_dir: Path) -> None:
        # The injection marker must not appear anywhere in the template's JS,
        # or the payload gets spliced into a string literal and breaks the page.
        data = build_report_data(
            load_payload(results_dir), load_audit(results_dir), today=TODAY
        )
        html = render_report(data)
        assert html.count('"generatedOn"') == 1


class TestReportCommand:
    def test_writes_html_next_to_worklist(self, results_dir: Path) -> None:
        res = runner.invoke(app, [
            "report", str(results_dir / "worklist.json"), "--as-of", AS_OF,
        ])
        assert res.exit_code == 0, res.output
        out = results_dir / "workbench.html"
        assert out.exists()
        assert "CLM-001" in out.read_text()

    def test_accepts_results_directory(self, results_dir: Path) -> None:
        res = runner.invoke(app, ["report", str(results_dir), "--as-of", AS_OF])
        assert res.exit_code == 0, res.output
        assert (results_dir / "workbench.html").exists()
