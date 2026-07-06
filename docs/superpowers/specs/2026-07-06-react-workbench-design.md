# React Workbench — Design

**Date:** 2026-07-06
**Status:** Approved (design discussion in session)

## Goal

Reimplement the Denial Workbench frontend (currently vanilla JS inside
`overturn/templates/workbench.html`) in React 18 + TypeScript, while keeping
the deliverable exactly what it is today: `overturn report` renders one
self-contained HTML file from a run's `worklist.json` + `audit.jsonl`.
Feature parity only — no new features.

## Delivery model

- New `frontend/` directory: Vite + React 18 + TypeScript.
- `vite-plugin-singlefile` inlines all JS/CSS into a single HTML file.
- `npm run build` produces the bundle AND copies it to
  `overturn/templates/workbench.html`.
- The built template is **committed to git** so `pip install` from the repo
  needs no Node toolchain. README documents the rebuild step.
- Python side unchanged: `report.py` injects the data island by replacing
  the `/*__OVERTURN_DATA__*/{}` marker (first occurrence only) inside
  `<script id="overturn-data" type="application/json">`. The raw template
  (marker not replaced) must fall back to an empty batch so `npm run dev`
  and direct opens don't crash.
- `npm run dev` serves the app with a bundled sample-data fixture
  (`frontend/src/fixtures/sample.ts`) for hot-reload development without
  running the CLI. Fixture data is synthetic and clearly labeled.

## Data contract (unchanged)

`types.ts` mirrors `overturn/report.py`'s `build_report_data` output:

```ts
interface WorkbenchData {
  generatedOn: string | null;
  asOf: string | null;
  model: string | null;
  totalBilled: number;
  claims: Claim[];
  summary: { processed: number; drafts: number; failed: number };
  audit: AuditEvent[];
}
interface Claim {
  id: string; payer: string; carc: string; carcText: string | null;
  rarcs: string[]; billed: number; dos: string; denialDate: string;
  deadline: string | null; days: number | null;
  status: 'Draft Ready' | 'Failed';
  denialText: string; letter: string | null; refined: string | null;
  rule: string | null; error: string | null;
}
interface AuditEvent { time: string; type: string; detail: string }
```

## Component structure

- `App.tsx` — owns all state: screen ('worklist' | 'detail' | 'summary'),
  activeId, sort col/dir, four filter sets, selection, letter edits,
  status overrides (Approve → 'Submitted', session-local), toast.
- `lib/format.ts` — `fmtMoney`, `fmtDate`.
- `lib/worklist.ts` — `bucketOf` (incl. Overdue and No deadline),
  `daysChip`, `statusStyle`, `visibleSorted` (filter + sort, default sort:
  days-until-deadline asc then billed desc), `letterFileFor` /
  `downloadLetter` (markdown export via Blob).
- `components/TopBar.tsx` — brand, Worklist/Batch Summary tabs, run meta.
- `components/worklist/` — `FilterRail` (CARC/Payer/Status/Deadline groups
  with live counts + Reset), `StatsStrip` (total at stake, records,
  deadline pills, shown label), `BulkBar` (n selected, clear, export
  letters), `ClaimsTable` (sortable headers, row select, days + status
  pills, row click → detail).
- `components/detail/` — `DenialCard` (payer/dates/billed, CARC + RARC
  chips with DenialCodeDB text from the island, original denial text with
  PHI-placeholder chips and "PHI redacted before model call" badge),
  `AppealCard` (meta strip: model/cites/generated; failed banner OR
  editable letter textarea + refined-recommendation block; Approve / Edit /
  Revert draft / Export letter).
- `components/summary/` — `StatCards` (processed, drafts ready, approved
  this session, failed), `CarcBars` (dollars by CARC, sorted desc),
  `DeadlineBars` (Overdue, <7, 7–30, 30+, No deadline), `AuditTrail`
  (scrollable, typed chips, real audit.jsonl events).
- `components/ui/` — `Pill`, `StatusPill`, `Checkbox`, `Toast`.
- Styling: the existing design-token CSS from the vanilla template moves to
  `src/styles.css` as a global stylesheet — same class names, pixel-identical
  visuals. No CSS-in-JS.

## Honest-equivalents policy (carried over from v1)

- Export downloads the real letter markdown (single and bulk).
- Approve marks Submitted as clearly session-local state.
- "Revert draft" restores the generated letter (no fake "Regenerate").
- No fabricated statuses or retention claims; audit panel is labeled
  "from audit.jsonl · N events".

## Testing

- `frontend/`: Vitest + React Testing Library.
  - Unit: bucketing (overdue, no-deadline, boundaries 7/30), sorting,
    filtering, letter-file assembly.
  - Component: filter click updates shown count; Approve flips status pill
    and summary "Approved this session"; export triggers a download; failed
    claim shows banner and no letter actions.
- Python: existing pytest suite unchanged (guards data mapping and the
  single-replacement injection contract against the committed template).
- Final gate: `npm run build`, regenerate the 50-record report, Playwright
  pass over all three screens.

## Error handling

- Raw template (marker intact) → empty-batch fallback, page still renders.
- Guarded JSON.parse; malformed island shows an empty batch rather than a
  blank page.

## Out of scope

- Served SPA / API server, live re-generation, persistence of approvals or
  letter edits, routing/URLs per screen, dark mode.
