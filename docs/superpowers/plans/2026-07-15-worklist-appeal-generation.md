# Worklist Appeal Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the design's LLM generation affordances into the product: a "Generate Appeals" bulk action on the worklist and a per-claim "Regenerate" on detail, both re-drafting claims through the existing worker.

**Architecture:** New `POST /runs/{run_id}/generate` endpoint requeues selected claims (retry-pattern: claim status → `queued`, run → `queued`, counters recomputed); the untouched worker re-drafts them via `AppealAgent.process_denial_record`. Frontend adds a `generate` mutation; ServerApp's existing 2-second polling is the progress channel. No healthflow-agents change (thin-host rule).

**Tech Stack:** FastAPI + SQLAlchemy (server), React 18 + TypeScript (frontend), pytest / Vitest / Playwright.

**Spec:** `docs/superpowers/specs/2026-07-15-worklist-appeal-generation-design.md`

## Global Constraints

- No changes to `server/worker.py` or the healthflow-agents package.
- Claim statuses eligible for regeneration: exactly `draft_ready` and `failed`. `submitted`, `dismissed`, `queued`, `drafting` are skipped (counted in the response, never an error).
- `overturn/templates/workbench.html` is generated — never hand-edit; rebuild with `cd frontend && npm run build:template` (Task 4) and commit.
- Server tests need Postgres: `docker compose up -d db` (port 5433). Frontend commands run from `frontend/`.
- Work on branch `worklist-generation`. Commit after every task. Full suite green before each commit.
- Do NOT update Linear or the local task list — the controller owns those gates.

## File Structure

- `server/api/runs.py` — new `generate_appeals` endpoint (transport only).
- `tests/server/test_generate.py` — new endpoint + worker-regen tests.
- `frontend/src/app/api.ts` — `generateAppeals()` client call.
- `frontend/src/app/ServerApp.tsx` — `makeMutations(runId, onGenerated)`.
- `frontend/src/App.tsx` — `generate` mutation type + bulk/detail wiring.
- `frontend/src/components/worklist/{WorklistScreen,BulkBar}.tsx` — Generate Appeals button.
- `frontend/src/components/detail/{DetailScreen,AppealCard}.tsx` — Regenerate button.
- `frontend/src/lib/worklist.ts` — `Queued`/`Drafting` pill styles.
- `frontend/e2e/generate.spec.ts` — new end-to-end flow.

---

### Task 1: Backend — POST /runs/{run_id}/generate

**Files:**
- Modify: `server/api/runs.py`
- Test: `tests/server/test_generate.py` (new)

**Interfaces:**
- Consumes: `scoped_run`/`get_session` deps, `Run`/`Claim`/`Org`/`AuditEvent` models, worker's queued-claim contract.
- Produces: `POST /api/v1/runs/{run_id}/generate` with JSON body `{"claimIds": ["<claim db uuid>", ...]}` → `{"queued": int, "skipped": int}`. Task 2's client calls this.

- [ ] **Step 1: Write the failing tests**

```python
# tests/server/test_generate.py
"""POST /runs/{id}/generate — requeue selected claims for (re)generation."""
import uuid

from overturn.dryrun import DryRunClient
from server.models import AuditEvent, Claim, Org, Run
from server.worker import claim_next_run, process_run
from tests.server.conftest import login_as, make_org, make_user
from tests.server.test_claims_api import drafted_run


def claims_of(client, run_id):
    return client.get(f"/api/v1/runs/{run_id}/claims").json()["claims"]


def _fail_claim(session_factory, db_id):
    with session_factory() as s:
        c = s.get(Claim, uuid.UUID(db_id))
        c.status = "failed"
        c.error = "boom"
        c.letter = None
        run = s.get(Run, c.run_id)
        run.drafted -= 1
        run.failed_records += 1
        s.commit()


def test_generate_requeues_and_recomputes(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    _fail_claim(session_factory, entries[1]["dbId"])

    r = client.post(f"/api/v1/runs/{run_id}/generate",
                    json={"claimIds": [entries[0]["dbId"], entries[1]["dbId"]]})
    assert r.status_code == 200, r.text
    assert r.json() == {"queued": 2, "skipped": 0}

    with session_factory() as s:
        run = s.get(Run, uuid.UUID(run_id))
        assert run.status == "queued"
        assert run.finished_at is None and run.error is None
        assert run.drafted == 1          # only the untouched third claim
        assert run.failed_records == 0   # the failed one is queued again
        for db_id in (entries[0]["dbId"], entries[1]["dbId"]):
            c = s.get(Claim, uuid.UUID(db_id))
            assert c.status == "queued" and c.error is None
        ev = s.query(AuditEvent).filter_by(
            event_type="regeneration_requested").one()
        assert ev.details["count"] == 2
        assert len(ev.details["claim_ids"]) == 2


def test_generate_then_worker_redrafts(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    with session_factory() as s:  # simulate a user edit that regen replaces
        c = s.get(Claim, uuid.UUID(entries[0]["dbId"]))
        c.letter = "EDITED BY HAND"
        s.commit()
    _fail_claim(session_factory, entries[1]["dbId"])

    r = client.post(f"/api/v1/runs/{run_id}/generate",
                    json={"claimIds": [entries[0]["dbId"], entries[1]["dbId"]]})
    assert r.status_code == 200

    with session_factory() as s:
        assert claim_next_run(s) == uuid.UUID(run_id)
    process_run(uuid.UUID(run_id), session_factory=session_factory,
                client=DryRunClient())

    with session_factory() as s:
        run = s.get(Run, uuid.UUID(run_id))
        assert run.status == "completed"
        assert run.drafted == 3 and run.failed_records == 0
        redrafted = s.get(Claim, uuid.UUID(entries[0]["dbId"]))
        assert redrafted.status == "draft_ready"
        assert redrafted.letter and redrafted.letter != "EDITED BY HAND"
        assert redrafted.letter == redrafted.letter_original
        revived = s.get(Claim, uuid.UUID(entries[1]["dbId"]))
        assert revived.status == "draft_ready" and revived.letter


def test_generate_skips_ineligible_statuses(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    client.patch(f"/api/v1/claims/{entries[0]['dbId']}", json={"status": "submitted"})
    client.patch(f"/api/v1/claims/{entries[1]['dbId']}", json={"status": "dismissed"})

    r = client.post(f"/api/v1/runs/{run_id}/generate",
                    json={"claimIds": [e["dbId"] for e in entries]})
    assert r.status_code == 200
    assert r.json() == {"queued": 1, "skipped": 2}
    with session_factory() as s:  # only queued work requeues the run
        assert s.get(Run, uuid.UUID(run_id)).status == "queued"


def test_generate_validation_and_guards(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)

    assert client.post(f"/api/v1/runs/{run_id}/generate",
                       json={"claimIds": []}).status_code == 422
    assert client.post(f"/api/v1/runs/{run_id}/generate",
                       json={"claimIds": ["not-a-uuid"]}).status_code == 422
    assert client.post(f"/api/v1/runs/{run_id}/generate",
                       json={"claimIds": [str(uuid.uuid4())]}).status_code == 422

    # live run without an org key is rejected up front
    with session_factory() as s:
        s.get(Run, uuid.UUID(run_id)).dry_run = False
        s.commit()
    r = client.post(f"/api/v1/runs/{run_id}/generate",
                    json={"claimIds": [entries[0]["dbId"]]})
    assert r.status_code == 422 and "API key" in r.json()["detail"]
    with session_factory() as s:
        s.get(Run, uuid.UUID(run_id)).dry_run = True
        s.commit()

    # demo run is read-only
    with session_factory() as s:
        s.get(Run, uuid.UUID(run_id)).is_demo = True
        s.commit()
    assert client.post(f"/api/v1/runs/{run_id}/generate",
                       json={"claimIds": [entries[0]["dbId"]]}).status_code == 409


def test_generate_cross_org_is_404(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    other = make_org(session_factory, name="Rival RCM")
    make_user(session_factory, "rival@example.com", "hunter2hunter2",
              org=other, role="admin")
    login_as(client, "rival@example.com", "hunter2hunter2")
    r = client.post(f"/api/v1/runs/{run_id}/generate",
                    json={"claimIds": [entries[0]["dbId"]]})
    assert r.status_code == 404
```

Note: `drafted_run` logs in as the platform admin and uploads the 3-claim
sample via the API (dry run), then processes it with `DryRunClient` —
see `tests/server/test_claims_api.py:11`. Look at how that module's
`upload` helper sets `dry_run` if any assumption above fails.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/server/test_generate.py -q`
Expected: FAIL — all tests 404/405 (endpoint missing).

- [ ] **Step 3: Implement the endpoint**

In `server/api/runs.py`, add imports:

```python
from pydantic import BaseModel

from server.models import AuditEvent, Claim, Org, Run, utcnow
```

(`AuditEvent, Claim, Run, utcnow` are already imported — only add `Org` to
that line and the new `pydantic` import.)

Add after `retry_run`:

```python
class GenerateRequest(BaseModel):
    claimIds: list[str]


GENERATABLE = ("draft_ready", "failed")


@router.post("/{run_id}/generate")
def generate_appeals(
    body: GenerateRequest,
    run: Run = Depends(scoped_run),
    session: Session = Depends(get_session),
) -> dict:
    """Requeue selected claims for (re)drafting; the worker picks them up."""
    if run.is_demo:
        raise HTTPException(409, detail="demo run is read-only")
    if not body.claimIds:
        raise HTTPException(422, detail="claimIds must not be empty")
    if not run.dry_run:
        org = session.get(Org, run.org_id)
        if org is None or not org.anthropic_key_encrypted:
            raise HTTPException(
                422,
                detail=(
                    "organization has no API key configured; add a key in "
                    "Org Settings or re-upload as a dry run"
                ),
            )
    try:
        wanted = {uuid.UUID(cid) for cid in body.claimIds}
    except ValueError:
        raise HTTPException(422, detail="claimIds must be claim UUIDs")
    by_id = {c.id: c for c in run.claims}
    unknown = wanted - by_id.keys()
    if unknown:
        raise HTTPException(422, detail=f"{len(unknown)} claim id(s) not in this run")

    queued_ids: list[str] = []
    skipped = 0
    for cid in wanted:
        claim = by_id[cid]
        if claim.status in GENERATABLE:
            claim.status = "queued"
            claim.error = None
            claim.updated_at = utcnow()
            queued_ids.append(claim.claim_id)
        else:
            skipped += 1
    if queued_ids:
        run.status = "queued"
        run.error = None
        run.finished_at = None
        # mirror retry: recompute so the worker's increments stay correct
        run.drafted = sum(1 for c in run.claims if c.status in ("draft_ready", "submitted"))
        run.failed_records = sum(1 for c in run.claims if c.status == "failed")
        session.add(AuditEvent(
            run_id=run.id, ts=utcnow(), event_type="regeneration_requested",
            details={"count": len(queued_ids), "claim_ids": sorted(queued_ids)[:20]},
        ))
    return {"queued": len(queued_ids), "skipped": skipped}
```

- [ ] **Step 4: Run the new tests, then the full backend suite**

Run: `.venv/bin/pytest tests/server/test_generate.py -q` → PASS, then
`.venv/bin/pytest -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add server/api/runs.py tests/server/test_generate.py
git commit -m "generate: POST /runs/{id}/generate requeues selected claims for the worker"
```

---

### Task 2: Frontend — generate mutation + Generate Appeals bulk action

**Files:**
- Modify: `frontend/src/app/api.ts`
- Modify: `frontend/src/app/ServerApp.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/worklist/WorklistScreen.tsx`
- Modify: `frontend/src/components/worklist/BulkBar.tsx`
- Modify: `frontend/src/lib/worklist.ts`
- Test: `frontend/src/__tests__/generate.test.tsx` (new)

**Interfaces:**
- Consumes: Task 1's endpoint.
- Produces: `WorkbenchMutations.generate(claims: Claim[]): Promise<{ queued: number; skipped: number }>`; `makeMutations(runId: string, onGenerated: () => void)`; `BulkBar` prop `onGenerate?: () => void`; `WorklistProps.onGenerateSelected?: () => void`; `statusStyle` entries for `Queued`/`Drafting`. Task 3 reuses the `generate` mutation.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/__tests__/generate.test.tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import App, { type WorkbenchMutations } from '../App';
import { BulkBar } from '../components/worklist/BulkBar';
import { statusStyle } from '../lib/worklist';
import { makeData } from './helpers/data';

function mutationsWith(generate: WorkbenchMutations['generate']): WorkbenchMutations {
  return {
    approve: vi.fn(), saveLetter: vi.fn(), revertLetter: vi.fn(),
    dismiss: vi.fn(), restore: vi.fn(), generate,
  };
}

test('BulkBar shows Generate Appeals only when a handler is provided', () => {
  const { rerender } = render(
    <BulkBar count={1} total={100} onClear={vi.fn()} onExport={vi.fn()} />,
  );
  expect(screen.queryByRole('button', { name: 'Generate Appeals' })).toBeNull();
  rerender(
    <BulkBar count={1} total={100} onClear={vi.fn()} onExport={vi.fn()}
      onGenerate={vi.fn()} />,
  );
  expect(screen.getByRole('button', { name: 'Generate Appeals' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Export letters' })).toBeInTheDocument();
});

test('selecting a claim and clicking Generate Appeals calls the mutation and toasts', async () => {
  const data = makeData();
  const generate = vi.fn().mockResolvedValue({ queued: 1, skipped: 0 });
  render(<App data={data} mutations={mutationsWith(generate)} />);

  fireEvent.click(document.querySelectorAll('.tbody-row .cbox')[0] as HTMLElement);
  fireEvent.click(screen.getByRole('button', { name: 'Generate Appeals' }));

  await waitFor(() => expect(generate).toHaveBeenCalledTimes(1));
  expect(generate.mock.calls[0][0]).toHaveLength(1);
  await screen.findByText(/Appeal generation queued for 1 claim/);
});

test('skipped claims are reported in the toast', async () => {
  const data = makeData();
  const generate = vi.fn().mockResolvedValue({ queued: 1, skipped: 2 });
  render(<App data={data} mutations={mutationsWith(generate)} />);
  fireEvent.click(document.querySelector('.thead .cbox') as HTMLElement); // select all
  fireEvent.click(screen.getByRole('button', { name: 'Generate Appeals' }));
  await screen.findByText(/queued for 1 claim · 2 skipped/);
});

test('without mutations the bulk bar keeps Export as the only action', () => {
  const data = makeData();
  render(<App data={data} />);
  fireEvent.click(document.querySelectorAll('.tbody-row .cbox')[0] as HTMLElement);
  expect(screen.queryByRole('button', { name: 'Generate Appeals' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Export letters' })).toBeInTheDocument();
});

test('statusStyle covers the in-flight statuses', () => {
  expect(statusStyle('Queued').cls).toBe('c-gray');
  expect(statusStyle('Drafting').cls).toBe('c-amber');
});
```

Check the existing `workbench-mutations.test.tsx` for how it builds
mutation stubs — if it constructs full `WorkbenchMutations` objects, those
object literals must gain a `generate` stub once the interface grows (fix
any type errors it raises the same way: add `generate: vi.fn()`).

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/__tests__/generate.test.tsx`
Expected: FAIL — no Generate Appeals button, `generate` missing from type.

- [ ] **Step 3: api.ts — client call**

Append near `retryRun`:

```ts
export const generateAppeals = (runId: string, claimIds: string[]) =>
  request<{ queued: number; skipped: number }>(
    `/api/v1/runs/${runId}/generate`, json('POST', { claimIds }),
  );
```

- [ ] **Step 4: App.tsx — mutation type + bulk wiring**

Add to the `WorkbenchMutations` interface:

```ts
  generate?(claims: Claim[]): Promise<{ queued: number; skipped: number }>;
```

(optional so the mutation only exists in server mode — static callers and
existing stubs stay valid; guard all uses.)

Inside `App`, after `onExportSelected`, add:

```ts
  const onGenerateSelected = mutations?.generate ? () => {
    const sel = data.claims.filter((c) => selected[c.id]);
    mutations.generate!(sel).then(({ queued, skipped }) => {
      setSelected({});
      setLetters((l) => {
        const next = { ...l };
        sel.forEach((c) => delete next[c.id]);
        return next;
      });
      showToast(
        `Appeal generation queued for ${queued} claim${queued === 1 ? '' : 's'}`
        + (skipped ? ` · ${skipped} skipped` : ''),
      );
    }).catch((e) => showToast(String((e as Error).message ?? e)));
  } : undefined;
```

and pass `onGenerateSelected={onGenerateSelected}` to `<WorklistScreen …>`.

- [ ] **Step 5: WorklistScreen + BulkBar**

`WorklistProps` gains `onGenerateSelected?: () => void;` and the `BulkBar`
call becomes:

```tsx
          <BulkBar
            count={selIds.length}
            total={selSum}
            onClear={p.onClearSelection}
            onExport={p.onExportSelected}
            onGenerate={p.onGenerateSelected}
          />
```

`BulkBar.tsx` becomes:

```tsx
import { fmtMoney } from '../../lib/format';

interface Props {
  count: number;
  total: number;
  onClear: () => void;
  onExport: () => void;
  onGenerate?: () => void;
}

export function BulkBar({ count, total, onClear, onExport, onGenerate }: Props) {
  return (
    <div className="bulk">
      <div className="bulk-label">{count} claim{count === 1 ? '' : 's'} selected</div>
      <div className="bulk-value">{fmtMoney(total)} at stake</div>
      <div className="spacer" />
      <button type="button" className="bulk-clear" onClick={onClear}>Clear</button>
      {onGenerate ? (
        <>
          <button type="button" className="btn" onClick={onExport}>Export letters</button>
          <button type="button" className="btn-primary" onClick={onGenerate}>
            Generate Appeals
          </button>
        </>
      ) : (
        <button type="button" className="btn-primary" onClick={onExport}>
          Export letters
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 6: ServerApp — run id + refresh callback**

Change `makeMutations()` to:

```ts
function makeMutations(runId: string, onGenerated: () => void): WorkbenchMutations {
```

add inside the returned object:

```ts
    async generate(claims) {
      const ids = claims.map((c) => c.dbId).filter(Boolean) as string[];
      if (!ids.length) throw new Error('read-only view');
      const out = await generateAppeals(runId, ids);
      if (out.queued > 0) onGenerated();
      return out;
    },
```

import `generateAppeals` from `./api`, and update the call site in the
run route:

```tsx
        {worklist
          ? (
            <App
              data={worklist}
              mutations={makeMutations(route.id, () => {
                setRunActive(true);
                loadRun(route.id);
              })}
            />
          )
          : <div className="sm-note" style={{ padding: 24 }}>Loading worklist…</div>}
```

- [ ] **Step 7: statusStyle — in-flight pills**

In `frontend/src/lib/worklist.ts` extend the `statusStyle` map:

```ts
    Queued: { cls: 'c-gray', dot: 'var(--gray-dot)' },
    Drafting: { cls: 'c-amber', dot: 'var(--amber-dot)' },
```

- [ ] **Step 8: Run the full suite**

Run: `cd frontend && npm test -- --run` and `npx tsc --noEmit`.
Expected: PASS (fix any mutation-stub type errors by adding `generate: vi.fn()`).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/app/api.ts frontend/src/app/ServerApp.tsx frontend/src/App.tsx frontend/src/components/worklist/WorklistScreen.tsx frontend/src/components/worklist/BulkBar.tsx frontend/src/lib/worklist.ts frontend/src/__tests__/generate.test.tsx frontend/src/__tests__/workbench-mutations.test.tsx
git commit -m "generate: Generate Appeals bulk action wired to the generation endpoint"
```

(drop `workbench-mutations.test.tsx` from the add list if it needed no change)

---

### Task 3: Detail screen — Regenerate

**Files:**
- Modify: `frontend/src/components/detail/AppealCard.tsx`
- Modify: `frontend/src/components/detail/DetailScreen.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/__tests__/generate.test.tsx` (extend)

**Interfaces:**
- Consumes: `mutations.generate` from Task 2.
- Produces: `AppealCard`/`DetailScreen` prop `onRegenerate?: () => void`.

- [ ] **Step 1: Write the failing tests** (append to `generate.test.tsx`)

```tsx
test('detail shows Regenerate in server mode and regen queues the claim', async () => {
  const data = makeData();
  const generate = vi.fn().mockResolvedValue({ queued: 1, skipped: 0 });
  render(<App data={data} mutations={mutationsWith(generate)} />);

  fireEvent.click(document.querySelector('.tbody-row') as HTMLElement);
  fireEvent.click(screen.getByRole('button', { name: 'Regenerate' }));

  await waitFor(() => expect(generate).toHaveBeenCalledTimes(1));
  expect(generate.mock.calls[0][0][0].id).toBe(data.claims.find(() => true)!.id
    ? generate.mock.calls[0][0][0].id : '');
  await screen.findByText(/queued for regeneration/);
});

test('detail has no Regenerate in static mode', () => {
  const data = makeData();
  render(<App data={data} />);
  fireEvent.click(document.querySelector('.tbody-row') as HTMLElement);
  expect(screen.queryByRole('button', { name: 'Regenerate' })).toBeNull();
});
```

(The first assertion's tautology guard is noise — replace it with a plain
`expect(generate.mock.calls[0][0]).toHaveLength(1);` when writing the file;
it is shown here only to flag that the exact claim opened depends on
`visibleSorted` order — assert on length, not a specific id.)

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/__tests__/generate.test.tsx`
Expected: FAIL — no Regenerate button.

- [ ] **Step 3: AppealCard — button + banner copy**

Add `onRegenerate?: () => void;` to `Props`. In the failed-claim banner,
change the body line to:

```tsx
          <div className="b">
            {p.claim.error ?? 'This record failed during batch processing.'}{' '}
            {p.onRegenerate
              ? 'Regenerate it below or write the appeal manually.'
              : 'Write the appeal manually or re-run the batch for this claim.'}
          </div>
```

In the actions row, the failed branch becomes:

```tsx
        ) : failed ? (
          <>
            {p.onRegenerate && (
              <button type="button" className="btn-primary" onClick={p.onRegenerate}>
                Regenerate
              </button>
            )}
            {p.onDismiss && !showReason && (
              <button type="button" className="btn" onClick={() => setShowReason(true)}>Dismiss</button>
            )}
          </>
        ) : (
```

and in the normal (draft) branch add after the "Revert draft" button:

```tsx
            {p.onRegenerate && (
              <button type="button" className="btn" onClick={p.onRegenerate}>Regenerate</button>
            )}
```

- [ ] **Step 4: DetailScreen passthrough**

Add `onRegenerate?: () => void;` to its `Props` and pass
`onRegenerate={p.onRegenerate}` into `<AppealCard …>`.

- [ ] **Step 5: App.tsx — wire it**

In the detail branch, alongside `onDismiss`/`onRestore`, add:

```tsx
          onRegenerate={
            mutations?.generate
              && ['Draft Ready', 'Failed'].includes(effectiveStatus(claim, statusOverrides))
              ? () => {
                mutations.generate!([claim]).then(({ queued }) => {
                  if (queued) {
                    setLetters((l) => {
                      const next = { ...l };
                      delete next[claim.id];
                      return next;
                    });
                    showToast(`${claim.id} queued for regeneration`);
                  } else {
                    showToast(`${claim.id} cannot be regenerated right now`);
                  }
                }).catch((e) => showToast(String((e as Error).message ?? e)));
              }
              : undefined
          }
```

- [ ] **Step 6: Run the full suite**

Run: `cd frontend && npm test -- --run` → PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/detail/AppealCard.tsx frontend/src/components/detail/DetailScreen.tsx frontend/src/App.tsx frontend/src/__tests__/generate.test.tsx
git commit -m "generate: per-claim Regenerate on the detail screen"
```

---

### Task 4: e2e flow + template rebuild + full verification

**Files:**
- Create: `frontend/e2e/generate.spec.ts`
- Modify: `overturn/templates/workbench.html` (generated)

**Interfaces:**
- Consumes: everything above; the compose stack at :8000.
- Produces: nothing downstream.

- [ ] **Step 1: Write the e2e spec**

```ts
// frontend/e2e/generate.spec.ts
import { expect, test } from '@playwright/test';

const STAMP = Date.now();
const CSV = `claim_id,payer,carc_code,rarc_codes,denial_reason_text,billed_amount,service_date,denial_date,appeal_deadline
CLM-GEN-${STAMP}-1,Synthetic Payer A,CO-50,N115,Not deemed a medical necessity.,1200.00,2026-04-10,2026-05-01,2026-09-30
CLM-GEN-${STAMP}-2,Synthetic Payer B,CO-197,M62,Authorization absent.,845.50,2026-04-12,2026-05-02,2026-10-15
`;

test('worklist Generate Appeals and detail Regenerate re-draft claims', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.getByLabel(/email/i).fill(process.env.E2E_EMAIL ?? 'admin@example.com');
  await page.getByLabel(/password/i).fill(process.env.E2E_PASSWORD ?? 'change-me-locally');
  await page.getByRole('button', { name: /log in/i }).click();

  await page.setInputFiles('input[type=file]', {
    name: `gen-${STAMP}.csv`, mimeType: 'text/csv', buffer: Buffer.from(CSV),
  });
  await page.getByRole('button', { name: /upload/i }).click();
  const row = page.locator('.audit-row', { hasText: `gen-${STAMP}.csv` }).first();
  await expect(row.getByText('completed')).toBeVisible({ timeout: 90_000 });
  await row.click();

  // bulk: select all → Generate Appeals → drafts come back
  await expect(page.getByText(`CLM-GEN-${STAMP}-1`)).toBeVisible();
  await page.locator('.thead .cbox').click();
  await page.getByRole('button', { name: 'Generate Appeals' }).click();
  await expect(page.getByText(/Appeal generation queued for 2 claims/)).toBeVisible();
  await expect(page.locator('.st', { hasText: 'Draft Ready' })).toHaveCount(2, { timeout: 90_000 });

  // detail: Regenerate a single claim
  await page.getByText(`CLM-GEN-${STAMP}-1`).click();
  await page.getByRole('button', { name: 'Regenerate' }).click();
  await expect(page.getByText(/queued for regeneration/)).toBeVisible();
  await expect(page.locator('.d-head .st', { hasText: 'Draft Ready' }))
    .toBeVisible({ timeout: 90_000 });
  await expect(page.locator('.letter')).not.toBeEmpty();
});
```

If the status-pill locator is ambiguous (pills also appear in the filter
rail counts), scope it to the table: `page.locator('.table-card .st', …)`
— check the rendered DOM rather than guessing.

- [ ] **Step 2: Rebuild both frontend targets**

Run: `cd frontend && npm run build:template && npm run build:app`
Expected: success; `overturn/templates/workbench.html` modified.

- [ ] **Step 3: Rebuild the stack and run all e2e specs**

```bash
docker compose up -d --build web worker
cd frontend && npx playwright test
```

Expected: all specs pass (existing 4 + this one).

- [ ] **Step 4: Full sweep**

Run: `cd frontend && npm test -- --run` and `.venv/bin/pytest -q` from the
repo root. Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/generate.spec.ts overturn/templates/workbench.html
git commit -m "generate: e2e regeneration flow; rebuild committed workbench template"
```
