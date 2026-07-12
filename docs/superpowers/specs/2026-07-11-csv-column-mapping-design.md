# CSV Column Mapping, Normalization & Deadline Rules — Design

**Date:** 2026-07-11
**Status:** Approved (design discussion in session)

## Goal

Let a biller upload their clearinghouse/PM-system denial export unchanged.
Today the server accepts only the canonical nine-column simplified-835 CSV;
real exports have different headers, different value formats, and almost
never an appeal-deadline column. This feature adds header mapping (saved
per org), value normalization, and a deadline rule — making the upload path
usable with real-world exports.

Decisions locked:
- **Map on upload, remembered per org.** Unknown headers trigger an inline
  mapping step; the confirmed mapping is saved and auto-applied to future
  uploads with the same header set.
- **Deadline rule: org default only.** `appeal_deadline = denial_date + N
  days` (org setting, default 90) whenever no deadline column is mapped or
  a cell is blank. Per-payer overrides are a fast follow, not v1.
- **Client-side inspection, server-side truth.** The browser parses headers
  + sample rows for the mapping UI (new frontend dep: `papaparse`); the
  server re-parses and validates authoritatively with Python's csv module.
- Thin-host rule holds: mapping/normalization is ingestion adaptation
  (transport). The output of the engine is the package's `DenialRecord`
  contract; no appeal logic is added server-side.

## Canonical fields and requiredness

| Canonical | Required | Notes |
|---|---|---|
| claim_id | yes | |
| payer | yes | |
| carc_code | yes | single column OR two-column (group + code) composition |
| rarc_codes | no | split on `\|`, `,`, `;`, or whitespace |
| denial_reason_text | no | blank → empty string (pipeline tolerates) |
| billed_amount | yes | |
| service_date | yes | |
| denial_date | yes | |
| appeal_deadline | no | unmapped/blank → deadline rule |

## Ingestion engine — `server/ingest.py` (pure functions)

- `CANONICAL_FIELDS: dict[str, FieldSpec]` — requiredness + label.
- `suggest_mapping(headers: list[str]) -> dict[str, str | CarcPair]` —
  case/punctuation-insensitive synonym table. Seed synonyms (extensible):
  - claim_id: claim id/number/no, pcn, patient control number/no
  - payer: payer, payer name, carrier, insurance, plan
  - carc_code: carc, reason code, adj(ustment) reason code, denial code
  - carc group column: group code, adj(ustment) group, carc group
  - rarc_codes: rarc, remark code(s)
  - denial_reason_text: denial reason, reason, description, remark
  - billed_amount: billed, billed amount, charge(s), charge amount, total charges
  - service_date: service date, dos, date of service, from date
  - denial_date: denial date, denied date, remit date, remittance date, check date
  - appeal_deadline: appeal deadline, appeal by, deadline, file by
- Normalizers (each returns value or raises `ValueError` with a
  human-readable message):
  - `normalize_date(s)` — accepts `YYYY-MM-DD`, `MM/DD/YYYY`, `M/D/YY`
    (2-digit years pivot at 70 → 19xx/20xx), `YYYYMMDD`.
  - `normalize_amount(s)` — strips `$`, thousands commas, whitespace;
    rejects negatives and parenthesized negatives.
  - `normalize_carc(code, group=None)` — accepts `CO-50`, `CO50`, `co 50`,
    or bare `50` (+ group column value `CO`/`PR`/`OA`/`PI`/`CR`); bare code
    with NO group defaults the group to `CO` and flags a row note.
  - `split_rarcs(s)` — on `|`, `,`, `;`, whitespace; empties dropped.
- `apply_mapping(headers, rows, mapping, *, default_appeal_days) ->
  MappedResult` where `MappedResult = (records: list[DenialRecord],
  notes: list[RowNote], errors: list[RowError])`:
  - `RowError = {row: int, field: str, value: str, message: str}` —
    collected for ALL rows (not fail-fast).
  - `RowNote` — non-fatal (e.g. CARC group defaulted to CO).
  - Deadline rule applied here when `appeal_deadline` is unmapped or blank:
    `denial_date + default_appeal_days`.
  - Unmapped extra columns are ignored.
- The canonical (unmapped) upload path is byte-for-byte unchanged — the
  engine is only invoked when a `mapping` is supplied.

## Data model (migration 0004)

- `orgs.default_appeal_days` (int, NOT NULL, server_default 90).
- `csv_mappings` table: `id` (uuid pk), `org_id` (fk, indexed, CASCADE),
  `name` (text — defaults to "Mapping N"), `header_signature` (text —
  sha256 of the sorted, lowercased header list; unique per org),
  `headers` (jsonb — original header list), `mapping` (jsonb —
  `{canonical_field: source_header}` plus optional
  `{"carc_code": {"group": h1, "code": h2}}` form),
  `created_at`, `last_used_at`.

## API changes

- `POST /api/v1/runs` gains optional form fields:
  - `mapping` (JSON string) — when present, the server parses the CSV
    generically, runs `apply_mapping`, and builds the run from the
    resulting `DenialRecord`s. Validation failures → 422 with
    `{detail: {errors: RowError[] (capped at 20), totalErrors: n}}`.
    Row notes are recorded as a `csv_import_notes` audit event on the run.
  - `save_mapping` (bool, default false) — upsert into `csv_mappings` by
    header signature (updates `last_used_at`, `mapping`).
  - Without `mapping`, behavior is exactly today's (canonical parse).
    JSON uploads are unaffected entirely.
- `GET /api/v1/org/csv-mappings` (member) → list
  `{id, name, headers, mapping, lastUsedAt}`.
- `DELETE /api/v1/org/csv-mappings/{id}` (org admin) → 404 foreign/unknown.
- `GET /api/v1/org` payload gains `defaultAppealDays`;
  `PATCH /api/v1/org {defaultAppealDays}` (org admin; 422 unless
  1 ≤ N ≤ 365).
- Auto-apply on the server is NOT implicit: the client always sends the
  mapping explicitly (fetched from saved mappings). Keeps the upload
  endpoint deterministic.

## Frontend (served app)

- New dep: `papaparse` (+ types) — client-side preview parsing only.
- `RunsScreen` upload flow:
  1. On file select (.csv), parse headers + first 5 rows locally.
  2. Headers canonical → upload as today (no new UI).
  3. Else, exact `header_signature` match in saved mappings (fetched on
     mount) → badge "using saved mapping ✓ · Edit" and upload sends that
     mapping. Edit reopens the panel pre-filled.
  4. Else → inline **mapping panel**: one row per canonical field
     (required marked) with a dropdown of the file's headers plus
     "(not present)", sample values under each selection, suggestions
     pre-selected, a CARC mode toggle (single column ⇄ group + code
     columns), a deadline note ("no deadline column — appeal deadline will
     be denial date + {N} days" linking to Org Settings), and a
     "Remember this mapping" checkbox (default on). Confirm → upload with
     `mapping` (+ `save_mapping`).
  5. 422 row errors render as a compact table (row, field, value, message)
     above the upload form.
- `OrgSettingsScreen` gains a "Default appeal window" card (N days input,
  1–365) and a saved-mappings list (name, header count, last used, delete).
- Island/static build: untouched (no mapping UI is reachable there — the
  CLI keeps requiring canonical CSVs; documented in README).

## Testing

- **pytest** — engine: every normalizer (incl. rejects), suggestion table
  hits/misses, two-column CARC, bare-code CO default note, deadline rule
  (unmapped column AND blank cell), full-row error collection with mixed
  good/bad rows; API: upload with mapping happy path, 422 error shape,
  save_mapping upsert + signature dedupe, mappings list/delete with org
  scoping (foreign org 404), defaultAppealDays get/patch/validation,
  canonical path regression (unchanged), JSON uploads unaffected.
- **Vitest** — mapping panel render with suggestions, required-field gate,
  CARC toggle, saved-mapping auto-apply badge, error-table rendering.
- **E2E** — upload a messy clearinghouse-style CSV (`Claim Number`,
  `Carrier`, `Adj Group`/`Reason Code` split, `MM/DD/YYYY` dates,
  `$1,234.56` amounts, no deadline column) through the mapping panel →
  run completes → worklist shows computed deadlines; re-upload the same
  file → saved-mapping badge, no panel.

## Error handling

- 422 structured row errors (capped 20 in the response, total count
  included); 415/413/auth/org guards unchanged; malformed `mapping` JSON
  or unknown canonical keys → 422; mapping that omits a required field →
  422 before parsing rows.

## Out of scope

X12 835 parsing (healthflow-agents roadmap), per-payer deadline overrides,
JSON-upload mapping, CLI mapping support, fuzzy value transforms beyond the
normalizers, mapping suggestions via LLM.
