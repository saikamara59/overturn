# Dismiss ("Won't Appeal") Claims — Design

**Date:** 2026-07-11
**Status:** Approved (design discussion in session)

## Goal

Give billers the missing counterpart to Approve: close a claim without
appealing it, clearing it from the active worklist while keeping the
decision on the record. Reversible, with an optional reason.

## Decisions

- **Reversible** — Restore returns the claim to its working state.
- **Optional reason** — fixed set: `payer_correct | too_small |
  deadline_passed | other` (stored as a short string; optional).
- **Hidden by default, filterable** — dismissed claims leave the default
  worklist and all its counts; a "Dismissed" entry in the Status filter
  reveals them.
- **API mode only** — the static-report (island) build is unchanged;
  dismissal is a persistence feature.

## Backend

**Migration 0003:** add `claims.dismiss_reason` (text, nullable). No other
schema change (status is already a free-form varchar).

**Status machine additions** (`PATCH /api/v1/claims/{id}`):
- `{status: "dismissed", dismissReason?: str}` — allowed when claim status
  is `draft_ready` or `failed`; 409 otherwise (incl. `submitted`,
  `queued`, `drafting`). `dismissReason` must be one of the fixed set when
  present (422 otherwise). Sets status `dismissed`, stores reason.
- `{status: "restored"}` — allowed only from `dismissed`; returns the
  claim to `draft_ready` if `letter` is non-null, else `failed`; clears
  `dismiss_reason`.
- Letter edits (`{letter: ...}`) are rejected 409 while dismissed.
- Existing guards apply unchanged: demo run 409, cross-org 404 (scoped
  dependency), auth required.

**Audit:** both actions insert `audit_events` rows directly from the API
(same table the sinks use): `claim_dismissed` (details: claim_id, reason)
and `claim_restored` (details: claim_id, restored_to). These appear in the
run's audit trail.

**Payloads:** `DISPLAY_STATUS` gains `dismissed → "Dismissed"`;
`claim_entry` gains `dismissReason: str | null`; `worklist_payload`'s
`summary` gains `dismissed: int` (count of dismissed claims in the run).
Run pipeline counters (`drafted`, `failed_records`) are NOT touched by
dismissal — it is a workflow state, not a pipeline state. The retry
endpoint continues to re-queue only claims not in
(`draft_ready`, `submitted`) — add `dismissed` to that exclusion so retry
never resurrects a written-off claim.

## Frontend (served app only)

- `types.ts`: Claim gains `dismissReason?: string | null`; status union
  widens accordingly where typed.
- `lib/worklist.ts`: `statusStyle` gains `Dismissed` (gray);
  `visibleSorted` excludes status `Dismissed` unless the `fStatus` filter
  includes `"Dismissed"`; filter counts follow the same rule (the
  Dismissed filter row shows its true count; all other counts exclude
  dismissed claims).
- `WorkbenchMutations` gains `dismiss(c: Claim, reason?: string):
  Promise<Claim>` and `restore(c: Claim): Promise<Claim>`; `api.ts`
  `patchClaim` already covers the wire format.
- **Detail screen:** a `Dismiss` button beside the existing actions;
  clicking reveals an inline reason `<select>` (optional, defaulting to no
  reason) + Confirm/Cancel. Dismissed claims render a gray banner
  ("Dismissed — {reason label}" or just "Dismissed"), a `Restore` button,
  a read-only (disabled) letter textarea, and no
  Approve/Edit/Revert/Dismiss actions.
- **Summary screen:** an `sm-note` line "N dismissed (won't appeal)" in
  the deadline panel when N > 0.
- Island mode (`mutations` undefined): no Dismiss UI anywhere; behavior
  byte-identical to today.

## Testing

- **pytest:** transition matrix (dismiss from draft_ready ✓, failed ✓,
  submitted 409, queued 409; restore→draft_ready with letter,
  restore→failed without; invalid reason 422; letter edit while dismissed
  409; demo 409; cross-org 404), audit rows written with correct details,
  payload fields (`dismissReason`, summary `dismissed`), retry excludes
  dismissed.
- **Vitest:** dismiss flow (button → reason picker → mutation called →
  banner state), default hiding + Status filter reveal, restore flow,
  island mode shows no Dismiss button.
- **E2E:** extend the persistence spec — dismiss a claim with a reason,
  reload, claim absent from default worklist, filter to Dismissed, restore,
  claim back in worklist.

## Out of scope

Bulk dismiss, reason analytics/reporting (Phase 3), dismiss in the static
report, admin-only dismissal permissions (any member may dismiss/restore,
same as approve).
