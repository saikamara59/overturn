"""Dry-run stand-in for the Anthropic client.

healthflow-agents' AgentBase accepts an injected `client`; this stub uses
that supported injection point so --dry-run exercises the full pipeline
(redaction, parsing, code lookup, deterministic letter generation) without
any network call. The one LLM step — refinement — returns a clearly labeled
placeholder instead of fabricated advice.
"""
from types import SimpleNamespace
from typing import Any

DRY_RUN_NOTE = (
    "[dry run — LLM refinement skipped; no API call was made. "
    "Run without --dry-run for Claude-refined appeal recommendations.]"
)


class _StubMessages:
    def create(self, **_: Any) -> SimpleNamespace:
        return SimpleNamespace(content=[SimpleNamespace(text=DRY_RUN_NOTE)])


class DryRunClient:
    """Duck-typed anthropic.Anthropic: exposes messages.create only."""

    def __init__(self) -> None:
        self.messages = _StubMessages()
