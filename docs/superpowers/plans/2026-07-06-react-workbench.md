# React Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reimplement the Denial Workbench frontend in React 18 + TypeScript inside `frontend/`, building to the same self-contained `overturn/templates/workbench.html` consumed by `overturn report` — pixel- and behavior-parity with the current vanilla template.

**Architecture:** Vite + `vite-plugin-singlefile` produces one inline-everything HTML file whose `<script id="overturn-data" type="application/json">/*__OVERTURN_DATA__*/{}</script>` island is replaced (first occurrence, Python-side, unchanged) by `report.py`. App state lives in `App.tsx`; pure worklist logic (bucketing, filtering, sorting, letter export) lives in `src/lib/` and is unit-tested without the DOM. The built template is committed so pip installs never need Node.

**Tech Stack:** React 18, TypeScript (strict), Vite 5, vite-plugin-singlefile, Vitest + React Testing Library + user-event + jsdom.

## Global Constraints

- Node >= 20; the Python side (report.py, cli.py, pytest suite) must NOT change.
- The template marker string is exactly `/*__OVERTURN_DATA__*/{}` and must appear exactly once in the built HTML, inside `<script id="overturn-data" type="application/json">`. It must NOT appear anywhere in the app's JS (report.py replaces every occurrence's first match only — a second occurrence in a JS string caused a real bug in v1).
- Raw template (marker intact) must render an empty batch, not crash; `npm run dev` uses the bundled synthetic fixture.
- Feature parity only. Honest-equivalents policy: Export downloads real letter markdown; Approve = session-local "Submitted"; "Revert draft" (no fake Regenerate); audit panel labeled "from audit.jsonl · N events".
- Design tokens (colors, fonts, class names) are ported verbatim from the current `overturn/templates/workbench.html` CSS.
- Do not overwrite `overturn/templates/workbench.html` until Task 7 (parity confirmed) so `overturn report` keeps working mid-implementation.
- All commits: end message with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Scaffold the frontend workspace

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx` (placeholder shell, replaced in Task 4)
- Create: `frontend/src/vitest.setup.ts`
- Create: `frontend/src/__tests__/smoke.test.tsx`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `App` component with props `{ data: WorkbenchData }` (typed `any` until Task 2 lands `types.ts`); npm scripts `dev`, `build`, `test`.

- [ ] **Step 1: Write package.json, configs, entry files**

`frontend/package.json`:

```json
{
  "name": "overturn-workbench",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "engines": { "node": ">=20" },
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "build:template": "npm run build && node scripts/install-template.mjs",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/user-event": "^14.5.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "jsdom": "^24.0.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0",
    "vite-plugin-singlefile": "^2.0.0",
    "vitest": "^2.0.0"
  }
}
```

`frontend/vite.config.ts`:

```ts
/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { viteSingleFile } from 'vite-plugin-singlefile';

export default defineConfig({
  plugins: [react(), viteSingleFile()],
  test: {
    environment: 'jsdom',
    setupFiles: ['src/vitest.setup.ts'],
  },
});
```

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "skipLibCheck": true,
    "types": ["vite/client", "vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "vite.config.ts"]
}
```

`frontend/index.html` — the island and marker live here, BEFORE the app script:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Overturn — Denial Workbench</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400..700&family=Spline+Sans+Mono:wght@400..700&display=swap" rel="stylesheet">
</head>
<body>
<div id="app"></div>
<script id="overturn-data" type="application/json">/*__OVERTURN_DATA__*/{}</script>
<script type="module" src="/src/main.tsx"></script>
</body>
</html>
```

`frontend/src/main.tsx`:

```tsx
import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { readWorkbenchData } from './data';
import './styles.css';

createRoot(document.getElementById('app')!).render(
  <React.StrictMode>
    <App data={readWorkbenchData()} />
  </React.StrictMode>,
);
```

(Note: `./data` and `./styles.css` land in Tasks 2–3. For this task only, create stubs so the build passes: `frontend/src/data.ts` with `export const readWorkbenchData = () => ({} as any);` and an empty `frontend/src/styles.css`. Task 2 replaces the stub with the real module.)

`frontend/src/App.tsx` (placeholder shell — replaced in Task 4):

```tsx
export default function App({ data }: { data: unknown }) {
  return <div className="topbar"><span className="brand-name">Overturn</span></div>;
}
```

`frontend/src/vitest.setup.ts`:

```ts
import '@testing-library/jest-dom/vitest';
```

Append to repo-root `.gitignore`:

```
node_modules/
frontend/dist/
```

- [ ] **Step 2: Write the smoke test**

`frontend/src/__tests__/smoke.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import App from '../App';

test('renders the Overturn brand', () => {
  render(<App data={{}} />);
  expect(screen.getByText('Overturn')).toBeInTheDocument();
});
```

- [ ] **Step 3: Install and run the test, expect pass; run the build**

Run: `cd frontend && npm install && npm test`
Expected: 1 passed.

Run: `npm run build`
Expected: `dist/index.html` produced; verify the marker survived inlining:

Run: `grep -c '/\*__OVERTURN_DATA__\*/{}' dist/index.html`
Expected: `1`

- [ ] **Step 4: Commit**

```bash
git add frontend .gitignore
git commit -m "frontend: scaffold Vite + React + TS workspace with data-island marker"
```

---

### Task 2: Types, data island reader, fixtures, and pure worklist logic

**Files:**
- Create: `frontend/src/types.ts`
- Replace stub: `frontend/src/data.ts`
- Create: `frontend/src/fixtures/sample.ts`
- Create: `frontend/src/lib/format.ts`
- Create: `frontend/src/lib/worklist.ts`
- Test: `frontend/src/lib/__tests__/worklist.test.ts`
- Test: `frontend/src/__tests__/data.test.ts`

**Interfaces:**
- Produces (used by every later task):
  - `types.ts`: `WorkbenchData`, `Claim`, `AuditEvent`, `Screen`, `SortCol`, `FilterKey`, `FilterState`, `EMPTY_DATA`
  - `format.ts`: `fmtMoney(n: number): string` ("$1,234.56"), `fmtDate(iso: string | null): string` ("MM/DD/YY" or "—")
  - `worklist.ts`: `effectiveStatus(c, overrides)`, `bucketOf(c): Bucket`, `daysChip(c): {cls, label}`, `statusStyle(s): {cls, dot}`, `visibleSorted(claims, filters, sort, overrides)`, `filterGroups(claims, overrides)`, `letterFileFor(c, letterOverride?)`, `downloadLetter(c, letterOverride?)`
  - `data.ts`: `parseWorkbenchData(raw: string): WorkbenchData`, `readWorkbenchData(): WorkbenchData`

- [ ] **Step 1: Write the failing unit tests**

`frontend/src/lib/__tests__/worklist.test.ts`:

```ts
import { describe, expect, test } from 'vitest';
import type { Claim } from '../../types';
import { fmtDate, fmtMoney } from '../format';
import {
  bucketOf, daysChip, effectiveStatus, letterFileFor, visibleSorted,
} from '../worklist';

const claim = (over: Partial<Claim>): Claim => ({
  id: 'CLM-1', payer: 'P', carc: 'CO-50', carcText: 'desc', rarcs: [],
  billed: 100, dos: '2026-05-01', denialDate: '2026-06-01',
  deadline: '2026-08-01', days: 10, status: 'Draft Ready',
  denialText: 'text', letter: 'LETTER BODY', refined: 'REFINED',
  rule: 'rule', error: null, ...over,
});

describe('format', () => {
  test('fmtMoney formats cents and thousands', () => {
    expect(fmtMoney(1209224.78)).toBe('$1,209,224.78');
  });
  test('fmtDate shortens ISO and dashes null', () => {
    expect(fmtDate('2026-07-06')).toBe('07/06/26');
    expect(fmtDate(null)).toBe('—');
  });
});

describe('bucketOf', () => {
  test.each([
    [null, 'No deadline'], [-3, '<7 days'], [0, '<7 days'], [6, '<7 days'],
    [7, '7–30 days'], [29, '7–30 days'], [30, '30+ days'],
  ])('days=%s -> %s', (days, bucket) => {
    expect(bucketOf(claim({ days: days as number | null }))).toBe(bucket);
  });
});

describe('daysChip', () => {
  test('overdue is red with overdue label', () => {
    expect(daysChip(claim({ days: -5 }))).toEqual({ cls: 'c-red', label: '5d overdue' });
  });
  test('no deadline is gray dash', () => {
    expect(daysChip(claim({ days: null }))).toEqual({ cls: 'c-gray', label: '—' });
  });
  test('mid-range is amber', () => {
    expect(daysChip(claim({ days: 12 }))).toEqual({ cls: 'c-amber', label: '12d left' });
  });
});

describe('effectiveStatus', () => {
  test('override wins', () => {
    expect(effectiveStatus(claim({}), { 'CLM-1': 'Submitted' })).toBe('Submitted');
    expect(effectiveStatus(claim({}), {})).toBe('Draft Ready');
  });
});

describe('visibleSorted', () => {
  const claims = [
    claim({ id: 'A', days: 10, billed: 100, payer: 'Zeta' }),
    claim({ id: 'B', days: null, billed: 900, payer: 'Alpha' }),
    claim({ id: 'C', days: -2, billed: 50, payer: 'Mid', carc: 'CO-97' }),
    claim({ id: 'D', days: 10, billed: 500, payer: 'Mid2' }),
  ];
  const noFilters = { fCarc: [], fPayer: [], fStatus: [], fBucket: [] };

  test('default sort: urgency (days asc, billed desc), no-deadline last', () => {
    const ids = visibleSorted(claims, noFilters, { col: 'urgency', dir: 'asc' }, {}).map(c => c.id);
    expect(ids).toEqual(['C', 'D', 'A', 'B']);
  });
  test('billed desc sort', () => {
    const ids = visibleSorted(claims, noFilters, { col: 'billed', dir: 'desc' }, {}).map(c => c.id);
    expect(ids).toEqual(['B', 'D', 'A', 'C']);
  });
  test('CARC filter narrows', () => {
    const ids = visibleSorted(claims, { ...noFilters, fCarc: ['CO-97'] }, { col: 'urgency', dir: 'asc' }, {}).map(c => c.id);
    expect(ids).toEqual(['C']);
  });
  test('bucket filter matches bucketOf', () => {
    const ids = visibleSorted(claims, { ...noFilters, fBucket: ['No deadline'] }, { col: 'urgency', dir: 'asc' }, {}).map(c => c.id);
    expect(ids).toEqual(['B']);
  });
});

describe('letterFileFor', () => {
  test('assembles markdown with refined section', () => {
    const md = letterFileFor(claim({}));
    expect(md).toContain('# Appeal — claim CLM-1 (CO-50, P)');
    expect(md).toContain('LETTER BODY');
    expect(md).toContain('## Refined recommendation');
    expect(md).toContain('REFINED');
  });
  test('letter override replaces body', () => {
    expect(letterFileFor(claim({}), 'EDITED')).toContain('EDITED');
  });
});
```

`frontend/src/__tests__/data.test.ts`:

```ts
import { describe, expect, test } from 'vitest';
import { parseWorkbenchData } from '../data';
import { EMPTY_DATA } from '../types';

describe('parseWorkbenchData', () => {
  test('unreplaced marker falls back to empty batch', () => {
    expect(parseWorkbenchData('/*__OVERTURN_DATA__*/{}')).toEqual(EMPTY_DATA);
  });
  test('valid JSON parses', () => {
    const d = parseWorkbenchData(JSON.stringify({ ...EMPTY_DATA, totalBilled: 5 }));
    expect(d.totalBilled).toBe(5);
  });
  test('malformed JSON falls back to empty batch', () => {
    expect(parseWorkbenchData('{nope')).toEqual(EMPTY_DATA);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/__tests__/worklist.test.ts src/__tests__/data.test.ts`
Expected: FAIL — modules `../worklist`, `../format`, `../data` not found / stub lacks exports.

- [ ] **Step 3: Implement**

`frontend/src/types.ts`:

```ts
export interface Claim {
  id: string;
  payer: string;
  carc: string;
  carcText: string | null;
  rarcs: string[];
  billed: number;
  dos: string;
  denialDate: string;
  deadline: string | null;
  days: number | null;
  status: 'Draft Ready' | 'Failed';
  denialText: string;
  letter: string | null;
  refined: string | null;
  rule: string | null;
  error: string | null;
}

export interface AuditEvent {
  time: string;
  type: string;
  detail: string;
}

export interface WorkbenchData {
  generatedOn: string | null;
  asOf: string | null;
  model: string | null;
  totalBilled: number;
  claims: Claim[];
  summary: { processed: number; drafts: number; failed: number };
  audit: AuditEvent[];
}

export const EMPTY_DATA: WorkbenchData = {
  generatedOn: null,
  asOf: null,
  model: null,
  totalBilled: 0,
  claims: [],
  summary: { processed: 0, drafts: 0, failed: 0 },
  audit: [],
};

export type Screen = 'worklist' | 'detail' | 'summary';
export type SortCol = 'urgency' | 'payer' | 'billed' | 'denial' | 'deadline' | 'days';
export interface SortState { col: SortCol; dir: 'asc' | 'desc' }
export type FilterKey = 'fCarc' | 'fPayer' | 'fStatus' | 'fBucket';
export type FilterState = Record<FilterKey, string[]>;
export type StatusOverrides = Record<string, string>;
export const NO_FILTERS: FilterState = { fCarc: [], fPayer: [], fStatus: [], fBucket: [] };
```

`frontend/src/lib/format.ts`:

```ts
export const fmtMoney = (n: number): string =>
  '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const fmtDate = (iso: string | null): string => {
  if (!iso) return '—';
  const [y, m, d] = iso.split('-');
  return `${m}/${d}/${y.slice(2)}`;
};
```

`frontend/src/lib/worklist.ts`:

```ts
import type { Claim, FilterState, SortState, StatusOverrides } from '../types';

export type Bucket = '<7 days' | '7–30 days' | '30+ days' | 'No deadline';
export const BUCKETS: Bucket[] = ['<7 days', '7–30 days', '30+ days', 'No deadline'];

export const effectiveStatus = (c: Claim, overrides: StatusOverrides): string =>
  overrides[c.id] ?? c.status;

export const bucketOf = (c: Claim): Bucket => {
  if (c.days === null) return 'No deadline';
  if (c.days < 7) return '<7 days';
  if (c.days < 30) return '7–30 days';
  return '30+ days';
};

export interface Chip { cls: string; label: string }

export const daysChip = (c: Claim): Chip => {
  if (c.days === null) return { cls: 'c-gray', label: '—' };
  if (c.days < 0) return { cls: 'c-red', label: `${-c.days}d overdue` };
  if (c.days < 7) return { cls: 'c-red', label: `${c.days}d left` };
  if (c.days < 30) return { cls: 'c-amber', label: `${c.days}d left` };
  return { cls: 'c-gray', label: `${c.days}d left` };
};

export const statusStyle = (s: string): { cls: string; dot: string } =>
  ({
    'Draft Ready': { cls: 'c-blue', dot: 'var(--blue-dot)' },
    'Needs Review': { cls: 'c-amber', dot: 'var(--amber-dot)' },
    Failed: { cls: 'c-red', dot: 'var(--red-dot)' },
    Submitted: { cls: 'c-green', dot: 'var(--green-dot)' },
  })[s] ?? { cls: 'c-gray', dot: 'var(--gray-dot)' };

const daysValue = (c: Claim): number => (c.days === null ? Infinity : c.days);

export function visibleSorted(
  claims: Claim[],
  filters: FilterState,
  sort: SortState,
  overrides: StatusOverrides,
): Claim[] {
  const visible = claims.filter(
    (c) =>
      (!filters.fCarc.length || filters.fCarc.includes(c.carc)) &&
      (!filters.fPayer.length || filters.fPayer.includes(c.payer)) &&
      (!filters.fStatus.length || filters.fStatus.includes(effectiveStatus(c, overrides))) &&
      (!filters.fBucket.length || filters.fBucket.includes(bucketOf(c))),
  );
  const dir = sort.dir === 'asc' ? 1 : -1;
  return [...visible].sort((a, b) => {
    switch (sort.col) {
      case 'payer': return dir * a.payer.localeCompare(b.payer);
      case 'billed': return dir * (a.billed - b.billed);
      case 'denial': return dir * a.denialDate.localeCompare(b.denialDate);
      case 'deadline': return dir * String(a.deadline ?? '9999').localeCompare(String(b.deadline ?? '9999'));
      case 'days': return dir * (daysValue(a) - daysValue(b));
      default: return daysValue(a) - daysValue(b) || b.billed - a.billed;
    }
  });
}

export interface FilterGroup {
  key: keyof FilterState;
  title: string;
  items: { label: string; count: number }[];
}

export function filterGroups(claims: Claim[], overrides: StatusOverrides): FilterGroup[] {
  const count = (fn: (c: Claim) => boolean) => claims.filter(fn).length;
  const uniq = (xs: string[]) => [...new Set(xs)];
  return [
    {
      key: 'fCarc', title: 'CARC group',
      items: uniq(claims.map((c) => c.carc)).map((v) => ({ label: v, count: count((c) => c.carc === v) })),
    },
    {
      key: 'fPayer', title: 'Payer',
      items: uniq(claims.map((c) => c.payer)).sort().map((v) => ({ label: v, count: count((c) => c.payer === v) })),
    },
    {
      key: 'fStatus', title: 'Status',
      items: uniq(claims.map((c) => effectiveStatus(c, overrides))).map((v) => ({
        label: v, count: count((c) => effectiveStatus(c, overrides) === v),
      })),
    },
    {
      key: 'fBucket', title: 'Deadline',
      items: BUCKETS.map((v) => ({ label: v, count: count((c) => bucketOf(c) === v) }))
        .filter((it) => it.count > 0),
    },
  ];
}

export function letterFileFor(c: Claim, letterOverride?: string): string {
  const letter = letterOverride ?? c.letter ?? '';
  let body = `# Appeal — claim ${c.id} (${c.carc}, ${c.payer})\n\n${letter}\n`;
  if (c.refined) body += `\n---\n\n## Refined recommendation\n\n${c.refined}\n`;
  return body;
}

export function downloadLetter(c: Claim, letterOverride?: string): void {
  const blob = new Blob([letterFileFor(c, letterOverride)], { type: 'text/markdown' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${c.id}-appeal.md`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
```

`frontend/src/data.ts` (replaces the Task 1 stub):

```ts
import { EMPTY_DATA, type WorkbenchData } from './types';
import { SAMPLE_DATA } from './fixtures/sample';

export function parseWorkbenchData(raw: string): WorkbenchData {
  const text = raw.trim();
  if (text.startsWith('/*')) return EMPTY_DATA; // unreplaced marker
  try {
    return JSON.parse(text) as WorkbenchData;
  } catch {
    return EMPTY_DATA;
  }
}

export function readWorkbenchData(): WorkbenchData {
  const el = document.getElementById('overturn-data');
  const parsed = parseWorkbenchData(el?.textContent ?? '');
  if (parsed === EMPTY_DATA && import.meta.env.DEV) return SAMPLE_DATA;
  return parsed;
}
```

`frontend/src/fixtures/sample.ts` — synthetic dev fixture, clearly labeled:

```ts
import type { WorkbenchData } from '../types';

// Synthetic data only — dev fixture for `npm run dev`; never shipped as real output.
export const SAMPLE_DATA: WorkbenchData = {
  generatedOn: '2026-07-06',
  asOf: '2026-07-06',
  model: null,
  totalBilled: 60920.25,
  summary: { processed: 4, drafts: 3, failed: 1 },
  audit: [
    { time: '06:11:42', type: 'batch_started', detail: 'records=4' },
    { time: '06:11:44', type: 'phi_redacted', detail: 'count=2 · types=[NAME, DOB]' },
    { time: '06:12:41', type: 'batch_completed', detail: 'records=4 · succeeded=3 · failed=1' },
  ],
  claims: [
    {
      id: 'CLM-0001', payer: 'Synthetic Payer A', carc: 'CO-50',
      carcText: 'These are non-covered services because this is not deemed a medical necessity',
      rarcs: ['N115'], billed: 12500, dos: '2026-04-10', denialDate: '2026-05-01',
      deadline: '2026-06-30', days: -6, status: 'Draft Ready',
      denialText: 'Patient: [PATIENT_NAME], DOB: [DOB]. Non-covered: not deemed a medical necessity.',
      letter: 'July 6, 2026\n\n[PATIENT_NAME]\n\nRE: Formal Appeal of Denied Claim (CO-50)\n\nTo Whom It May Concern, ...',
      refined: '[dry run — LLM refinement skipped]',
      rule: 'Medicare Benefit Policy Manual, Ch. 15', error: null,
    },
    {
      id: 'CLM-0002', payer: 'Synthetic Payer B', carc: 'CO-29',
      carcText: 'The time limit for filing has expired', rarcs: ['N30'],
      billed: 430.25, dos: '2026-03-02', denialDate: '2026-04-15',
      deadline: '2026-07-15', days: 9, status: 'Draft Ready',
      denialText: 'The time limit for filing has expired.',
      letter: 'RE: Formal Appeal of Denied Claim (CO-29) ...', refined: null,
      rule: '42 CFR §424.44', error: null,
    },
    {
      id: 'CLM-0003', payer: 'Synthetic Payer A', carc: 'CO-97',
      carcText: 'Benefit included in another adjudicated service', rarcs: [],
      billed: 8300, dos: '2026-05-20', denialDate: '2026-06-10',
      deadline: null, days: null, status: 'Draft Ready',
      denialText: 'Benefit for this service is included in another service.',
      letter: 'RE: Formal Appeal of Denied Claim (CO-97) ...', refined: null,
      rule: 'NCCI Policy Manual, Ch. 1', error: null,
    },
    {
      id: 'CLM-0004', payer: 'Synthetic Payer C', carc: 'CO-16',
      carcText: 'Claim lacks information needed for adjudication', rarcs: ['M76'],
      billed: 39690, dos: '2026-05-25', denialDate: '2026-06-20',
      deadline: '2026-08-19', days: 44, status: 'Failed',
      denialText: 'Claim lacks information or has submission errors.',
      letter: null, refined: null, rule: null, error: 'APIError: synthetic failure',
    },
  ],
};
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: all pass (smoke + worklist + data).

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "frontend: types, data-island reader with fallbacks, pure worklist logic"
```

---

### Task 3: Global stylesheet and UI primitives

**Files:**
- Replace stub: `frontend/src/styles.css`
- Create: `frontend/src/components/ui/Checkbox.tsx`
- Create: `frontend/src/components/ui/Pills.tsx`
- Create: `frontend/src/components/ui/Toast.tsx`
- Create: `frontend/src/components/TopBar.tsx`
- Test: `frontend/src/__tests__/ui.test.tsx`

**Interfaces:**
- Consumes: `daysChip`, `statusStyle` from `lib/worklist`; `Claim`, `Screen` from `types`.
- Produces:
  - `Checkbox({ checked, onToggle, size? })`
  - `Pills.tsx` exports `DaysPill({ claim })` and `StatusPill({ status })`
  - `Toast({ message })` (renders nothing when message is empty)
  - `TopBar({ screen, onNavigate, generatedOn, asOf })` where `onNavigate: (s: Screen) => void`

- [ ] **Step 1: Copy the CSS**

Copy the entire `<style>` block content from the current `overturn/templates/workbench.html` (`:root { --bg: #F7F7F5; ... }` through `.toast { ... }`) into `frontend/src/styles.css` verbatim, then append the two body rules that were inline in the old `<head>` style:

```css
/* (verbatim token + component CSS from overturn/templates/workbench.html) */
```

No changes to selectors or values — class names are the contract with the components.

- [ ] **Step 2: Write the failing UI tests**

`frontend/src/__tests__/ui.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { test, expect, vi } from 'vitest';
import { TopBar } from '../components/TopBar';
import { Checkbox } from '../components/ui/Checkbox';
import { DaysPill, StatusPill } from '../components/ui/Pills';
import { Toast } from '../components/ui/Toast';
import type { Claim } from '../types';

const claim = { days: -4 } as Claim;

test('DaysPill shows overdue in red', () => {
  render(<DaysPill claim={claim} />);
  const pill = screen.getByText('4d overdue');
  expect(pill).toHaveClass('c-red');
});

test('StatusPill renders label with status class', () => {
  render(<StatusPill status="Submitted" />);
  expect(screen.getByText('Submitted')).toHaveClass('c-green');
});

test('Checkbox toggles', async () => {
  const onToggle = vi.fn();
  render(<Checkbox checked={false} onToggle={onToggle} />);
  await userEvent.click(screen.getByRole('button'));
  expect(onToggle).toHaveBeenCalledOnce();
});

test('Toast hides when empty', () => {
  const { rerender } = render(<Toast message="" />);
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  rerender(<Toast message="Saved" />);
  expect(screen.getByRole('status')).toHaveTextContent('Saved');
});

test('TopBar navigates', async () => {
  const onNavigate = vi.fn();
  render(<TopBar screen="worklist" onNavigate={onNavigate} generatedOn="2026-07-06" asOf="2026-07-06" />);
  await userEvent.click(screen.getByRole('button', { name: 'Batch Summary' }));
  expect(onNavigate).toHaveBeenCalledWith('summary');
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/__tests__/ui.test.tsx`
Expected: FAIL — components not found.

- [ ] **Step 4: Implement**

`frontend/src/components/ui/Checkbox.tsx`:

```tsx
interface Props {
  checked: boolean;
  onToggle: (e: React.MouseEvent) => void;
  size?: number;
}

export function Checkbox({ checked, onToggle, size = 14 }: Props) {
  return (
    <button
      type="button"
      className={`cbox${checked ? ' on' : ''}`}
      style={{ width: size, height: size }}
      onClick={onToggle}
    >
      <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF"
        strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="20 6 9 17 4 12" />
      </svg>
    </button>
  );
}
```

`frontend/src/components/ui/Pills.tsx`:

```tsx
import { daysChip, statusStyle } from '../../lib/worklist';
import type { Claim } from '../../types';

export function DaysPill({ claim }: { claim: Claim }) {
  const chip = daysChip(claim);
  return <span className={`pill ${chip.cls}`}>{chip.label}</span>;
}

export function StatusPill({ status }: { status: string }) {
  const st = statusStyle(status);
  return (
    <span className={`st ${st.cls}`}>
      <span className="dot" style={{ background: st.dot }} />
      {status}
    </span>
  );
}
```

`frontend/src/components/ui/Toast.tsx`:

```tsx
export function Toast({ message }: { message: string }) {
  if (!message) return null;
  return <div className="toast" role="status">{message}</div>;
}
```

`frontend/src/components/TopBar.tsx`:

```tsx
import type { Screen } from '../types';

interface Props {
  screen: Screen;
  onNavigate: (s: Screen) => void;
  generatedOn: string | null;
  asOf: string | null;
}

export function TopBar({ screen, onNavigate, generatedOn, asOf }: Props) {
  const onSummary = screen === 'summary';
  return (
    <div className="topbar">
      <div className="brand">
        <div className="brand-mark">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF"
            strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 12a9 9 0 1 0 3-6.7" />
            <polyline points="3 4 3 9 8 9" />
          </svg>
        </div>
        <div className="brand-name">Overturn</div>
      </div>
      <div className="topbar-rule" />
      <div className="tabs">
        <button type="button" className={`tab${!onSummary ? ' on' : ''}`} onClick={() => onNavigate('worklist')}>
          Worklist
        </button>
        <button type="button" className={`tab${onSummary ? ' on' : ''}`} onClick={() => onNavigate('summary')}>
          Batch Summary
        </button>
      </div>
      <div className="spacer" />
      <div className="topbar-meta">
        worklist {generatedOn ?? '—'} · deadlines as of {asOf ?? '—'}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run tests, expect pass; commit**

Run: `cd frontend && npm test`
Expected: all pass.

```bash
git add frontend/src
git commit -m "frontend: design-token stylesheet, UI primitives, top bar"
```

---

### Task 4: Worklist screen + App state

**Files:**
- Create: `frontend/src/components/worklist/FilterRail.tsx`
- Create: `frontend/src/components/worklist/StatsStrip.tsx`
- Create: `frontend/src/components/worklist/BulkBar.tsx`
- Create: `frontend/src/components/worklist/ClaimsTable.tsx`
- Create: `frontend/src/components/worklist/WorklistScreen.tsx`
- Replace: `frontend/src/App.tsx`
- Test: `frontend/src/__tests__/worklist-screen.test.tsx`

**Interfaces:**
- Consumes: Task 2 lib + Task 3 primitives.
- Produces: `App({ data })` owning state:
  `screen/activeId/sort/filters/selected/letters/statusOverrides/toast`;
  `WorklistScreen` props:
  `{ data, filters, onToggleFilter(key, val), onResetFilters, sort, onSort(col), sorted, selected, onToggleClaim(id), onToggleAll, onClearSelection, onExportSelected, onOpenClaim(id), statusOverrides }`.
  Detail/Summary screens render placeholder `<div>`s until Tasks 5–6.

- [ ] **Step 1: Write the failing screen test**

`frontend/src/__tests__/worklist-screen.test.tsx`:

```tsx
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { test, expect } from 'vitest';
import App from '../App';
import { SAMPLE_DATA } from '../fixtures/sample';

test('renders stats, rows in urgency order, filters narrow, selection shows bulk bar', async () => {
  render(<App data={SAMPLE_DATA} />);

  expect(screen.getByText('$60,920.25')).toBeInTheDocument();
  expect(screen.getByText('all 4 claims')).toBeInTheDocument();

  // urgency order: overdue first, no-deadline last
  const ids = screen.getAllByText(/^CLM-\d+$/).map((el) => el.textContent);
  expect(ids).toEqual(['CLM-0001', 'CLM-0002', 'CLM-0004', 'CLM-0003']);

  // filter: CO-50 narrows to 1 of 4
  await userEvent.click(screen.getByRole('button', { name: /CO-50/ }));
  expect(screen.getByText('1 of 4 claims')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Reset' }));
  expect(screen.getByText('all 4 claims')).toBeInTheDocument();

  // selection: row checkbox -> bulk bar
  const row = screen.getByText('CLM-0001').closest('.tbody-row')!;
  await userEvent.click(within(row as HTMLElement).getByRole('button'));
  expect(screen.getByText('1 claim selected')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Clear' }));
  expect(screen.queryByText('1 claim selected')).not.toBeInTheDocument();
});

test('sort by billed toggles direction', async () => {
  render(<App data={SAMPLE_DATA} />);
  await userEvent.click(screen.getByRole('button', { name: /Billed/ }));
  const ids = screen.getAllByText(/^CLM-\d+$/).map((el) => el.textContent);
  expect(ids[0]).toBe('CLM-0004'); // largest billed first (desc default)
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/worklist-screen.test.tsx`
Expected: FAIL — App renders only the placeholder shell.

- [ ] **Step 3: Implement**

`frontend/src/App.tsx`:

```tsx
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { TopBar } from './components/TopBar';
import { Toast } from './components/ui/Toast';
import { WorklistScreen } from './components/worklist/WorklistScreen';
import { downloadLetter, visibleSorted } from './lib/worklist';
import {
  NO_FILTERS,
  type FilterKey, type FilterState, type Screen, type SortCol,
  type SortState, type StatusOverrides, type WorkbenchData,
} from './types';

export default function App({ data }: { data: WorkbenchData }) {
  const [screen, setScreen] = useState<Screen>('worklist');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sort, setSort] = useState<SortState>({ col: 'urgency', dir: 'asc' });
  const [filters, setFilters] = useState<FilterState>(NO_FILTERS);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [letters, setLetters] = useState<Record<string, string>>({});
  const [statusOverrides, setStatusOverrides] = useState<StatusOverrides>({});
  const [toast, setToast] = useState('');
  const toastTimer = useRef<ReturnType<typeof setTimeout>>();

  const showToast = useCallback((msg: string) => {
    clearTimeout(toastTimer.current);
    setToast(msg);
    toastTimer.current = setTimeout(() => setToast(''), 2600);
  }, []);
  useEffect(() => () => clearTimeout(toastTimer.current), []);

  const sorted = useMemo(
    () => visibleSorted(data.claims, filters, sort, statusOverrides),
    [data.claims, filters, sort, statusOverrides],
  );

  const onToggleFilter = (key: FilterKey, val: string) =>
    setFilters((f) => ({
      ...f,
      [key]: f[key].includes(val) ? f[key].filter((x) => x !== val) : [...f[key], val],
    }));

  const onSort = (col: SortCol) =>
    setSort((s) =>
      s.col === col
        ? { ...s, dir: s.dir === 'asc' ? 'desc' : 'asc' }
        : { col, dir: col === 'billed' ? 'desc' : 'asc' },
    );

  const onToggleAll = () => {
    const allChecked = sorted.length > 0 && sorted.every((c) => selected[c.id]);
    setSelected(allChecked ? {} : Object.fromEntries(sorted.map((c) => [c.id, true])));
  };

  const onExportSelected = () => {
    const sel = data.claims.filter((c) => selected[c.id] && c.letter);
    sel.forEach((c) => downloadLetter(c, letters[c.id]));
    showToast(`${sel.length} letter${sel.length === 1 ? '' : 's'} exported`);
  };

  let body: JSX.Element;
  if (screen === 'detail') {
    body = <div>detail placeholder</div>; // Task 5
  } else if (screen === 'summary') {
    body = <div>summary placeholder</div>; // Task 6
  } else {
    body = (
      <WorklistScreen
        data={data}
        filters={filters}
        onToggleFilter={onToggleFilter}
        onResetFilters={() => setFilters(NO_FILTERS)}
        sort={sort}
        onSort={onSort}
        sorted={sorted}
        selected={selected}
        onToggleClaim={(id) => setSelected((s) => ({ ...s, [id]: !s[id] }))}
        onToggleAll={onToggleAll}
        onClearSelection={() => setSelected({})}
        onExportSelected={onExportSelected}
        onOpenClaim={(id) => { setActiveId(id); setScreen('detail'); }}
        statusOverrides={statusOverrides}
      />
    );
  }

  return (
    <div id="workbench" style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <TopBar screen={screen} onNavigate={setScreen} generatedOn={data.generatedOn} asOf={data.asOf} />
      {body}
      <Toast message={toast} />
    </div>
  );
}
```

(Note: Tasks 5 and 6 will replace the two placeholders and will need
`activeId`, `letters`, `setLetters`, `statusOverrides`, `setStatusOverrides`,
and `showToast` — they are already in scope here by design.)

`frontend/src/components/worklist/WorklistScreen.tsx`:

```tsx
import type {
  Claim, FilterKey, FilterState, SortCol, SortState, StatusOverrides, WorkbenchData,
} from '../../types';
import { BulkBar } from './BulkBar';
import { ClaimsTable } from './ClaimsTable';
import { FilterRail } from './FilterRail';
import { StatsStrip } from './StatsStrip';

export interface WorklistProps {
  data: WorkbenchData;
  filters: FilterState;
  onToggleFilter: (key: FilterKey, val: string) => void;
  onResetFilters: () => void;
  sort: SortState;
  onSort: (col: SortCol) => void;
  sorted: Claim[];
  selected: Record<string, boolean>;
  onToggleClaim: (id: string) => void;
  onToggleAll: () => void;
  onClearSelection: () => void;
  onExportSelected: () => void;
  onOpenClaim: (id: string) => void;
  statusOverrides: StatusOverrides;
}

export function WorklistScreen(p: WorklistProps) {
  const selIds = Object.keys(p.selected).filter((id) => p.selected[id]);
  const selSum = p.data.claims
    .filter((c) => selIds.includes(c.id))
    .reduce((t, c) => t + c.billed, 0);
  return (
    <div className="wl">
      <FilterRail
        claims={p.data.claims}
        filters={p.filters}
        onToggle={p.onToggleFilter}
        onReset={p.onResetFilters}
        statusOverrides={p.statusOverrides}
      />
      <div className="main">
        <StatsStrip data={p.data} shownCount={p.sorted.length} />
        {selIds.length > 0 && (
          <BulkBar
            count={selIds.length}
            total={selSum}
            onClear={p.onClearSelection}
            onExport={p.onExportSelected}
          />
        )}
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
      </div>
    </div>
  );
}
```

`frontend/src/components/worklist/FilterRail.tsx`:

```tsx
import { filterGroups } from '../../lib/worklist';
import type { Claim, FilterKey, FilterState, StatusOverrides } from '../../types';

interface Props {
  claims: Claim[];
  filters: FilterState;
  onToggle: (key: FilterKey, val: string) => void;
  onReset: () => void;
  statusOverrides: StatusOverrides;
}

export function FilterRail({ claims, filters, onToggle, onReset, statusOverrides }: Props) {
  const anyFilters = Object.values(filters).some((a) => a.length > 0);
  return (
    <div className="rail">
      <div className="rail-head">
        <div className="rail-title">Filters</div>
        {anyFilters && (
          <button type="button" className="rail-reset" onClick={onReset}>Reset</button>
        )}
      </div>
      {filterGroups(claims, statusOverrides).map((g) => (
        <div className="fgroup" key={g.key}>
          <div className="fgroup-title">{g.title}</div>
          {g.items.map((it) => (
            <button
              type="button"
              className="fitem"
              key={it.label}
              onClick={() => onToggle(g.key, it.label)}
            >
              <span className={`cbox${filters[g.key].includes(it.label) ? ' on' : ''}`}>
                <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF"
                  strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </span>
              <span className="fitem-label">{it.label}</span>
              <span className="fitem-count">{it.count}</span>
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}
```

(Note: the filter row uses an inline `span.cbox`, not the `Checkbox` button
component, because the whole row is already a button — nested buttons are
invalid HTML and break RTL name queries.)

`frontend/src/components/worklist/StatsStrip.tsx`:

```tsx
import { fmtMoney } from '../../lib/format';
import type { WorkbenchData } from '../../types';

export function StatsStrip({ data, shownCount }: { data: WorkbenchData; shownCount: number }) {
  const all = data.claims;
  const lt7 = all.filter((c) => c.days !== null && c.days < 7).length;
  const mid = all.filter((c) => c.days !== null && c.days >= 7 && c.days < 30).length;
  const g30 = all.filter((c) => c.days !== null && c.days >= 30).length;
  return (
    <div className="stats">
      <div>
        <div className="stat-label">Total at stake</div>
        <div className="stat-value">{fmtMoney(data.totalBilled)}</div>
      </div>
      <div>
        <div className="stat-label">Records</div>
        <div className="stat-value">{all.length} <small>denied claims</small></div>
      </div>
      <div>
        <div className="stat-label">Appeal deadlines</div>
        <div className="stat-pills">
          <span className="pill c-red">{lt7} · &lt;7d</span>
          <span className="pill c-amber">{mid} · 7–30d</span>
          <span className="pill c-gray">{g30} · 30d+</span>
        </div>
      </div>
      <div className="spacer" />
      <div style={{ textAlign: 'right' }}>
        <div className="stat-label">Showing</div>
        <div className="shown">
          {shownCount === all.length ? `all ${all.length} claims` : `${shownCount} of ${all.length} claims`}
        </div>
      </div>
    </div>
  );
}
```

`frontend/src/components/worklist/BulkBar.tsx`:

```tsx
import { fmtMoney } from '../../lib/format';

interface Props {
  count: number;
  total: number;
  onClear: () => void;
  onExport: () => void;
}

export function BulkBar({ count, total, onClear, onExport }: Props) {
  return (
    <div className="bulk">
      <div className="bulk-label">{count} claim{count === 1 ? '' : 's'} selected</div>
      <div className="bulk-value">{fmtMoney(total)} at stake</div>
      <div className="spacer" />
      <button type="button" className="bulk-clear" onClick={onClear}>Clear</button>
      <button type="button" className="btn-primary" onClick={onExport}>Export letters</button>
    </div>
  );
}
```

`frontend/src/components/worklist/ClaimsTable.tsx`:

```tsx
import { fmtDate, fmtMoney } from '../../lib/format';
import { effectiveStatus } from '../../lib/worklist';
import type { Claim, SortCol, SortState, StatusOverrides } from '../../types';
import { Checkbox } from '../ui/Checkbox';
import { DaysPill, StatusPill } from '../ui/Pills';

interface Props {
  sorted: Claim[];
  sort: SortState;
  onSort: (col: SortCol) => void;
  selected: Record<string, boolean>;
  onToggleClaim: (id: string) => void;
  onToggleAll: () => void;
  onOpenClaim: (id: string) => void;
  statusOverrides: StatusOverrides;
}

export function ClaimsTable(p: Props) {
  const arrow = (col: SortCol) => (p.sort.col === col ? (p.sort.dir === 'asc' ? ' ↑' : ' ↓') : '');
  const allChecked = p.sorted.length > 0 && p.sorted.every((c) => p.selected[c.id]);
  const header = (col: SortCol, label: string, num = false) => (
    <button type="button" className={`th${num ? ' num' : ''}`} onClick={() => p.onSort(col)}>
      {label}{arrow(col)}
    </button>
  );
  return (
    <div className="table-wrap">
      <div className="card table-card">
        <div className="trow thead">
          <div className="td-check" style={{ paddingTop: 9, paddingBottom: 9 }}>
            <Checkbox checked={allChecked} onToggle={p.onToggleAll} size={15} />
          </div>
          <div className="th">Claim ID</div>
          {header('payer', 'Payer')}
          <div className="th">CARC · Reason</div>
          {header('billed', 'Billed', true)}
          {header('denial', 'Denied')}
          {header('deadline', 'Deadline')}
          {header('days', 'Days Left')}
          <div className="th">Status</div>
        </div>
        {p.sorted.map((c) => (
          <div
            key={c.id}
            className={`trow tbody-row${p.selected[c.id] ? ' sel' : ''}`}
            onClick={() => p.onOpenClaim(c.id)}
          >
            <div className="td-check">
              <Checkbox
                checked={!!p.selected[c.id]}
                onToggle={(e) => { e.stopPropagation(); p.onToggleClaim(c.id); }}
                size={15}
              />
            </div>
            <div className="td td-id">{c.id}</div>
            <div className="td">{c.payer}</div>
            <div className="td td-carc">
              <span className="code">{c.carc}</span>
              <span className="why"> · {c.carcText ?? ''}</span>
            </div>
            <div className="td td-num">{fmtMoney(c.billed)}</div>
            <div className="td td-date">{fmtDate(c.denialDate)}</div>
            <div className="td td-date" style={{ color: 'var(--ink-2)' }}>{fmtDate(c.deadline)}</div>
            <div className="td"><DaysPill claim={c} /></div>
            <div className="td"><StatusPill status={effectiveStatus(c, p.statusOverrides)} /></div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests, expect pass**

Run: `cd frontend && npm test`
Expected: all pass, including the two new screen tests. Fix the smoke test if the placeholder App changed shape (it should still find "Overturn" via TopBar).

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "frontend: worklist screen with filters, sorting, selection, bulk export"
```

---

### Task 5: Claim detail screen

**Files:**
- Create: `frontend/src/components/detail/DenialCard.tsx`
- Create: `frontend/src/components/detail/AppealCard.tsx`
- Create: `frontend/src/components/detail/DetailScreen.tsx`
- Modify: `frontend/src/App.tsx` (replace detail placeholder)
- Test: `frontend/src/__tests__/detail-screen.test.tsx`

**Interfaces:**
- Consumes: Task 2 lib, Task 3 primitives, App state from Task 4.
- Produces: `DetailScreen` props:
  `{ claim, model, generatedOn, status, letter, onBack, onLetterChange(text), onApprove, onRevert, onExport }`.

- [ ] **Step 1: Write the failing test**

`frontend/src/__tests__/detail-screen.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { test, expect, vi } from 'vitest';
import App from '../App';
import { SAMPLE_DATA } from '../fixtures/sample';

async function openClaim(id: string) {
  render(<App data={SAMPLE_DATA} />);
  await userEvent.click(screen.getByText(id));
}

test('detail shows denial fields, PHI chips, letter, and approve flow', async () => {
  await openClaim('CLM-0001');

  expect(screen.getByText('parsed from 835 remittance')).toBeInTheDocument();
  expect(screen.getByText('N115')).toBeInTheDocument();
  expect(screen.getByText('PHI redacted before model call')).toBeInTheDocument();
  // [PATIENT_NAME] in denial text renders as a chip without brackets
  expect(screen.getAllByText('PATIENT_NAME').length).toBeGreaterThan(0);

  const textarea = screen.getByRole('textbox');
  expect(textarea).toHaveValue(expect.stringContaining('Formal Appeal') as unknown as string);

  await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
  expect(screen.getByText('Submitted')).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('approved');
});

test('editing then reverting restores the generated letter', async () => {
  await openClaim('CLM-0001');
  const textarea = screen.getByRole('textbox');
  await userEvent.clear(textarea);
  await userEvent.type(textarea, 'edited');
  expect(textarea).toHaveValue('edited');
  await userEvent.click(screen.getByRole('button', { name: 'Revert draft' }));
  expect(screen.getByRole('textbox')).not.toHaveValue('edited');
});

test('failed claim shows banner and no letter actions', async () => {
  await openClaim('CLM-0004');
  expect(screen.getByText('No appeal drafted')).toBeInTheDocument();
  expect(screen.getByText(/synthetic failure/)).toBeInTheDocument();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
});
```

Note on the `toHaveValue`/`stringContaining` line: if it proves awkward, assert
via `expect((textarea as HTMLTextAreaElement).value).toContain('Formal Appeal')`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/detail-screen.test.tsx`
Expected: FAIL — detail placeholder has none of this.

- [ ] **Step 3: Implement**

`frontend/src/components/detail/DenialCard.tsx`:

```tsx
import { Fragment } from 'react';
import { fmtDate, fmtMoney } from '../../lib/format';
import type { Claim } from '../../types';

function PhiText({ text }: { text: string }) {
  const parts = text.split(/(\[[A-Z_]+\])/g);
  return (
    <>
      {parts.map((p, i) =>
        /^\[[A-Z_]+\]$/.test(p)
          ? <span className="phi-tag" key={i}>{p.slice(1, -1)}</span>
          : <Fragment key={i}>{p}</Fragment>,
      )}
    </>
  );
}

export function DenialCard({ claim }: { claim: Claim }) {
  const hot = claim.days !== null && claim.days < 7;
  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">Denial</div>
        <div className="card-sub">parsed from 835 remittance</div>
      </div>
      <div className="kv">
        <div className="k">Payer</div><div className="v">{claim.payer}</div>
        <div className="k">Date of service</div><div className="v mono">{fmtDate(claim.dos)}</div>
        <div className="k">Billed</div><div className="v mono">{fmtMoney(claim.billed)}</div>
        <div className="k">Denial date</div><div className="v mono">{fmtDate(claim.denialDate)}</div>
        <div className="k">Appeal deadline</div>
        <div className="v mono" style={{ fontWeight: 600, color: hot ? 'var(--red-fg)' : 'var(--ink)' }}>
          {fmtDate(claim.deadline)}
        </div>
      </div>
      <div className="codes">
        <div className="k" style={{ color: 'var(--mut)', fontSize: '12.5px' }}>CARC</div>
        <div>
          <span className="code-chip">{claim.carc}</span>
          <div className="code-text">
            {claim.carcText ?? 'Code not in the curated CARC database — fallback appeal grounds were used.'}
          </div>
        </div>
        <div className="k" style={{ color: 'var(--mut)', fontSize: '12.5px' }}>RARC</div>
        <div>
          {claim.rarcs.length
            ? claim.rarcs.map((r) => <span className="code-chip" key={r}>{r}</span>)
            : <span style={{ fontSize: '12.5px', color: 'var(--mut-2)' }}>none on remittance</span>}
        </div>
      </div>
      <div className="denial-block">
        <div className="denial-label">
          <b>Original denial text</b>
          <span className="phi-badge">
            <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#1F6B3D"
              strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            PHI redacted before model call
          </span>
        </div>
        <div className="denial-text"><PhiText text={claim.denialText} /></div>
      </div>
    </div>
  );
}
```

`frontend/src/components/detail/AppealCard.tsx`:

```tsx
import { useRef } from 'react';
import type { Claim } from '../../types';

interface Props {
  claim: Claim;
  model: string | null;
  generatedOn: string | null;
  failed: boolean;
  letter: string;
  onLetterChange: (text: string) => void;
  onApprove: () => void;
  onRevert: () => void;
  onExport: () => void;
}

export function AppealCard(p: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  return (
    <div className="card appeal-card">
      <div className="card-head">
        <div className="card-title">Drafted appeal</div>
        <div className="card-sub">editable draft — not sent</div>
      </div>
      <div className="meta-strip">
        <div>Model <b>{p.model ?? 'refinement skipped (dry run)'}</b></div>
        {p.claim.rule && <div>Cites <b>{p.claim.rule}</b></div>}
        <div>Generated <b>{p.generatedOn ?? '—'}</b></div>
      </div>
      {p.failed ? (
        <div className="fail-banner">
          <div className="t">No appeal drafted</div>
          <div className="b">
            {p.claim.error ?? 'This record failed during batch processing.'}{' '}
            Write the appeal manually or re-run the batch for this claim.
          </div>
        </div>
      ) : (
        <>
          <textarea
            ref={textareaRef}
            className="letter"
            spellCheck={false}
            value={p.letter}
            onChange={(e) => p.onLetterChange(e.target.value)}
          />
          {p.claim.refined && (
            <div className="refined">
              <div className="t">Refined recommendation</div>
              <div className="b">{p.claim.refined}</div>
            </div>
          )}
        </>
      )}
      <div className="actions">
        {!p.failed && (
          <>
            <button type="button" className="btn-primary" onClick={p.onApprove}>Approve</button>
            <button type="button" className="btn" onClick={() => textareaRef.current?.focus()}>Edit</button>
            <button type="button" className="btn" onClick={p.onRevert}>Revert draft</button>
          </>
        )}
        <div className="spacer" />
        {!p.failed && (
          <button type="button" className="btn" onClick={p.onExport}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            Export letter
          </button>
        )}
      </div>
    </div>
  );
}
```

`frontend/src/components/detail/DetailScreen.tsx`:

```tsx
import { fmtMoney } from '../../lib/format';
import type { Claim } from '../../types';
import { DaysPill, StatusPill } from '../ui/Pills';
import { AppealCard } from './AppealCard';
import { DenialCard } from './DenialCard';

interface Props {
  claim: Claim;
  status: string;
  model: string | null;
  generatedOn: string | null;
  letter: string;
  onBack: () => void;
  onLetterChange: (text: string) => void;
  onApprove: () => void;
  onRevert: () => void;
  onExport: () => void;
}

export function DetailScreen(p: Props) {
  return (
    <div className="detail">
      <button type="button" className="backlink" onClick={p.onBack}>← Worklist</button>
      <div className="d-head">
        <div className="d-id">{p.claim.id}</div>
        <StatusPill status={p.status} />
        <div className="d-payer">{p.claim.payer}</div>
        <DaysPill claim={p.claim} />
        <div className="spacer" />
        <div className="d-billed">{fmtMoney(p.claim.billed)}</div>
      </div>
      <div className="d-grid">
        <DenialCard claim={p.claim} />
        <AppealCard
          claim={p.claim}
          model={p.model}
          generatedOn={p.generatedOn}
          failed={p.status === 'Failed'}
          letter={p.letter}
          onLetterChange={p.onLetterChange}
          onApprove={p.onApprove}
          onRevert={p.onRevert}
          onExport={p.onExport}
        />
      </div>
    </div>
  );
}
```

In `frontend/src/App.tsx`, replace the detail placeholder with:

```tsx
  if (screen === 'detail') {
    const claim = data.claims.find((c) => c.id === activeId) ?? data.claims[0];
    if (!claim) {
      body = <div className="detail">No claims in this batch.</div>;
    } else {
      body = (
        <DetailScreen
          claim={claim}
          status={effectiveStatus(claim, statusOverrides)}
          model={data.model}
          generatedOn={data.generatedOn}
          letter={letters[claim.id] ?? claim.letter ?? ''}
          onBack={() => setScreen('worklist')}
          onLetterChange={(text) => setLetters((l) => ({ ...l, [claim.id]: text }))}
          onApprove={() => {
            setStatusOverrides((o) => ({ ...o, [claim.id]: 'Submitted' }));
            showToast(`${claim.id} approved — marked Submitted (this session only)`);
          }}
          onRevert={() => {
            setLetters((l) => {
              const next = { ...l };
              delete next[claim.id];
              return next;
            });
            showToast('Draft reverted to the generated letter');
          }}
          onExport={() => {
            downloadLetter(claim, letters[claim.id]);
            showToast(`Exported ${claim.id}-appeal.md`);
          }}
        />
      );
    }
  }
```

and add the imports: `DetailScreen` from `./components/detail/DetailScreen`,
`effectiveStatus` from `./lib/worklist`.

- [ ] **Step 4: Run tests, expect pass; commit**

Run: `cd frontend && npm test`
Expected: all pass.

```bash
git add frontend/src
git commit -m "frontend: claim detail screen with denial card, editable appeal, approve/revert/export"
```

---

### Task 6: Batch summary screen

**Files:**
- Create: `frontend/src/components/summary/SummaryScreen.tsx`
- Modify: `frontend/src/App.tsx` (replace summary placeholder)
- Test: `frontend/src/__tests__/summary-screen.test.tsx`

**Interfaces:**
- Consumes: Task 2 lib, Task 3 primitives.
- Produces: `SummaryScreen({ data, statusOverrides, onBack })`.

- [ ] **Step 1: Write the failing test**

`frontend/src/__tests__/summary-screen.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { test, expect } from 'vitest';
import App from '../App';
import { SAMPLE_DATA } from '../fixtures/sample';

test('summary shows stat cards, CARC bars, deadline buckets, audit trail', async () => {
  render(<App data={SAMPLE_DATA} />);
  await userEvent.click(screen.getByRole('button', { name: 'Batch Summary' }));

  expect(screen.getByText('Records processed')).toBeInTheDocument();
  expect(screen.getByText('Dollars at stake by CARC group')).toBeInTheDocument();
  expect(screen.getByText(/from audit\.jsonl · 3 events/)).toBeInTheDocument();
  expect(screen.getByText('batch_started')).toBeInTheDocument();
  // Overdue bucket exists (CLM-0001 days=-6)
  expect(screen.getByText('Overdue')).toBeInTheDocument();
});

test('approving a claim moves it into Approved this session', async () => {
  render(<App data={SAMPLE_DATA} />);
  await userEvent.click(screen.getByText('CLM-0001'));
  await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
  await userEvent.click(screen.getByRole('button', { name: 'Batch Summary' }));
  const card = screen.getByText('Approved this session').parentElement!;
  expect(card).toHaveTextContent('1');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/summary-screen.test.tsx`
Expected: FAIL — summary placeholder.

- [ ] **Step 3: Implement**

`frontend/src/components/summary/SummaryScreen.tsx`:

```tsx
import { fmtMoney } from '../../lib/format';
import { effectiveStatus } from '../../lib/worklist';
import type { Claim, StatusOverrides, WorkbenchData } from '../../types';

interface Props {
  data: WorkbenchData;
  statusOverrides: StatusOverrides;
  onBack: () => void;
}

const EVENT_CLS: Record<string, string> = {
  phi_redacted: 'c-green',
  appeal_generated: 'c-blue',
  recommendation_generated: 'c-blue',
  record_failed: 'c-red',
  generation_failed: 'c-red',
  batch_started: 'c-gray',
  batch_completed: 'c-gray',
};

interface BucketDef {
  label: string;
  cls: string;
  bar: string;
  test: (c: Claim) => boolean;
  always: boolean;
}

const BUCKET_DEFS: BucketDef[] = [
  { label: 'Overdue', cls: 'c-red', bar: 'var(--red-dot)', test: (c) => c.days !== null && c.days < 0, always: false },
  { label: '<7 days', cls: 'c-red', bar: 'var(--red-dot)', test: (c) => c.days !== null && c.days >= 0 && c.days < 7, always: true },
  { label: '7–30 days', cls: 'c-amber', bar: 'var(--amber-dot)', test: (c) => c.days !== null && c.days >= 7 && c.days < 30, always: true },
  { label: '30+ days', cls: 'c-gray', bar: 'var(--gray-dot)', test: (c) => c.days !== null && c.days >= 30, always: true },
  { label: 'No deadline', cls: 'c-gray', bar: 'var(--gray-dot)', test: (c) => c.days === null, always: false },
];

export function SummaryScreen({ data, statusOverrides, onBack }: Props) {
  const all = data.claims;
  const submitted = all.filter((c) => effectiveStatus(c, statusOverrides) === 'Submitted').length;

  const carcTotals = new Map<string, { amt: number; n: number }>();
  for (const c of all) {
    const t = carcTotals.get(c.carc) ?? { amt: 0, n: 0 };
    t.amt += c.billed; t.n += 1;
    carcTotals.set(c.carc, t);
  }
  const maxAmt = Math.max(1, ...[...carcTotals.values()].map((t) => t.amt));

  const buckets = BUCKET_DEFS
    .map((b) => ({ ...b, count: all.filter(b.test).length }))
    .filter((b) => b.always || b.count > 0);
  const maxB = Math.max(1, ...buckets.map((b) => b.count));

  const hot = all.filter((c) => c.days !== null && c.days < 7);
  const hotSum = hot.reduce((t, c) => t + c.billed, 0);

  return (
    <div className="sm"><div className="sm-inner">
      <div className="sm-head">
        <div className="sm-title">Batch summary</div>
        <div className="sm-meta">worklist {data.generatedOn ?? '—'} · deadlines as of {data.asOf ?? '—'}</div>
        <div className="spacer" />
        <button type="button" className="sm-back" onClick={onBack}>← Back to worklist</button>
      </div>
      <div className="sm-cards">
        <div className="sm-card">
          <div className="stat-label">Records processed</div>
          <div className="sm-num">{data.summary.processed}</div>
        </div>
        <div className="sm-card">
          <div className="stat-label">Drafts ready</div>
          <div className="sm-num" style={{ color: 'var(--blue-fg)' }}>{data.summary.drafts - submitted}</div>
        </div>
        <div className="sm-card">
          <div className="stat-label">Approved this session</div>
          <div className="sm-num" style={{ color: 'var(--green-fg)' }}>{submitted}</div>
        </div>
        <div className="sm-card">
          <div className="stat-label">Failed</div>
          <div className="sm-num" style={{ color: 'var(--red-fg)' }}>{data.summary.failed}</div>
        </div>
      </div>
      <div className="sm-grid">
        <div className="panel">
          <div className="panel-head">
            <div className="panel-title">Dollars at stake by CARC group</div>
            <div className="panel-sub">{fmtMoney(data.totalBilled)} total</div>
          </div>
          <div className="bars">
            {[...carcTotals.entries()].sort((a, b) => b[1].amt - a[1].amt).map(([code, t]) => (
              <div className="bar-row" key={code}>
                <div className="code">{code}</div>
                <div className="bar-track">
                  <div className="bar-fill" style={{ width: `${Math.max(2, Math.round((t.amt / maxAmt) * 100))}%` }} />
                </div>
                <div className="bar-amt">{fmtMoney(t.amt)}</div>
                <div className="bar-n">×{t.n}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="panel">
            <div className="panel-title">Deadline distribution</div>
            <div className="bars">
              {buckets.map((b) => (
                <div className="dl-row" key={b.label}>
                  <span className={`pill ${b.cls}`}>{b.label}</span>
                  <div className="bar-track">
                    <div className="bar-fill" style={{ background: b.bar, width: `${Math.round((b.count / maxB) * 100)}%` }} />
                  </div>
                  <div className="dl-count">{b.count}</div>
                </div>
              ))}
            </div>
            {hot.length > 0 && (
              <div className="sm-note">
                {hot.length} claim{hot.length === 1 ? '' : 's'} worth <b>{fmtMoney(hotSum)}</b>{' '}
                expire{hot.length === 1 ? 's' : ''} within 7 days.
              </div>
            )}
          </div>
          <div className="panel">
            <div className="panel-head">
              <div className="panel-title">Audit trail</div>
              <div className="card-sub">from audit.jsonl · {data.audit.length} events</div>
            </div>
            <div className="audit-list">
              {data.audit.length === 0 && (
                <div className="sm-note">No audit.jsonl found next to worklist.json.</div>
              )}
              {data.audit.map((e, i) => (
                <div className="audit-row" key={i}>
                  <div className="audit-time">{e.time}</div>
                  <div className={`audit-type ${EVENT_CLS[e.type] ?? 'c-gray'}`}>{e.type}</div>
                  <div className="audit-detail">{e.detail}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div></div>
  );
}
```

In `frontend/src/App.tsx`, replace the summary placeholder:

```tsx
  } else if (screen === 'summary') {
    body = (
      <SummaryScreen
        data={data}
        statusOverrides={statusOverrides}
        onBack={() => setScreen('worklist')}
      />
    );
  }
```

with import `SummaryScreen` from `./components/summary/SummaryScreen`.

- [ ] **Step 4: Run all frontend tests, expect pass; commit**

Run: `cd frontend && npm test`
Expected: all pass.

```bash
git add frontend/src
git commit -m "frontend: batch summary screen with CARC bars, deadline buckets, audit trail"
```

---

### Task 7: Build into the template, verify end-to-end, document

**Files:**
- Create: `frontend/scripts/install-template.mjs`
- Overwrite (generated): `overturn/templates/workbench.html`
- Modify: `README.md`

**Interfaces:**
- Consumes: `npm run build:template`; the Python contract (`report.py`'s marker replacement) — unchanged.
- Produces: committed React-built `overturn/templates/workbench.html`.

- [ ] **Step 1: Write the install script**

`frontend/scripts/install-template.mjs`:

```js
import { copyFileSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'dist', 'index.html');
const dest = join(here, '..', '..', 'overturn', 'templates', 'workbench.html');

const html = readFileSync(src, 'utf8');
const marker = '/*__OVERTURN_DATA__*/{}';
const count = html.split(marker).length - 1;
if (count !== 1) {
  console.error(`FATAL: data-island marker appears ${count} times (must be exactly 1)`);
  process.exit(1);
}
if (!html.includes('id="overturn-data"')) {
  console.error('FATAL: overturn-data script island missing');
  process.exit(1);
}
copyFileSync(src, dest);
console.log(`installed ${dest}`);
```

- [ ] **Step 2: Build and install the template**

Run: `cd frontend && npm run build:template`
Expected: `installed .../overturn/templates/workbench.html`.

- [ ] **Step 3: Run the FULL Python test suite against the new template**

Run: `cd .. && .venv/bin/python -m pytest tests/ -q`
Expected: all pass (report tests exercise marker injection against the committed template).

- [ ] **Step 4: Regenerate the 50-record report and verify in a browser**

```bash
SCRATCH=<session scratchpad>
.venv/bin/overturn report $SCRATCH/out50 --as-of 2026-07-06
cd $SCRATCH/out50 && python3 -m http.server 8471 &
```

With Playwright (or manually): load `http://localhost:8471/workbench.html`, then verify:
1. Worklist renders 50 rows, urgency order, zero console errors.
2. Filter click narrows counts; Reset restores.
3. Row click → detail; letter editable; Approve → Submitted pill + toast.
4. Batch Summary → stat cards, CARC bars, deadline buckets incl. Overdue, audit trail event count > 0.
Kill the server afterward.

- [ ] **Step 5: Update README**

In `README.md`, extend the Development section:

```markdown
### Frontend (Denial Workbench)

The HTML workbench template is built from a React + TypeScript app in
`frontend/`. The built single-file template is committed at
`overturn/templates/workbench.html`, so Python users never need Node.

To change the workbench UI:

```bash
cd frontend
npm install
npm run dev             # hot-reload dev server with a synthetic fixture
npm test                # Vitest + React Testing Library
npm run build:template  # build and install overturn/templates/workbench.html
```

Commit the rebuilt template together with the frontend source change.
```

- [ ] **Step 6: Commit**

```bash
git add frontend overturn/templates/workbench.html README.md
git commit -m "frontend: build React workbench into the committed template; document rebuild"
```

---

## Self-Review Notes

- Spec coverage: delivery model (T1, T7), data contract (T2), component
  structure (T3–T6), honest-equivalents (T4 export, T5 approve/revert, T6
  audit label), testing (unit T2, component T3–T6, pytest + Playwright T7),
  error handling (T2 data.ts fallbacks), README (T7). Out-of-scope items have
  no tasks — correct.
- Marker discipline: marker exists only in `frontend/index.html`'s island;
  no JS string repeats it (`data.ts` tests use the marker string but tests
  are not bundled into the build). `install-template.mjs` enforces
  exactly-once at install time.
- Type consistency: `WorkbenchData/Claim/AuditEvent` defined once in T2 and
  imported everywhere; `effectiveStatus(claim, overrides)` signature used in
  T4 ClaimsTable, T5 App wiring, T6 SummaryScreen.
