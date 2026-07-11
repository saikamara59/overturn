# Dismiss Claims Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reversible "won't appeal" dismissal for claims — with optional reason, hidden-by-default filtering, audit trail — in the served app only.

**Architecture:** One nullable column (`claims.dismiss_reason`, migration 0003) plus two new PATCH transitions (`dismissed`, `restored`) on the existing claim status machine; API writes `claim_dismissed`/`claim_restored` audit rows directly. Frontend threads `dismiss`/`restore` through `WorkbenchMutations` (API mode only), hides Dismissed from default worklist views, and renders a banner+Restore state on dismissed claims.

**Tech Stack:** Existing Phase 2 stack; no new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-11-dismiss-claims-design.md`.
- Reason values exactly: `payer_correct | too_small | deadline_passed | other`; optional; 422 on anything else.
- Dismiss allowed only from `draft_ready` or `failed` (409 otherwise); restore only from `dismissed` → `draft_ready` if letter else `failed`; letter edits 409 while dismissed; demo 409 and cross-org 404 guards unchanged.
- Retry must never re-queue dismissed claims.
- Island (static-report) build byte-identical: no Dismiss UI without `mutations`; `npm run build:template` output unchanged.
- Baselines before starting: pytest 102, vitest 53, e2e 2 (Postgres container up).
- Every commit message ends with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: Backend — migration, PATCH transitions, audit rows, payloads, retry exclusion

**Files:**
- Modify: `server/models.py` (Claim gains `dismiss_reason`)
- Create: `server/migrations/versions/0003_dismiss_reason.py`
- Modify: `server/api/claims.py` (transition machine + audit helper)
- Modify: `server/payloads.py` (`DISPLAY_STATUS`, `claim_entry`, `worklist_payload` summary)
- Modify: `server/api/runs.py` (retry exclusion)
- Test: `tests/server/test_dismiss.py`

**Interfaces:**
- Produces: `PATCH /api/v1/claims/{id}` additionally accepts `{"status": "dismissed", "dismissReason"?: str}` and `{"status": "restored"}`; `claim_entry` gains `"dismissReason": str | None`; `worklist_payload["summary"]` gains `"dismissed": int`; `DISPLAY_STATUS["dismissed"] == "Dismissed"`. `DISMISS_REASONS` frozenset exported from `server/api/claims.py`.

- [ ] **Step 1: Write the failing tests**

`tests/server/test_dismiss.py`:

```python
import uuid

from server.models import AuditEvent, Claim, Run
from tests.server.conftest import login
from tests.server.test_claims_api import drafted_run


def claims_of(client, run_id):
    return client.get(f"/api/v1/runs/{run_id}/claims").json()["claims"]


def test_dismiss_from_draft_ready_with_reason(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entry = claims_of(client, run_id)[0]

    r = client.patch(f"/api/v1/claims/{entry['dbId']}",
                     json={"status": "dismissed", "dismissReason": "too_small"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "Dismissed"
    assert body["dismissReason"] == "too_small"

    data = client.get(f"/api/v1/runs/{run_id}/claims").json()
    assert data["summary"]["dismissed"] == 1
    # pipeline counters untouched
    assert data["summary"]["drafts"] == 3

    with session_factory() as s:
        ev = s.query(AuditEvent).filter_by(event_type="claim_dismissed").one()
        assert ev.details["claim_id"] == entry["id"]
        assert ev.details["reason"] == "too_small"


def test_dismiss_without_reason_and_from_failed(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    with session_factory() as s:
        c = s.get(Claim, uuid.UUID(entries[1]["dbId"]))
        c.status = "failed"
        c.letter = None
        s.commit()

    ok = client.patch(f"/api/v1/claims/{entries[0]['dbId']}",
                      json={"status": "dismissed"})
    assert ok.status_code == 200 and ok.json()["dismissReason"] is None
    ok2 = client.patch(f"/api/v1/claims/{entries[1]['dbId']}",
                       json={"status": "dismissed"})
    assert ok2.status_code == 200


def test_dismiss_transition_guards(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    db_id = entries[0]["dbId"]

    # invalid reason
    assert client.patch(f"/api/v1/claims/{db_id}",
                        json={"status": "dismissed", "dismissReason": "meh"}
                        ).status_code == 422
    # submitted claims cannot be dismissed
    client.patch(f"/api/v1/claims/{db_id}", json={"status": "submitted"})
    assert client.patch(f"/api/v1/claims/{db_id}",
                        json={"status": "dismissed"}).status_code == 409
    # queued claims cannot be dismissed
    other = entries[1]["dbId"]
    with session_factory() as s:
        s.get(Claim, uuid.UUID(other)).status = "queued"
        s.commit()
    assert client.patch(f"/api/v1/claims/{other}",
                        json={"status": "dismissed"}).status_code == 409


def test_restore_paths_and_guards(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    with_letter, without = entries[0]["dbId"], entries[1]["dbId"]
    with session_factory() as s:
        c = s.get(Claim, uuid.UUID(without))
        c.status = "failed"
        c.letter = None
        s.commit()
    client.patch(f"/api/v1/claims/{with_letter}", json={"status": "dismissed"})
    client.patch(f"/api/v1/claims/{without}", json={"status": "dismissed"})

    # restore not allowed on non-dismissed
    active = entries[2]["dbId"]
    assert client.patch(f"/api/v1/claims/{active}",
                        json={"status": "restored"}).status_code == 409
    # letter edit blocked while dismissed
    assert client.patch(f"/api/v1/claims/{with_letter}",
                        json={"letter": "nope"}).status_code == 409

    r1 = client.patch(f"/api/v1/claims/{with_letter}", json={"status": "restored"})
    assert r1.status_code == 200 and r1.json()["status"] == "Draft Ready"
    assert r1.json()["dismissReason"] is None
    r2 = client.patch(f"/api/v1/claims/{without}", json={"status": "restored"})
    assert r2.status_code == 200 and r2.json()["status"] == "Failed"

    with session_factory() as s:
        evs = s.query(AuditEvent).filter_by(event_type="claim_restored").all()
        assert {e.details["restored_to"] for e in evs} == {"draft_ready", "failed"}


def test_retry_never_requeues_dismissed(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    client.patch(f"/api/v1/claims/{entries[0]['dbId']}",
                 json={"status": "dismissed"})
    with session_factory() as s:
        s.get(Claim, uuid.UUID(entries[1]["dbId"])).status = "failed"
        s.commit()

    r = client.post(f"/api/v1/runs/{run_id}/retry")
    assert r.json() == {"requeued": 1}  # only the failed one, not the dismissed
    with session_factory() as s:
        assert s.get(Claim, uuid.UUID(entries[0]["dbId"])).status == "dismissed"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/server/test_dismiss.py -q`
Expected: FAIL (422/409s from the current machine; missing fields).

- [ ] **Step 3: Implement**

`server/models.py` — on `Claim`, after `error`:

```python
    dismiss_reason: Mapped[str | None] = mapped_column(Text, default=None)
```

`server/migrations/versions/0003_dismiss_reason.py` (down_revision = `"0002_multi_tenancy"`):

```python
"""claims.dismiss_reason for won't-appeal dismissals"""
import sqlalchemy as sa
from alembic import op

revision = "0003_dismiss_reason"
down_revision = "0002_multi_tenancy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("claims", sa.Column("dismiss_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("claims", "dismiss_reason")
```

Apply: `DATABASE_URL=postgresql+psycopg://overturn:overturn@localhost:5433/overturn .venv/bin/alembic upgrade head`

`server/payloads.py`:
- `DISPLAY_STATUS` gains `"dismissed": "Dismissed"`.
- `claim_entry` return dict gains `"dismissReason": claim.dismiss_reason,`.
- `worklist_payload` summary becomes:

```python
        "summary": {
            "processed": run.total_records,
            "drafts": run.drafted,
            "failed": run.failed_records,
            "dismissed": sum(1 for c in claims if c.status == "dismissed"),
        },
```

`server/api/claims.py` — replace `ClaimPatch` and `patch_claim`:

```python
DISMISS_REASONS = frozenset({"payer_correct", "too_small", "deadline_passed", "other"})


class ClaimPatch(BaseModel):
    letter: str | None = None
    status: str | None = None
    dismissReason: str | None = None


def _audit(session: Session, run_id: uuid.UUID, event_type: str, details: dict) -> None:
    from server.models import AuditEvent

    session.add(AuditEvent(run_id=run_id, ts=utcnow(),
                           event_type=event_type, details=details))


@router.patch("/{claim_id}")
def patch_claim(
    patch: ClaimPatch,
    claim: Claim = Depends(scoped_claim),
    session: Session = Depends(get_session),
) -> dict:
    if claim.run.is_demo:
        raise HTTPException(409, detail="demo run is read-only")

    if patch.status == "dismissed":
        if claim.status not in ("draft_ready", "failed"):
            raise HTTPException(409, detail=f"cannot dismiss a {claim.status} claim")
        if patch.dismissReason is not None and patch.dismissReason not in DISMISS_REASONS:
            raise HTTPException(422, detail="unknown dismissal reason")
        claim.status = "dismissed"
        claim.dismiss_reason = patch.dismissReason
        _audit(session, claim.run_id, "claim_dismissed",
               {"claim_id": claim.claim_id, "reason": patch.dismissReason})
    elif patch.status == "restored":
        if claim.status != "dismissed":
            raise HTTPException(409, detail="only dismissed claims can be restored")
        restored_to = "draft_ready" if claim.letter else "failed"
        claim.status = restored_to
        claim.dismiss_reason = None
        _audit(session, claim.run_id, "claim_restored",
               {"claim_id": claim.claim_id, "restored_to": restored_to})
    elif patch.status == "submitted":
        if claim.status not in ("draft_ready", "submitted"):
            raise HTTPException(409, detail=f"claim is {claim.status}; not editable yet")
        claim.status = "submitted"
    elif patch.status is not None:
        raise HTTPException(422, detail="status may be 'submitted', 'dismissed', or 'restored'")

    if "letter" in patch.model_fields_set:
        if claim.status not in ("draft_ready", "submitted"):
            raise HTTPException(409, detail=f"claim is {claim.status}; letter not editable")
        claim.letter = claim.letter_original if patch.letter is None else patch.letter
    claim.updated_at = utcnow()
    return claim_entry(claim, date.today())
```

(Note: the letter-edit gate now derives from the possibly-updated status, so
a combined dismiss+letter patch correctly 409s on the letter part. Imports:
add `utcnow` from `server.models` if not present.)

`server/api/runs.py` `retry_run` — the requeue condition becomes:

```python
        if claim.status not in ("draft_ready", "submitted", "dismissed"):
```

(the counter recompute lines below it already exclude dismissed because they
count only `draft_ready|submitted` and `failed`).

- [ ] **Step 4: Run to verify pass; commit**

Run: `.venv/bin/python -m pytest tests/ -q` — expect 107 passed (102 + 5).

```bash
git add server/ tests/server/test_dismiss.py
git commit -m "dismiss: backend — transitions, audit rows, payloads, retry exclusion"
```

---

### Task 2: Frontend logic — types, filtering, mutations wiring

**Files:**
- Modify: `frontend/src/types.ts` (Claim.dismissReason; summary.dismissed optional)
- Modify: `frontend/src/lib/worklist.ts` (statusStyle, visibleSorted hide rule, filterGroups exclusion)
- Modify: `frontend/src/App.tsx` (WorkbenchMutations dismiss/restore; handlers; local dismissReasons)
- Modify: `frontend/src/app/ServerApp.tsx` (makeMutations gains dismiss/restore via patchClaim)
- Test: extend `frontend/src/lib/__tests__/worklist.test.ts` and `frontend/src/__tests__/workbench-mutations.test.tsx`

**Interfaces:**
- Produces: `WorkbenchMutations` gains `dismiss(c: Claim, reason?: string): Promise<Claim>` and `restore(c: Claim): Promise<Claim>` (returned Claim is the server's updated entry; App applies `statusOverrides[c.id] = returned.status` and tracks `dismissReasons[c.id]`). `visibleSorted` hides claims whose effective status is `'Dismissed'` unless `filters.fStatus.includes('Dismissed')`. `filterGroups`: CARC/Payer/Deadline counts exclude dismissed; Status group lists Dismissed with its true count. App passes `onDismiss(reason?: string)` and `onRestore` down to `DetailScreen` (Task 3 renders them; this task threads no-op-safe props).
- `types.ts`: `Claim` gains `dismissReason?: string | null`; `WorkbenchData['summary']` gains `dismissed?: number` (optional — island payloads lack it).

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/lib/__tests__/worklist.test.ts`:

```ts
describe('dismissed filtering', () => {
  const claims = [
    claim({ id: 'A', days: 5 }),
    claim({ id: 'B', days: 6 }),
  ];
  const noFilters = { fCarc: [], fPayer: [], fStatus: [], fBucket: [] };
  const overrides = { B: 'Dismissed' };

  test('dismissed hidden by default', () => {
    const ids = visibleSorted(claims, noFilters, { col: 'urgency', dir: 'asc' }, overrides).map(c => c.id);
    expect(ids).toEqual(['A']);
  });

  test('Dismissed status filter reveals them', () => {
    const ids = visibleSorted(claims, { ...noFilters, fStatus: ['Dismissed'] },
      { col: 'urgency', dir: 'asc' }, overrides).map(c => c.id);
    expect(ids).toEqual(['B']);
  });

  test('non-status filter counts exclude dismissed', () => {
    const groups = filterGroups(claims, overrides);
    const carc = groups.find(g => g.key === 'fCarc')!;
    expect(carc.items.find(i => i.label === 'CO-50')!.count).toBe(1);
    const status = groups.find(g => g.key === 'fStatus')!;
    expect(status.items.find(i => i.label === 'Dismissed')!.count).toBe(1);
  });

  test('statusStyle knows Dismissed', () => {
    expect(statusStyle('Dismissed').cls).toBe('c-gray');
  });
});
```

(add `filterGroups`, `statusStyle` to the existing import from `../worklist`.)

Append to `frontend/src/__tests__/workbench-mutations.test.tsx` (extend the
`mutations()` helper with `dismiss: vi.fn().mockResolvedValue({ status: 'Dismissed' }), restore: vi.fn().mockResolvedValue({ status: 'Draft Ready' })`):

```tsx
test('dismiss mutation is threaded and applies the override', async () => {
  const m = mutations();
  render(<App data={SAMPLE_DATA} mutations={m} />);
  await userEvent.click(screen.getByText('CLM-0001'));
  await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
  await userEvent.click(screen.getByRole('button', { name: /confirm dismiss/i }));
  expect(m.dismiss).toHaveBeenCalledOnce();
  expect(await screen.findByText(/dismissed/i)).toBeInTheDocument();
});
```

(This test also exercises Task 3's UI; it is written now and will pass at the
end of Task 3 — for THIS task run only the worklist lib tests plus a
compile-green suite with the UI test marked `test.todo` if needed. Simplest:
add the UI test in Task 3 instead if it blocks; the lib tests are Task 2's
gate.)

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/lib/__tests__/worklist.test.ts`
Expected: FAIL (no hide rule, no Dismissed style, filterGroups signature).

- [ ] **Step 3: Implement**

`types.ts`: add to `Claim`: `dismissReason?: string | null;` and change
`WorkbenchData` summary to `{ processed: number; drafts: number; failed: number; dismissed?: number }`.

`lib/worklist.ts`:
- `statusStyle` map gains `Dismissed: { cls: 'c-gray', dot: 'var(--gray-dot)' },`.
- In `visibleSorted`, extend the filter predicate's status logic:

```ts
  const showDismissed = filters.fStatus.includes('Dismissed');
  const visible = claims.filter((c) => {
    const st = effectiveStatus(c, overrides);
    if (st === 'Dismissed' && !showDismissed) return false;
    return (
      (!filters.fCarc.length || filters.fCarc.includes(c.carc)) &&
      (!filters.fPayer.length || filters.fPayer.includes(c.payer)) &&
      (!filters.fStatus.length || filters.fStatus.includes(st)) &&
      (!filters.fBucket.length || filters.fBucket.includes(bucketOf(c)))
    );
  });
```

- In `filterGroups`, count non-status groups over active (non-dismissed)
  claims only:

```ts
  const active = claims.filter((c) => effectiveStatus(c, overrides) !== 'Dismissed');
  const count = (fn: (c: Claim) => boolean) => active.filter(fn).length;
```

  and the Status group keeps counting over ALL claims per status:

```ts
      items: uniq(claims.map((c) => effectiveStatus(c, overrides))).map((v) => ({
        label: v,
        count: claims.filter((c) => effectiveStatus(c, overrides) === v).length,
      })),
```

`App.tsx`:
- Interface:

```ts
export interface WorkbenchMutations {
  approve(c: Claim): Promise<void>;
  saveLetter(c: Claim, text: string): Promise<void>;
  revertLetter(c: Claim): Promise<string>;
  dismiss(c: Claim, reason?: string): Promise<Claim>;
  restore(c: Claim): Promise<Claim>;
}
```

- State: `const [dismissReasons, setDismissReasons] = useState<Record<string, string | undefined>>({});`
- Detail-branch handlers (pass to DetailScreen; Task 3 consumes):

```tsx
          onDismiss={mutations ? (reason?: string) => {
            mutations.dismiss(claim, reason).then((updated) => {
              setStatusOverrides((o) => ({ ...o, [claim.id]: updated.status as string }));
              setDismissReasons((d) => ({ ...d, [claim.id]: reason }));
              showToast(`${claim.id} dismissed — won't appeal`);
            }).catch((e) => showToast(String((e as Error).message ?? e)));
          } : undefined}
          onRestore={mutations ? () => {
            mutations.restore(claim).then((updated) => {
              setStatusOverrides((o) => ({ ...o, [claim.id]: updated.status as string }));
              setDismissReasons((d) => ({ ...d, [claim.id]: undefined }));
              showToast(`${claim.id} restored to the worklist`);
            }).catch((e) => showToast(String((e as Error).message ?? e)));
          } : undefined}
          dismissReason={dismissReasons[claim.id] ?? claim.dismissReason ?? undefined}
```

  (DetailScreen accepts these three new optional props in Task 3; for this
  task, add them to `DetailScreen`'s Props as optional and ignore them in the
  body so tsc passes: `onDismiss?: (reason?: string) => void; onRestore?: () => void; dismissReason?: string;`.)

`app/ServerApp.tsx` `makeMutations` gains:

```ts
    async dismiss(c, reason) {
      if (!c.dbId) throw new Error('read-only view');
      return patchClaim(c.dbId, { status: 'dismissed', dismissReason: reason ?? null });
    },
    async restore(c) {
      if (!c.dbId) throw new Error('read-only view');
      return patchClaim(c.dbId, { status: 'restored' });
    },
```

and `api.ts` `patchClaim`'s body type widens to
`{ letter?: string | null; status?: 'submitted' | 'dismissed' | 'restored'; dismissReason?: string | null }`.

- [ ] **Step 4: Run to verify pass; commit**

Run: `cd frontend && npm test && npm run build:app && npm run build:template`
Expected: lib tests green, suite green (53 + 4 new lib tests), builds clean,
template bytes unchanged.

```bash
git add frontend/src
git commit -m "dismiss: frontend logic — filtering, mutations, type plumbing"
```

---

### Task 3: Frontend UI — dismiss/restore controls, banner, summary note

**Files:**
- Modify: `frontend/src/components/detail/AppealCard.tsx` (Dismiss button + reason picker; dismissed banner + Restore; read-only letter)
- Modify: `frontend/src/components/detail/DetailScreen.tsx` (thread props)
- Modify: `frontend/src/components/summary/SummaryScreen.tsx` (dismissed note)
- Test: extend `frontend/src/__tests__/workbench-mutations.test.tsx` and `frontend/src/__tests__/detail-screen.test.tsx`

**Interfaces:**
- Consumes Task 2's props: `onDismiss?: (reason?: string) => void`, `onRestore?: () => void`, `dismissReason?: string`.
- Produces: `REASON_LABELS` exported from `AppealCard.tsx`:
  `{ payer_correct: 'payer was correct', too_small: 'amount too small', deadline_passed: 'deadline passed', other: 'other' }`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/__tests__/workbench-mutations.test.tsx` (and extend the
`mutations()` helper as described in Task 2 if not already done):

```tsx
test('dismiss flow: button → reason picker → mutation → dismissed banner', async () => {
  const m = mutations();
  render(<App data={SAMPLE_DATA} mutations={m} />);
  await userEvent.click(screen.getByText('CLM-0001'));
  await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
  await userEvent.selectOptions(screen.getByLabelText(/reason/i), 'too_small');
  await userEvent.click(screen.getByRole('button', { name: /confirm dismiss/i }));
  expect(m.dismiss).toHaveBeenCalledWith(expect.anything(), 'too_small');
  expect(await screen.findByText(/won't appeal/i)).toBeInTheDocument();
  // actions replaced by Restore; letter read-only
  expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Restore' })).toBeInTheDocument();
  expect(screen.getByRole('textbox')).toBeDisabled();
});

test('restore flow returns claim to worklist state', async () => {
  const m = mutations();
  render(<App data={SAMPLE_DATA} mutations={m} />);
  await userEvent.click(screen.getByText('CLM-0001'));
  await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
  await userEvent.click(screen.getByRole('button', { name: /confirm dismiss/i }));
  await userEvent.click(await screen.findByRole('button', { name: 'Restore' }));
  expect(m.restore).toHaveBeenCalledOnce();
  expect(await screen.findByRole('button', { name: 'Approve' })).toBeInTheDocument();
});
```

Append to `frontend/src/__tests__/detail-screen.test.tsx`:

```tsx
test('island mode shows no Dismiss button', async () => {
  await openClaim('CLM-0001');
  expect(screen.queryByRole('button', { name: 'Dismiss' })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/__tests__/workbench-mutations.test.tsx src/__tests__/detail-screen.test.tsx`
Expected: FAIL (no Dismiss button).

- [ ] **Step 3: Implement**

`AppealCard.tsx` — props gain
`status: string; onDismiss?: (reason?: string) => void; onRestore?: () => void; dismissReason?: string;`
(replace the current `failed: boolean` prop with `status`, deriving
`const failed = p.status === 'Failed'; const dismissed = p.status === 'Dismissed';`).
Add:

```tsx
export const REASON_LABELS: Record<string, string> = {
  payer_correct: 'payer was correct',
  too_small: 'amount too small',
  deadline_passed: 'deadline passed',
  other: 'other',
};
```

- Local state `const [showReason, setShowReason] = useState(false);`
  `const [reason, setReason] = useState('');`
- Dismissed rendering: above the actions bar, when `dismissed`:

```tsx
      {dismissed && (
        <div className="fail-banner" style={{ background: 'var(--gray-bg)', borderColor: 'var(--line-2)' }}>
          <div className="t" style={{ color: 'var(--gray-fg)' }}>
            Dismissed — won't appeal{p.dismissReason ? ` (${REASON_LABELS[p.dismissReason] ?? p.dismissReason})` : ''}
          </div>
        </div>
      )}
```

- The letter textarea gains `disabled={dismissed}` and its `onChange` guards
  on `dismissed`; render it for dismissed claims that have a letter (reuse
  the existing `hasLetter` logic: dismissed-without-letter shows the fail
  banner content as today's failed path did — keep the failed banner for
  `failed`, the dismissed banner for `dismissed`).
- Actions bar:

```tsx
      <div className="actions">
        {dismissed ? (
          p.onRestore && (
            <button type="button" className="btn-primary" onClick={p.onRestore}>Restore</button>
          )
        ) : failed ? (
          p.onDismiss && !showReason && (
            <button type="button" className="btn" onClick={() => setShowReason(true)}>Dismiss</button>
          )
        ) : (
          <>
            <button type="button" className="btn-primary" onClick={p.onApprove}>Approve</button>
            <button type="button" className="btn" onClick={() => textareaRef.current?.focus()}>Edit</button>
            <button type="button" className="btn" onClick={p.onRevert}>Revert draft</button>
            {p.onDismiss && !showReason && (
              <button type="button" className="btn" onClick={() => setShowReason(true)}>Dismiss</button>
            )}
          </>
        )}
        {showReason && !dismissed && (
          <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
            <label style={{ fontSize: 12.5, color: 'var(--mut)' }}>
              Reason
              <select value={reason} onChange={(e) => setReason(e.target.value)}
                      style={{ font: 'inherit', fontSize: 12.5, marginLeft: 6 }}>
                <option value="">(none)</option>
                {Object.entries(REASON_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </label>
            <button type="button" className="btn"
                    onClick={() => { p.onDismiss?.(reason || undefined); setShowReason(false); }}>
              Confirm dismiss
            </button>
            <button type="button" className="btn" onClick={() => setShowReason(false)}>Cancel</button>
          </span>
        )}
        <div className="spacer" />
        {!failed && !dismissed && (
          /* existing Export letter button unchanged */
        )}
      </div>
```

`DetailScreen.tsx`: props gain the three optionals; pass `status={p.status}`
(replacing `failed={p.status === 'Failed'}`) plus `onDismiss/onRestore/dismissReason`
through to `AppealCard`.

`SummaryScreen.tsx`: in the deadline panel, after the hot-claims note:

```tsx
            {(data.summary.dismissed ?? 0) > 0 && (
              <div className="sm-note">
                {data.summary.dismissed} dismissed (won't appeal).
              </div>
            )}
```

- [ ] **Step 4: Run to verify pass; commit**

Run: `cd frontend && npm test && npm run build:app && npm run build:template`
Expected: all green (Task 2 baseline + 3 new); template bytes unchanged
(island mode passes `onDismiss=undefined`, so no Dismiss UI renders — the
island `detail-screen` test asserts it).

```bash
git add frontend/src
git commit -m "dismiss: frontend UI — reason picker, dismissed banner, restore, summary note"
```

---

### Task 4: E2E + full verification

**Files:**
- Modify: `frontend/e2e/server.spec.ts` (extend the Phase 1 persistence spec)
- Test: full suites against the rebuilt stack

**Interfaces:**
- Consumes the compose stack (rebuild with the new code).

- [ ] **Step 1: Extend the e2e**

In the existing `upload → draft → approve → persists across reload` spec,
after the reload-assert block, append (the spec uploads 2 claims; CLM-E2E-2
is still Draft Ready):

```ts
  // dismiss the second claim with a reason; it leaves the default worklist
  await page.getByText('CLM-E2E-2').click();
  await page.getByRole('button', { name: 'Dismiss' }).click();
  await page.getByLabel(/reason/i).selectOption('too_small');
  await page.getByRole('button', { name: /confirm dismiss/i }).click();
  await expect(page.getByText(/won't appeal/i)).toBeVisible();

  await page.getByRole('button', { name: '← Worklist' }).click();
  await expect(page.getByText('CLM-E2E-2')).not.toBeVisible();

  // reload → still dismissed; reveal via the status filter and restore
  await page.reload();
  await expect(page.getByText('CLM-E2E-2')).not.toBeVisible();
  await page.getByRole('button', { name: /Dismissed/ }).click();  // status filter row
  await page.getByText('CLM-E2E-2').click();
  await page.getByRole('button', { name: 'Restore' }).click();
  await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible();
```

(Note: each e2e run uploads a fresh `e2e-denials.csv`, so `getByText('CLM-E2E-2')`
may match rows from previous runs in the persistent dev DB — scope the
locators with `.first()` where strict-mode complains, consistent with the
existing spec's `.first()` usage.)

- [ ] **Step 2: Rebuild and run everything**

```bash
docker compose up -d --build web worker
.venv/bin/python -m pytest tests/ -q
cd frontend && npm test && npm run e2e
```

Expected: pytest 107, vitest all green, e2e 2 passed (the extended
persistence spec + onboarding spec).

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e
git commit -m "dismiss: e2e — dismiss, filter reveal, restore across reload"
```

---

## Self-Review Notes

- Spec coverage: migration+transitions+audit+payload+retry (T1), filtering +
  mutations + types (T2), UI incl. island-gating + summary note (T3),
  e2e (T4). Out-of-scope items have no tasks.
- Type consistency: `WorkbenchMutations.dismiss/restore` return `Promise<Claim>`
  and App uses `updated.status`; `patchClaim` body widened in T2 matches T1's
  wire format (`dismissReason` key); `REASON_LABELS` keys equal the backend
  `DISMISS_REASONS` values.
- T2's `AppealCard` prop change (`failed: boolean` → `status: string`) is
  executed in T3; T2 only adds optional props to `DetailScreen` so tsc stays
  green mid-sequence.
- The workbench-mutations dismiss test in T2 Step 1 is deferred to T3 (noted
  inline) — T2's gate is the lib tests + builds.
