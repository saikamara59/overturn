"""Overturn CLI: provider-side denial management on top of healthflow-agents.

Thin adapter — transport, config, and presentation only.
"""
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import typer
from healthflow_agents.tools.remittance_parser import (
    RemittanceParseError,
    load_remittance,
)
from rich.console import Console

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


if __name__ == "__main__":
    app()
