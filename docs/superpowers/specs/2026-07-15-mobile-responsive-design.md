# Mobile Responsive Frontend — Design

**Date:** 2026-07-15
**Status:** Approved (design authored by the owner in Claude Design)

## Problem

The frontend is desktop-only. The worklist table has `min-width: 1080px`, the
filter rail permanently occupies 222px, and the summary grid is fixed 4-up.
On a phone the workbench requires horizontal panning and the SPA screens
overflow. The owner updated the design source — Claude Design project
`1d6c80ea-6fb4-493d-b376-73054d9fdca3`, file **"Overturn v2.dc.html"** — with
a complete mobile treatment and asked for it to be implemented.

## Source of truth

The updated design file defines the mobile behavior for the three workbench
screens (worklist, claim detail, batch summary) and a refreshed brand lockup.
Its deltas are enumerated in full below so this spec is self-contained. The
SPA-only screens (runs, org settings, platform admin, login, invite, CSV
mapping) are not in the design; they get the same breakpoint and equivalent
treatment by extension (the complaint was "the frontend is not mobile
responsive", not just the workbench).

## Breakpoint & mechanism

- **One breakpoint: 760px** (the design computes `mobile = vw < 760`).
- **Structural swaps** (different components mounted) use a shared React hook
  `useIsMobile()` in `frontend/src/lib/useIsMobile.ts`, backed by
  `window.matchMedia('(max-width: 759px)')` with a change listener.
- **Style-only changes** (padding, grid columns, hiding) use CSS
  `@media (max-width: 759px)` in `frontend/src/styles.css`.
- Both build targets (static report template and served SPA) share these
  components, so both become responsive; the committed template is rebuilt.
- The viewport meta tag already exists in every entry HTML — no change.

## Workbench changes (from the design)

### Top bar (all viewports)
New brand lockup replacing the current 26px mark + plain wordmark:
- 30px logo, `border-radius: 8px`, accent background, shadows
  `inset 0 1px 0 rgba(255,255,255,0.25), 0 1px 3px rgba(46,91,218,0.5)`;
  new 18px mark: circular-arrow path `M20 12a8 8 0 1 1-3.2-6.4`
  (stroke #FFF, width 3, round caps) plus solid arrowhead
  `M17.4 1.6 L16.8 7.3 L22.3 6.1 Z` (fill #FFF).
- Two-line wordmark: **Overturn** (16px/700/-0.02em, white) with an
  accent-blue period (`#6E93F2`), and subtitle **Denial Workbench**
  (mono, 8.5px, 500, letter-spacing 0.18em, uppercase, `#8B8981`).
- Mobile (≤759px): the right-side meta text ("worklist … · deadlines as of …")
  is hidden; top-bar padding tightens to 12px. Tabs and divider remain.
- The design's "KD" avatar is placeholder filler — not implemented (the SPA
  chrome carries the real account controls).

### Worklist
Mobile (≤759px):
- **Filter rail hidden.** In its place, a horizontally scrollable **quick-filter
  chip row** under the stats strip: deadline-bucket chips then status chips,
  toggling the same `fBucket`/`fStatus` filter state (labels from the existing
  `filterGroups()`; only groups with data appear). Active chip = dark
  (`#1E1E1B` bg, white text). A leading **Reset** chip appears when any filter
  is active (covers CARC/payer filters set earlier on desktop, which have no
  mobile UI).
- **Card list replaces the table.** One card per claim (same
  `visibleSorted` order — deadline-first): row 1 checkbox + claim ID +
  billed amount; row 2 payer · CARC code + reason (ellipsized); row 3
  days-left pill + status pill + "due <deadline>" (— when no deadline).
  Tap opens detail; checkbox still multi-selects (selected card tints
  `#EEF2FC`). Sort headers are desktop-only, as in the design.
- Stats strip: padding `12px 12px 10px`; the "Showing" block is hidden.
- Bulk action bar: margin `0 12px 10px`; unchanged otherwise.

### Claim detail
- Padding `12px 12px 24px` on mobile.
- Single-column card stack: the existing 980px rule already stacks the two
  cards and is **kept** (it supersets the design's 760px value — the design's
  desktop grid has an 816px minimum width and would overflow between 760 and
  980px).

### Batch summary
- Stat cards `repeat(2, 1fr)` at ≤759px (2×2); back to 4-up above. The
  current 900px rule collapsing `.sm-cards` to 1 column is replaced by this.
- Main grid stays 1-column ≤900px (existing rule, kept).
- Inner padding `16px 12px 28px` on mobile.

## SPA screens (extension, same breakpoint)

- **App chrome bars** (org header, run header, demo banner): move inline
  styles to shared classes; on mobile they wrap and use 12px side padding.
- **`.audit-row`** (used for runs list, members, invites, saved mappings,
  admin orgs, row errors, audit trail): `flex-wrap: wrap` on mobile so long
  rows fold instead of truncating; `.audit-detail` allowed to wrap.
- **MappingPanel / forms**: existing flex rows already wrap or inherit the
  `.audit-row` fix; inputs keep `width: 100%` within their labels.
- **Login / accept-invite**: already narrow centered cards; only inherit
  detail-padding fix. No functional changes anywhere.

## Testing

- **Vitest**: `useIsMobile` hook behavior (matchMedia mock installed in
  `vitest.setup.ts`, default desktop, per-test override helper); worklist
  swap tests (mobile → chips + cards, no rail/table; desktop → inverse);
  chip toggling drives the same filter state; card click-through and
  checkbox selection.
- **Playwright e2e**: new `e2e/mobile.spec.ts` with a 390×844 viewport
  against the read-only demo: cards + chips render, table and rail absent,
  chip toggles active state, card opens detail, Batch Summary renders.
  Existing desktop specs unchanged.
- **Template sync**: `npm run build:template` rerun; committed
  `overturn/templates/workbench.html` updated (CI enforces sync).

## Out of scope

- README screenshot refresh (brand lockup changes them slightly).
- Any server/API change; any new mobile-only feature (e.g. mobile sort UI).
- The design file's demo-data divergences (Regenerate button, `.docx` export,
  hardcoded batch strings) — the implemented workbench keeps its real
  behaviors (Revert, `.md` export, live data).
