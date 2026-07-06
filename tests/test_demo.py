"""Tests for `overturn demo` — zero arguments, zero setup, no API key."""
import pytest
from typer.testing import CliRunner

from overturn.cli import app

runner = CliRunner()


class TestDemoCommand:
    def test_runs_with_no_args_and_no_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = runner.invoke(app, ["demo"])

        assert result.exit_code == 0, result.output
        assert "50 records" in result.output
        # Prints the worklist table and exactly one sample appeal letter.
        assert "Appeal worklist" in result.output
        assert result.output.count("Formal Appeal of Denied Claim") == 1
        # Honest about what it is.
        assert "synthetic" in result.output.lower()

    def test_reports_phi_redaction_counts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = runner.invoke(app, ["demo"])

        # Seeded generator embeds synthetic patient identifiers in ~1/3 of
        # records; the demo surfaces the resulting redaction events.
        assert "redact" in result.output.lower()

    def test_live_without_key_fails_clearly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = runner.invoke(app, ["demo", "--live"])

        assert result.exit_code != 0
        assert "ANTHROPIC_API_KEY" in result.output
