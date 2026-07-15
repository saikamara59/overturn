# Mobile Responsive Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the updated "Overturn v2.dc.html" mobile design (760px breakpoint: chip filters + card list on the worklist, stacked detail, 2×2 summary stats, new brand lockup) across both frontend build targets, and extend the same breakpoint to the SPA-only screens.

**Architecture:** One `useIsMobile()` matchMedia hook drives structural swaps (filter rail ↔ chip row, table ↔ card list); everything style-only is a `@media (max-width: 759px)` rule in `frontend/src/styles.css`. Shared components mean the static report template and the served SPA both become responsive; the committed template is rebuilt at the end.

**Tech Stack:** React 18 + TypeScript, Vite, Vitest + React Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-07-15-mobile-responsive-design.md`

## Global Constraints

- Breakpoint is exactly 760px: hook query `(max-width: 759px)`, CSS `@media (max-width: 759px)`.
- No server/API changes. No changes to `overturn/` Python code.
- `overturn/templates/workbench.html` is generated — never hand-edit; rebuild with `cd frontend && npm run build:template` (Task 6) and commit the result. CI fails the PR if it is out of sync.
- All frontend commands run from `frontend/`. Tests: `npm test -- --run`. Full suite must pass before each commit.
- Work on branch `mobile-responsive`. Commit after every task.
- Do NOT update Linear or the local task list — the controller owns those gates.

## File Structure

- `frontend/src/lib/useIsMobile.ts` — new: the breakpoint hook (only structural-swap consumer state).
- `frontend/src/__tests__/helpers/matchMedia.ts` — new: jsdom matchMedia stub + per-test viewport switch.
- `frontend/src/vitest.setup.ts` — installs the stub globally.
- `frontend/src/components/TopBar.tsx` — brand lockup rewrite.
- `frontend/src/components/worklist/MobileChips.tsx` — new: quick-filter chips.
- `frontend/src/components/worklist/ClaimCards.tsx` — new: mobile card list.
- `frontend/src/components/worklist/WorklistScreen.tsx` — mobile/desktop swap.
- `frontend/src/components/worklist/StatsStrip.tsx` — class hook for hiding "Showing".
- `frontend/src/app/ServerApp.tsx` — chrome inline styles → classes.
- `frontend/src/styles.css` — all media queries + new component styles.
- `frontend/e2e/mobile.spec.ts` — new: 390×844 demo flow.
- `overturn/templates/workbench.html` — rebuilt artifact (Task 6).

---

### Task 1: Viewport hook + test infrastructure

**Files:**
- Create: `frontend/src/lib/useIsMobile.ts`
- Create: `frontend/src/__tests__/helpers/matchMedia.ts`
- Modify: `frontend/src/vitest.setup.ts`
- Test: `frontend/src/__tests__/use-is-mobile.test.tsx`

**Interfaces:**
- Consumes: nothing.
- Produces: `useIsMobile(): boolean` and `MOBILE_QUERY = '(max-width: 759px)'` from `../lib/useIsMobile`; test helpers `setViewportMobile(mobile: boolean): void` and `resetViewport(): void` from `./helpers/matchMedia` (Tasks 2–5 use these in tests; jsdom has no native matchMedia, so the stub is global).

- [ ] **Step 1: Write the matchMedia stub helper**

```ts
// frontend/src/__tests__/helpers/matchMedia.ts
type Listener = (e: { matches: boolean }) => void;

let mobile = false;
const listeners = new Set<Listener>();

/** Installed once from vitest.setup.ts — jsdom has no matchMedia. */
export function installMatchMedia(): void {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      get matches() {
        // Our app only queries the mobile breakpoint; anything else is false.
        return query.includes('max-width') ? mobile : false;
      },
      media: query,
      addEventListener: (_: 'change', fn: Listener) => listeners.add(fn),
      removeEventListener: (_: 'change', fn: Listener) => listeners.delete(fn),
      onchange: null,
      addListener: (fn: Listener) => listeners.add(fn),
      removeListener: (fn: Listener) => listeners.delete(fn),
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}

/** Switch the simulated viewport; notifies mounted hooks. */
export function setViewportMobile(next: boolean): void {
  mobile = next;
  listeners.forEach((fn) => fn({ matches: next }));
}

export function resetViewport(): void {
  mobile = false;
  listeners.clear();
}
```

- [ ] **Step 2: Install it in vitest.setup.ts**

```ts
// frontend/src/vitest.setup.ts
import '@testing-library/jest-dom/vitest';
import { installMatchMedia } from './__tests__/helpers/matchMedia';

installMatchMedia();
```

- [ ] **Step 3: Write the failing hook test**

```tsx
// frontend/src/__tests__/use-is-mobile.test.tsx
import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';
import { useIsMobile } from '../lib/useIsMobile';
import { resetViewport, setViewportMobile } from './helpers/matchMedia';

afterEach(() => resetViewport());

test('defaults to desktop', () => {
  const { result } = renderHook(() => useIsMobile());
  expect(result.current).toBe(false);
});

test('tracks viewport changes both ways', () => {
  const { result } = renderHook(() => useIsMobile());
  act(() => setViewportMobile(true));
  expect(result.current).toBe(true);
  act(() => setViewportMobile(false));
  expect(result.current).toBe(false);
});

test('starts mobile when mounted under a mobile viewport', () => {
  setViewportMobile(true);
  const { result } = renderHook(() => useIsMobile());
  expect(result.current).toBe(true);
});
```

- [ ] **Step 4: Run to verify failure**

Run: `cd frontend && npx vitest run src/__tests__/use-is-mobile.test.tsx`
Expected: FAIL — cannot resolve `../lib/useIsMobile`.

- [ ] **Step 5: Implement the hook**

```ts
// frontend/src/lib/useIsMobile.ts
import { useEffect, useState } from 'react';

export const MOBILE_QUERY = '(max-width: 759px)';

/** True below the 760px design breakpoint; live-updates on resize. */
export function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(MOBILE_QUERY).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(MOBILE_QUERY);
    const onChange = (e: { matches: boolean }) => setMobile(e.matches);
    mq.addEventListener('change', onChange);
    setMobile(mq.matches);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return mobile;
}
```

- [ ] **Step 6: Run the full suite**

Run: `cd frontend && npm test -- --run`
Expected: PASS (new tests green; existing suites unaffected by the stub since it defaults to desktop).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/useIsMobile.ts frontend/src/__tests__/helpers/matchMedia.ts frontend/src/vitest.setup.ts frontend/src/__tests__/use-is-mobile.test.tsx
git commit -m "mobile: add useIsMobile breakpoint hook + matchMedia test stub"
```

---

### Task 2: Top-bar brand lockup + responsive top bar

**Files:**
- Modify: `frontend/src/components/TopBar.tsx`
- Modify: `frontend/src/styles.css` (brand rules + first media query)
- Test: `frontend/src/__tests__/topbar.test.tsx` (new)

**Interfaces:**
- Consumes: nothing new (pure markup/CSS).
- Produces: brand DOM `div.brand > div.brand-mark + div.brand-text > (.brand-name + .brand-sub)`. No prop changes — `TopBar` keeps `{ screen, onNavigate, generatedOn, asOf }`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/topbar.test.tsx
import { render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { TopBar } from '../components/TopBar';

test('renders the brand lockup with wordmark and subtitle', () => {
  render(<TopBar screen="worklist" onNavigate={vi.fn()} generatedOn="2026-07-05" asOf="2026-07-05" />);
  expect(screen.getByText('Overturn')).toBeInTheDocument();
  expect(screen.getByText('Denial Workbench')).toBeInTheDocument();
  expect(document.querySelector('.brand-mark svg path[fill="#FFFFFF"]')).not.toBeNull();
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/__tests__/topbar.test.tsx`
Expected: FAIL — "Denial Workbench" not found.

- [ ] **Step 3: Rewrite the brand block in TopBar.tsx**

Replace the current `<div className="brand">…</div>` (lines 14–23) with:

```tsx
      <div className="brand">
        <div className="brand-mark">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M20 12a8 8 0 1 1-3.2-6.4" stroke="#FFFFFF"
              strokeWidth="3" strokeLinecap="round" />
            <path d="M17.4 1.6 L16.8 7.3 L22.3 6.1 Z" fill="#FFFFFF" />
          </svg>
        </div>
        <div className="brand-text">
          <div className="brand-name">Overturn<span className="brand-dot">.</span></div>
          <div className="brand-sub">Denial Workbench</div>
        </div>
      </div>
```

Note: `getByText('Overturn')` still matches because the accent period is in its own span.

- [ ] **Step 4: Update styles.css**

Replace the `.brand`/`.brand-mark`/`.brand-name` rules (lines 24–26) with:

```css
.brand { display: flex; align-items: center; gap: 10px; }
.brand-mark { width: 30px; height: 30px; border-radius: 8px; background: var(--accent); box-shadow: inset 0 1px 0 rgba(255,255,255,0.25), 0 1px 3px rgba(46,91,218,0.5); display: flex; align-items: center; justify-content: center; }
.brand-text { display: flex; flex-direction: column; gap: 1px; }
.brand-name { font-size: 16px; font-weight: 700; letter-spacing: -0.02em; color: #FFF; line-height: 1; }
.brand-dot { color: #6E93F2; }
.brand-sub { font-family: var(--mono); font-size: 8.5px; font-weight: 500; letter-spacing: 0.18em; text-transform: uppercase; color: #8B8981; line-height: 1; }
```

Then append at the end of the `/* ---- top bar ---- */` section:

```css
@media (max-width: 759px) {
  .topbar { padding: 0 12px; gap: 12px; }
  .topbar-meta { display: none; }
}
```

- [ ] **Step 5: Run the full suite**

Run: `cd frontend && npm test -- --run`
Expected: PASS. If any existing test asserted on the old brand markup, update it to the new structure (the smoke test renders the whole app — `getByText('Overturn')` still resolves uniquely; if it reports multiple matches, scope with `document.querySelector('.brand-name')`).

- [ ] **Step 6: Visual sanity check**

Run: `cd frontend && npm run build:template && npm run build:app`
Expected: both builds succeed (template install script verifies the data-island marker).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/TopBar.tsx frontend/src/styles.css frontend/src/__tests__/topbar.test.tsx overturn/templates/workbench.html
git commit -m "mobile: new brand lockup, top-bar meta hidden on small screens"
```

---

### Task 3: Worklist mobile — quick-filter chips + card list

**Files:**
- Create: `frontend/src/components/worklist/MobileChips.tsx`
- Create: `frontend/src/components/worklist/ClaimCards.tsx`
- Modify: `frontend/src/components/worklist/WorklistScreen.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/__tests__/worklist-mobile.test.tsx` (new)

**Interfaces:**
- Consumes: `useIsMobile()` (Task 1); `filterGroups`, `effectiveStatus` from `../../lib/worklist`; `fmtDate`, `fmtMoney` from `../../lib/format`; `Checkbox`, `DaysPill`, `StatusPill` from `../ui/*`.
- Produces: `MobileChips({ claims, filters, onToggle, onReset, statusOverrides })` and `ClaimCards({ sorted, selected, onToggleClaim, onOpenClaim, statusOverrides })`. DOM hooks for e2e: `.chips`, `.chip`, `.chip.on`, `.claim-card`, `.claim-card.sel`.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/__tests__/worklist-mobile.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { WorklistScreen, type WorklistProps } from '../components/worklist/WorklistScreen';
import { NO_FILTERS } from '../types';
import { makeData } from './helpers/data';
import { resetViewport, setViewportMobile } from './helpers/matchMedia';

afterEach(() => resetViewport());

function props(overrides: Partial<WorklistProps> = {}): WorklistProps {
  const data = makeData();
  return {
    data,
    filters: NO_FILTERS,
    onToggleFilter: vi.fn(),
    onResetFilters: vi.fn(),
    sort: { col: 'urgency', dir: 'asc' },
    onSort: vi.fn(),
    sorted: data.claims,
    selected: {},
    onToggleClaim: vi.fn(),
    onToggleAll: vi.fn(),
    onClearSelection: vi.fn(),
    onExportSelected: vi.fn(),
    onOpenClaim: vi.fn(),
    statusOverrides: {},
    ...overrides,
  };
}

test('desktop shows rail + table, no chips or cards', () => {
  render(<WorklistScreen {...props()} />);
  expect(document.querySelector('.rail')).not.toBeNull();
  expect(document.querySelector('.table-card')).not.toBeNull();
  expect(document.querySelector('.chips')).toBeNull();
  expect(document.querySelector('.claim-card')).toBeNull();
});

test('mobile shows chips + cards, no rail or table', () => {
  setViewportMobile(true);
  render(<WorklistScreen {...props()} />);
  expect(document.querySelector('.rail')).toBeNull();
  expect(document.querySelector('.table-card')).toBeNull();
  expect(document.querySelector('.chips')).not.toBeNull();
  expect(document.querySelectorAll('.claim-card').length).toBeGreaterThan(0);
});

test('chips toggle bucket and status filters', () => {
  setViewportMobile(true);
  const p = props();
  render(<WorklistScreen {...p} />);
  fireEvent.click(screen.getByRole('button', { name: '<7 days' }));
  expect(p.onToggleFilter).toHaveBeenCalledWith('fBucket', '<7 days');
  fireEvent.click(screen.getByRole('button', { name: 'Draft Ready' }));
  expect(p.onToggleFilter).toHaveBeenCalledWith('fStatus', 'Draft Ready');
});

test('a Reset chip appears only when a filter is active', () => {
  setViewportMobile(true);
  const p = props({ filters: { ...NO_FILTERS, fPayer: ['Payer A'] } });
  render(<WorklistScreen {...p} />);
  fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
  expect(p.onResetFilters).toHaveBeenCalled();
});

test('card opens the claim; its checkbox selects without opening', () => {
  setViewportMobile(true);
  const p = props();
  render(<WorklistScreen {...p} />);
  const card = document.querySelector('.claim-card') as HTMLElement;
  fireEvent.click(card);
  expect(p.onOpenClaim).toHaveBeenCalled();
  const box = card.querySelector('.cbox') as HTMLElement;
  fireEvent.click(box);
  expect(p.onToggleClaim).toHaveBeenCalledTimes(1);
  expect(p.onOpenClaim).toHaveBeenCalledTimes(1); // stopPropagation held
});
```

**About `./helpers/data`:** look at how the existing `worklist-screen.test.tsx` builds its `WorkbenchData` fixture. If it has a reusable factory, extract/reuse it as `makeData()` in `frontend/src/__tests__/helpers/data.ts`; otherwise create that helper wrapping the same fixture data (must include at least one claim with `days < 7` and one with status `Draft Ready` so the chip tests find their labels).

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/__tests__/worklist-mobile.test.tsx`
Expected: FAIL — mobile renders still show rail/table (hook not wired), `.chips` missing.

- [ ] **Step 3: Implement MobileChips**

```tsx
// frontend/src/components/worklist/MobileChips.tsx
import { filterGroups } from '../../lib/worklist';
import type { Claim, FilterKey, FilterState, StatusOverrides } from '../../types';

interface Props {
  claims: Claim[];
  filters: FilterState;
  onToggle: (key: FilterKey, val: string) => void;
  onReset: () => void;
  statusOverrides: StatusOverrides;
}

/** Mobile quick filters: deadline buckets then statuses, same filter state as the rail. */
export function MobileChips({ claims, filters, onToggle, onReset, statusOverrides }: Props) {
  const groups = filterGroups(claims, statusOverrides);
  const chips = (['fBucket', 'fStatus'] as FilterKey[]).flatMap((key) => {
    const g = groups.find((x) => x.key === key);
    return (g?.items ?? []).map((it) => ({ key, label: it.label }));
  });
  const anyFilters = Object.values(filters).some((a) => a.length > 0);
  return (
    <div className="chips">
      {anyFilters && (
        <button type="button" className="chip chip-reset" onClick={onReset}>Reset</button>
      )}
      {chips.map((c) => (
        <button
          type="button"
          key={`${c.key}:${c.label}`}
          className={`chip${filters[c.key].includes(c.label) ? ' on' : ''}`}
          onClick={() => onToggle(c.key, c.label)}
        >
          {c.label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Implement ClaimCards**

```tsx
// frontend/src/components/worklist/ClaimCards.tsx
import { fmtDate, fmtMoney } from '../../lib/format';
import { effectiveStatus } from '../../lib/worklist';
import type { Claim, StatusOverrides } from '../../types';
import { Checkbox } from '../ui/Checkbox';
import { DaysPill, StatusPill } from '../ui/Pills';

interface Props {
  sorted: Claim[];
  selected: Record<string, boolean>;
  onToggleClaim: (id: string) => void;
  onOpenClaim: (id: string) => void;
  statusOverrides: StatusOverrides;
}

export function ClaimCards(p: Props) {
  return (
    <div className="cards-wrap">
      {p.sorted.map((c) => (
        <div
          key={c.id}
          className={`claim-card${p.selected[c.id] ? ' sel' : ''}`}
          onClick={() => p.onOpenClaim(c.id)}
        >
          <div className="cc-top">
            <Checkbox
              checked={!!p.selected[c.id]}
              onToggle={(e) => { e.stopPropagation(); p.onToggleClaim(c.id); }}
              size={17}
            />
            <span className="cc-id">{c.id}</span>
            <span className="spacer" />
            <span className="cc-billed">{fmtMoney(c.billed)}</span>
          </div>
          <div className="cc-line">
            {c.payer} · <span className="code">{c.carc}</span> {c.carcText ?? ''}
          </div>
          <div className="cc-foot">
            <DaysPill claim={c} />
            <StatusPill status={effectiveStatus(c, p.statusOverrides)} />
            <span className="spacer" />
            <span className="cc-due">due {fmtDate(c.deadline)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Wire the swap into WorklistScreen**

In `frontend/src/components/worklist/WorklistScreen.tsx`, add imports:

```tsx
import { useIsMobile } from '../../lib/useIsMobile';
import { ClaimCards } from './ClaimCards';
import { MobileChips } from './MobileChips';
```

and change the returned JSX to:

```tsx
export function WorklistScreen(p: WorklistProps) {
  const isMobile = useIsMobile();
  const selIds = Object.keys(p.selected).filter((id) => p.selected[id]);
  const selSum = p.data.claims
    .filter((c) => selIds.includes(c.id))
    .reduce((t, c) => t + c.billed, 0);
  return (
    <div className="wl">
      {!isMobile && (
        <FilterRail
          claims={p.data.claims}
          filters={p.filters}
          onToggle={p.onToggleFilter}
          onReset={p.onResetFilters}
          statusOverrides={p.statusOverrides}
        />
      )}
      <div className="main">
        <StatsStrip data={p.data} shownCount={p.sorted.length} />
        {isMobile && (
          <MobileChips
            claims={p.data.claims}
            filters={p.filters}
            onToggle={p.onToggleFilter}
            onReset={p.onResetFilters}
            statusOverrides={p.statusOverrides}
          />
        )}
        {selIds.length > 0 && (
          <BulkBar
            count={selIds.length}
            total={selSum}
            onClear={p.onClearSelection}
            onExport={p.onExportSelected}
          />
        )}
        {isMobile ? (
          <ClaimCards
            sorted={p.sorted}
            selected={p.selected}
            onToggleClaim={p.onToggleClaim}
            onOpenClaim={p.onOpenClaim}
            statusOverrides={p.statusOverrides}
          />
        ) : (
          <ClaimsTable
            sorted={p.sorted}
            sort={p.sort}
            onSort={p.onSort}
            selected={p.selected}
            onToggleClaim={p.onToggleClaim}
            onToggleAll={p.onToggleAll}
            onOpenClaim={p.onOpenClaim}
            statusOverrides={p.statusOverrides}
          />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Add the chip/card styles**

Append to the `/* ---- worklist layout ---- */` section of `frontend/src/styles.css`:

```css
.chips { flex: none; display: flex; gap: 6px; overflow-x: auto; padding: 0 12px 10px; -webkit-overflow-scrolling: touch; }
.chip { flex: none; font-size: 12px; font-weight: 600; padding: 5px 11px; border-radius: 999px; border: 1px solid #DBD8D1; background: #FFF; color: var(--ink-2); white-space: nowrap; }
.chip.on { background: #1E1E1B; color: #FFF; border-color: #1E1E1B; }
.chip-reset { color: var(--accent); border-color: var(--accent); }
.cards-wrap { flex: 1; min-height: 0; overflow-y: auto; padding: 0 12px 20px; display: flex; flex-direction: column; gap: 8px; }
.claim-card { background: #FFF; border: 1px solid var(--line-2); border-radius: 12px; box-shadow: 0 1px 2px rgba(24,24,21,0.04); padding: 12px 14px; cursor: pointer; }
.claim-card.sel { background: #EEF2FC; }
.cc-top { display: flex; align-items: center; gap: 10px; }
.cc-id { font-family: var(--mono); font-size: 13px; font-weight: 600; }
.cc-billed { font-family: var(--mono); font-variant-numeric: tabular-nums; font-size: 14px; font-weight: 600; }
.cc-line { font-size: 12.5px; color: var(--ink-3); margin-top: 7px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cc-line .code { font-family: var(--mono); font-size: 11.5px; font-weight: 600; color: var(--ink-2); }
.cc-foot { display: flex; align-items: center; gap: 6px; margin-top: 9px; flex-wrap: wrap; }
.cc-due { font-family: var(--mono); font-variant-numeric: tabular-nums; font-size: 11px; color: var(--mut-2); }
```

- [ ] **Step 7: Run the full suite**

Run: `cd frontend && npm test -- --run`
Expected: PASS (all new tests plus existing `worklist-screen.test.tsx`, which runs under the default desktop stub).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/worklist/MobileChips.tsx frontend/src/components/worklist/ClaimCards.tsx frontend/src/components/worklist/WorklistScreen.tsx frontend/src/styles.css frontend/src/__tests__/worklist-mobile.test.tsx frontend/src/__tests__/helpers/data.ts
git commit -m "mobile: worklist chip filters + claim card list under 760px"
```

---

### Task 4: Detail, summary, stats & bulk responsive CSS

**Files:**
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/components/worklist/StatsStrip.tsx`
- Test: `frontend/src/__tests__/worklist-mobile.test.tsx` (one assertion added)

**Interfaces:**
- Consumes: nothing new.
- Produces: class `stat-showing` on the "Showing" block (hidden ≤759px).

- [ ] **Step 1: Tag the "Showing" block**

In `StatsStrip.tsx` change the wrapper of the "Showing" stat (currently `<div style={{ textAlign: 'right' }}>`) to:

```tsx
      <div className="stat-showing" style={{ textAlign: 'right' }}>
```

- [ ] **Step 2: Add the media queries**

In `frontend/src/styles.css`:

1. Change line 152 from
   `@media (max-width: 900px) { .sm-grid, .sm-cards { grid-template-columns: 1fr; } }`
   to
   `@media (max-width: 900px) { .sm-grid { grid-template-columns: 1fr; } }`

2. Append at the end of the file:

```css
/* ---- mobile (≤759px) ---- */
@media (max-width: 759px) {
  .stats { padding: 12px 12px 10px; }
  .stat-showing { display: none; }
  .bulk { margin: 0 12px 10px; }
  .detail { padding: 12px 12px 24px; }
  .sm-inner { padding: 16px 12px 28px; }
  .sm-cards { grid-template-columns: repeat(2, 1fr); }
}
```

- [ ] **Step 3: Add a regression assertion**

In `worklist-mobile.test.tsx`, extend the mobile swap test:

```tsx
  expect(document.querySelector('.stat-showing')).not.toBeNull();
```

(placed in the desktop test — the element must exist so CSS can hide it on mobile; JSDOM does not apply media queries, so presence is what we can assert.)

- [ ] **Step 4: Run the full suite**

Run: `cd frontend && npm test -- --run`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/styles.css frontend/src/components/worklist/StatsStrip.tsx frontend/src/__tests__/worklist-mobile.test.tsx
git commit -m "mobile: responsive padding + grids for detail, summary, stats, bulk bar"
```

---

### Task 5: SPA screens responsive (chrome bars + row wrapping)

**Files:**
- Modify: `frontend/src/app/ServerApp.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/__tests__/server-app.test.tsx` (only if selectors break)

**Interfaces:**
- Consumes: nothing new.
- Produces: classes `.app-chrome` (org/run header bars) and `.demo-banner` (read-only banner). Behavior of ServerApp is unchanged — existing tests must pass untouched unless they queried inline styles.

- [ ] **Step 1: Add the classes to styles.css**

Append after the `/* ---- top bar ---- */` section:

```css
/* ---- app chrome (served SPA) ---- */
.app-chrome { display: flex; align-items: center; gap: 12px; padding: 8px 20px; border-bottom: 1px solid var(--line); font-size: 12.5px; }
.app-chrome .org { font-weight: 650; }
.demo-banner { display: flex; align-items: center; gap: 12px; padding: 10px 20px; background: var(--amber-bg); color: var(--amber-fg); font-size: 12.5px; font-weight: 600; }
```

and extend the mobile block added in Task 4:

```css
@media (max-width: 759px) {
  .app-chrome, .demo-banner { flex-wrap: wrap; row-gap: 8px; padding-left: 12px; padding-right: 12px; }
  .audit-row { flex-wrap: wrap; row-gap: 4px; }
  .audit-detail { white-space: normal; }
}
```

(Keep it inside the single `@media (max-width: 759px)` block from Task 4 — one block, not two.)

- [ ] **Step 2: Swap inline styles for the classes in ServerApp.tsx**

Three replacements:

Demo banner (lines 110–112):
```tsx
        <div className="demo-banner">
          Read-only demo — synthetic data only.
          <div className="spacer" />
          <button type="button" className="btn" onClick={() => setShowLogin(true)}>Sign in</button>
        </div>
```

`chrome()` header (lines 123–126):
```tsx
      <div className="app-chrome">
        <span className="org">{user.orgName}</span>
```

Run-route header (lines 148–153):
```tsx
        <div className="app-chrome">
          <button type="button" className="backlink" onClick={() => { window.location.hash = ''; }}>
            ← Runs
          </button>
          <span className="org">{user.orgName}</span>
```

(the rest of each block — buttons, pills, spacer — is unchanged; only the wrapper `div style={{…}}` becomes `className`, and the `span style={{ fontWeight: 650 }}` becomes `className="org"`).

- [ ] **Step 3: Run the full suite**

Run: `cd frontend && npm test -- --run`
Expected: PASS — `server-app.test.tsx` queries by text/roles, not styles. Fix selectors only if it fails.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/ServerApp.tsx frontend/src/styles.css
git commit -m "mobile: SPA chrome bars and list rows wrap under 760px"
```

---

### Task 6: Mobile e2e spec + template rebuild + full verification

**Files:**
- Create: `frontend/e2e/mobile.spec.ts`
- Modify: `overturn/templates/workbench.html` (generated)

**Interfaces:**
- Consumes: DOM hooks from Task 3 (`.chips`, `.chip`, `.claim-card`), the read-only demo at `/` (no login), Playwright config (`E2E_BASE_URL` default `http://localhost:8000`).
- Produces: nothing downstream.

- [ ] **Step 1: Write the e2e spec**

```ts
// frontend/e2e/mobile.spec.ts
import { expect, test } from '@playwright/test';

test.use({ viewport: { width: 390, height: 844 } });

test('mobile demo: chips + cards replace rail + table; card opens detail', async ({ page }) => {
  await page.goto('/');

  // worklist: card list + chip row, no table or rail
  await expect(page.locator('.claim-card').first()).toBeVisible();
  await expect(page.locator('.table-card')).toHaveCount(0);
  await expect(page.locator('.rail')).toHaveCount(0);
  await expect(page.locator('.chips')).toBeVisible();

  // a chip toggles active state (same filter state as the rail)
  const chip = page.locator('.chip').first();
  await chip.click();
  await expect(page.locator('.chip.on')).toHaveCount(1);
  await page.locator('.chip-reset').click();
  await expect(page.locator('.chip.on')).toHaveCount(0);

  // card → detail → back
  const firstId = await page.locator('.claim-card .cc-id').first().innerText();
  await page.locator('.claim-card').first().click();
  await expect(page.getByRole('button', { name: '← Worklist' })).toBeVisible();
  await expect(page.locator('.d-id')).toHaveText(firstId);
  await page.getByRole('button', { name: '← Worklist' }).click();

  // summary renders with the 2×2 stat grid present
  await page.getByRole('button', { name: 'Batch Summary' }).click();
  await expect(page.getByText('Records processed')).toBeVisible();
});
```

Check `DetailScreen.tsx` for the claim-id element class — the design uses `.d-id`; if the implementation names it differently, use the actual selector.

- [ ] **Step 2: Rebuild both targets and the committed template**

Run: `cd frontend && npm run build:template && npm run build:app`
Expected: success; `git status` shows `overturn/templates/workbench.html` modified.

- [ ] **Step 3: Rebuild the local stack and run all e2e specs**

```bash
docker compose up -d --build web worker
cd frontend && npx playwright test
```

Expected: existing desktop specs + the new mobile spec PASS (desktop specs run at Playwright's default 1280×720 and are unaffected).

- [ ] **Step 4: Full test sweep**

Run: `cd frontend && npm test -- --run` and `.venv/bin/pytest -q` (from repo root).
Expected: all green (backend untouched — this is a regression guard).

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/mobile.spec.ts overturn/templates/workbench.html
git commit -m "mobile: e2e viewport spec; rebuild committed workbench template"
```
