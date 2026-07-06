"""Overturn CLI: provider-side denial management on top of healthflow-agents.

Thin adapter — transport, config, and presentation only.
"""
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional

import typer
from healthflow_agents.tools.remittance_parser import (
    RemittanceParseError,
    load_remittance,
    make_synthetic_denials,
)
from rich.console import Console
from rich.panel import Panel

from overturn.pipeline import (
    build_agent,
    run_batch,
    worklist_payload,
    write_results,
)
from overturn.render import build_worklist_table, format_money

app = typer.Typer(
    add_completion=False,
    help=(
        "Overturn — turn payer denial remittances into a prioritized appeal "
        "worklist with drafted appeal letters. Demonstration system; "
        "synthetic data only."
    ),
)
console = Console()
err_console = Console(stderr=True)


@app.callback()
def main() -> None:
    """Overturn v0.1 — demonstration system, not production RCM software."""


def _fail(message: str) -> None:
    err_console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code=2)


def _require_api_key(dry_run: bool) -> None:
    if dry_run:
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        _fail(
            "ANTHROPIC_API_KEY is not set. Export it to enable Claude appeal "
            "refinement, or pass --dry-run to run the pipeline without LLM calls."
        )


@app.command()
def run(
    input_file: Path = typer.Argument(
        ..., exists=True, dir_okay=False, readable=True,
        help="Remittance file: simplified-835 .csv or .json",
    ),
    output_dir: Path = typer.Option(
        Path("results"), "--output-dir", "-o",
        help="Directory for worklist.json, appeals/, and audit.jsonl",
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", min=1, help="Process only the first N records"
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Machine-readable JSON on stdout, no table"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Run the full pipeline without LLM calls (no API key needed)",
    ),
    as_of: Optional[str] = typer.Option(
        None, "--as-of", metavar="YYYY-MM-DD",
        help="Compute deadlines relative to this date (default: today)",
    ),
) -> None:
    """Parse a remittance file, draft appeals, and print the prioritized worklist."""
    _require_api_key(dry_run)
    today = date.fromisoformat(as_of) if as_of else date.today()

    try:
        records = load_remittance(input_file)
    except (RemittanceParseError, ValueError, json.JSONDecodeError) as exc:
        _fail(f"could not parse {input_file}: {exc}")
    if not records:
        _fail(f"{input_file} contains no denial records")
    if limit is not None:
        records = records[:limit]

    agent = build_agent(output_dir / "audit.jsonl", dry_run=dry_run)
    result, worklist = run_batch(records, agent=agent, today=today)
    write_results(output_dir, result, worklist, today=today)

    if json_out:
        sys.stdout.write(
            json.dumps(worklist_payload(result, worklist, today=today), indent=2)
            + "\n"
        )
        return

    console.print(build_worklist_table(worklist, today=today))
    summary = result.summary
    console.print(
        f"{summary.total_records} records — {summary.succeeded} drafted, "
        f"{summary.failed} failed — {format_money(summary.total_billed_amount)} at stake"
    )
    console.print(f"Results written to [bold]{output_dir}[/bold]")
    if dry_run:
        console.print(
            "[dim]dry run: appeal letters are template-generated; "
            "LLM refinement was skipped.[/dim]"
        )


DEMO_SEED = 2026


@app.command()
def demo(
    live: bool = typer.Option(
        False, "--live",
        help="Use real Claude refinement (requires ANTHROPIC_API_KEY; "
        "makes 50 API calls)",
    ),
) -> None:
    """Run the full pipeline on 50 synthetic denials. Zero setup required."""
    _require_api_key(dry_run=not live)
    today = date.today()

    console.print(Panel.fit(
        "[bold]Overturn demo[/bold] — 50 synthetic payer denials "
        "(seeded generator; every name, claim id, and dollar figure is invented)",
        border_style="cyan",
    ))

    records = make_synthetic_denials(50, seed=DEMO_SEED, base_date=today)
    with tempfile.TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "audit.jsonl"
        agent = build_agent(audit_path, dry_run=not live)
        result, worklist = run_batch(records, agent=agent, today=today)
        redaction_events, redaction_count = _redaction_stats(audit_path)

    console.print(build_worklist_table(worklist, today=today))

    summary = result.summary
    console.print(
        f"\n[bold]{summary.total_records} records[/bold] — "
        f"{summary.succeeded} appeals drafted, {summary.failed} failed — "
        f"[bold]{format_money(summary.total_billed_amount)}[/bold] at stake"
    )
    console.print(
        f"PHI redaction boundary: {redaction_count} identifiers redacted "
        f"across {redaction_events} records before any text left the process"
    )

    sample = next(o for o in worklist if o.appeal is not None)
    console.print(Panel(
        sample.appeal.appeal_letter,
        title=(
            f"Sample appeal letter — {sample.record.claim_id} "
            f"({sample.record.carc_code}, {sample.record.payer})"
        ),
        border_style="green",
    ))
    if not live:
        console.print(
            "[dim]Letters above are deterministic templates from the appeal "
            "engine; Claude refinement was skipped (no API key needed). "
            "Re-run with --live for refined recommendations.[/dim]"
        )
    console.print(
        "[dim]Synthetic data only — Overturn is a demonstration system, "
        "not production RCM software.[/dim]"
    )


def _redaction_stats(audit_path: Path) -> tuple[int, int]:
    """(records with redactions, total identifiers redacted) from audit.jsonl."""
    events = 0
    total = 0
    try:
        lines = audit_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0, 0
    for line in lines:
        entry = json.loads(line)
        if entry["event_type"] == "phi_redacted":
            count = int(entry["details"].get("count", 0))
            if count:
                events += 1
                total += count
    return events, total


if __name__ == "__main__":
    app()
