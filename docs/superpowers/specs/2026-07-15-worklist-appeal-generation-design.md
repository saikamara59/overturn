# Worklist Appeal Generation — Design

**Date:** 2026-07-15
**Status:** Approved (design authored by the owner in Claude Design)

## Problem

The design ("Overturn v2.dc.html", Claude Design project
`1d6c80ea-6fb4-493d-b376-73054d9fdca3`) makes **LLM appeal generation a
worklist action**: select claims → dark bulk bar → **Generate Appeals**
("Appeal generation queued for N claims"), plus a **Regenerate** button on
the claim detail screen. The product never implemented either — generation
happens exactly once, at upload; the bulk bar's only action is "Export
letters"; and the failed-claim banner tells users to *"re-run the batch for
this claim"* while offering no way to do that (run-level Retry on the Runs
screen is the only knob, and it requeues every unfinished claim).

This feature wires the design's generation affordances to the real
pipeline: bulk **Generate Appeals** from the worklist and per-claim
**Regenerate** from detail — including re-drafting failed claims.

## Approach (no package change needed)

The worker already drafts claim-by-claim: `process_run` loops over claims
with `status == "queued"` and calls the package's
`AppealAgent.process_denial_record` per record (`server/worker.py`). The
retry endpoint already demonstrates the requeue pattern. Generation from
the worklist is therefore pure transport, consistent with the thin-host
rule: **requeue the selected claims and the run; the worker re-drafts
them.** No healthflow-agents change.

## API

`POST /api/v1/runs/{run_id}/generate` (org-scoped via `scoped_run` —
cross-org is 404), body `{"claimIds": ["<claim db uuid>", ...]}`:

- **409** if the run is the demo run.
- **409** if the run is currently `running` — the worker holds that run's
  counters in memory mid-pass (`expire_on_commit=False`), so a concurrent
  requeue would let its per-claim commits clobber the recompute below, and
  flipping a running run back to `queued` could double-claim it under
  multiple workers. Queued/completed/failed runs are safe to requeue.
- **422** if `claimIds` is empty, or contains ids not belonging to this run.
- **422** if the run is live (`dry_run=False`) and the org currently has no
  API key ("organization has no API key configured; add a key in Org
  Settings or re-upload as a dry run") — prevents the worker's
  `OrgKeyError` path from marking the whole run failed.
- Eligible claims (`draft_ready`, `failed`): set `status="queued"`, clear
  `error`. Ineligible claims (`submitted`, `dismissed`, `queued`,
  `drafting`) are **skipped, not an error** — the response reports both:
  `{"queued": N, "skipped": M}`.
- If anything was queued: run `status="queued"`, `error=None`,
  `finished_at=None`, and counters recomputed exactly like retry
  (`drafted` = draft_ready+submitted count, `failed_records` = failed
  count) so the worker's increments stay correct.
- Audit event `regeneration_requested` with
  `{"count": N, "claim_ids": [first 20 external claim ids]}`.
- Generation mode is inherited: the run's `dry_run` flag picks
  `DryRunClient` vs. the org's decrypted key, same as upload.
- Regenerating **overwrites** `letter`, `letter_original`, `refined`, and
  `rule` with the fresh draft (that is what "regenerate" means); manual
  edits are lost for those claims. "Revert draft" remains the non-LLM
  restore. The package's audit sink records the new `appeal_generated`
  events as usual.
- Known benign race (shared with retry): if the worker is committing a
  run's final status at the same moment, the requeue can be overwritten;
  the claims stay `queued` and a subsequent retry/generate re-queues the
  run. Not worth locking for.

## Frontend

- **`WorkbenchMutations.generate(claims: Claim[]): Promise<{queued, skipped}>`**
  — new mutation (server mode only). `makeMutations` gains the run id and
  an `onGenerated` callback so ServerApp can immediately `loadRun` and
  resume its existing 2-second polling (`runActive=true`) — progress then
  streams in via the current mechanism, no new polling code.
- **BulkBar**: when `generate` is available, the primary button is
  **Generate Appeals** (design's CTA) with "Export letters" demoted to a
  secondary `.btn`; in the static report (no mutations) the bulk bar keeps
  Export as primary — a static file can't call an LLM. After a successful
  call: clear selection, drop local letter overrides for the *eligible*
  (actually queued) claims only, and only when something was queued; cancel
  any pending letter autosave; toast `Appeal generation queued for N claims`
  (append `· M skipped` when M > 0).
- **Detail / AppealCard**: a **Regenerate** button (server mode only) for
  `Draft Ready` and `Failed` claims — on the failed branch it is the
  primary action (this is the fix the banner was asking for; banner copy
  becomes "Regenerate it below or write the appeal manually."). Calls
  `generate([claim])`, toasts, clears that claim's local letter override;
  the poll refresh brings in the new draft.
- **Status pills**: add `Queued` (gray) and `Drafting` (amber) to
  `statusStyle` so in-flight claims read clearly in the table, cards, and
  detail while polling refreshes.
- Claims whose status is `Queued`/`Drafting` render a passive "Drafting in
  progress" banner in detail instead of the editable letter and draft
  actions (the server independently 409s any letter patch outside
  draft_ready/submitted).

## Testing

- **pytest**: endpoint happy path (statuses flip, error cleared, run
  requeued, counters recomputed, audit event written); skipped statuses;
  empty list 422; foreign/unknown claim ids 422; cross-org 404; demo 409;
  live-run-without-key 422; end-to-end worker pass — requeue a drafted +
  a failed claim, `process_run` with a stub client, assert fresh
  letter/letter_original/refined and correct final counters.
- **vitest**: BulkBar renders Generate Appeals only when handler provided;
  App wires selection → `generate`, clears overrides, toasts with
  queued/skipped; AppealCard shows Regenerate for Draft Ready and Failed
  (server mode) and not in static mode; statusStyle for Queued/Drafting.
- **Playwright**: new `e2e/generate.spec.ts` — upload a small dry-run CSV,
  wait for completion, select all → Generate Appeals → statuses cycle back
  to Draft Ready with letters present; open a claim → Regenerate → same.
- Template rebuilt (shared components change) and committed.

## Out of scope

- Choosing a different mode/model at generation time (inherits the run).
- Streaming/per-token progress; the 2s poll is the progress channel.
- Regenerating submitted or dismissed claims (unsubmit/restore first).
- The design's hardcoded strings ("claude-sonnet-4-6", fixed timestamps) —
  live metadata continues to come from the run.
