# CSV Column Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Billers upload clearinghouse denial exports unchanged: header mapping (auto-suggested, saved per org), value normalization (dates/amounts/CARC composition/RARC lists), and an org-default appeal-deadline rule.

**Architecture:** A pure-function ingestion engine (`server/ingest.py`) maps and normalizes arbitrary CSV rows into the package's `DenialRecord` contract, collecting all row errors. `POST /runs` gains optional `mapping`/`save_mapping` form fields; mappings persist in a `csv_mappings` table keyed by header signature; `orgs.default_appeal_days` powers the deadline rule. The SPA inspects files client-side (papaparse) and shows an inline mapping panel with suggestions; saved mappings auto-apply.

**Tech Stack:** Existing Phase 2 stack + `papaparse` (frontend only). No new Python deps.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-11-csv-column-mapping-design.md`. Thin-host: engine output is `DenialRecord`; no appeal logic.
- Canonical fields: required = claim_id, payer, carc_code, billed_amount, service_date, denial_date; optional = rarc_codes, denial_reason_text, appeal_deadline.
- Deadline rule: `denial_date + org.default_appeal_days` (default 90, valid 1–365) when appeal_deadline unmapped OR cell blank.
- Row errors collected for ALL rows; 422 response detail `{errors: [...capped 20], totalErrors: n}`; `RowError = {row, field, value, message}`.
- Bare numeric CARC with no group column → group defaults to `CO` + row note; notes recorded as one `csv_import_notes` audit event.
- Canonical-CSV and JSON upload paths byte-for-byte unchanged; CLI untouched; island/template build untouched (mapping UI lives in `src/app/` only — verify template bytes unchanged; do not commit it).
- Baselines: pytest 108, vitest 62, e2e 2 (Postgres container up; compose stack running).
- Every commit message ends with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: Ingestion engine (`server/ingest.py`)

**Files:**
- Create: `server/ingest.py`
- Test: `tests/server/test_ingest.py`

**Interfaces:**
- Produces (used by Tasks 3–4):
  - `REQUIRED_FIELDS: tuple[str, ...]`, `OPTIONAL_FIELDS: tuple[str, ...]`, `CANONICAL_FIELDS: tuple[str, ...]`
  - `header_signature(headers: list[str]) -> str` (sha256 hex of the sorted, normalized header list)
  - `suggest_mapping(headers: list[str]) -> dict` — values are source-header strings; `carc_code` may be `{"group": str, "code": str}` when a group column is detected
  - `validate_mapping(headers, mapping) -> None` (raises `ValueError` on unknown canonical keys, missing required fields, or source headers not in the file)
  - `normalize_date(s: str) -> date`, `normalize_amount(s: str) -> float`, `normalize_carc(code: str, group: str | None = None) -> tuple[str, str | None]` (returns (canonical, note-or-None)), `split_rarcs(s: str) -> list[str]` — normalizers raise `ValueError` with human-readable messages
  - `apply_mapping(headers, rows: list[dict], mapping: dict, *, default_appeal_days: int) -> MappedResult` with `MappedResult(records: list[DenialRecord], notes: list[RowNote], errors: list[RowError])`; `RowError(row: int, field: str, value: str, message: str)`, `RowNote(row: int, message: str)` (dataclasses with `.as_dict()`)

- [ ] **Step 1: Write the failing tests**

`tests/server/test_ingest.py`:

```python
from datetime import date

import pytest

from server.ingest import (
    apply_mapping, header_signature, normalize_amount, normalize_carc,
    normalize_date, split_rarcs, suggest_mapping, validate_mapping,
)

WAYSTAR_HEADERS = [
    "Claim Number", "Carrier", "Adj Group", "Reason Code", "Remark Codes",
    "Denial Reason", "Total Charges", "DOS", "Check Date", "Extra Col",
]


class TestNormalizers:
    @pytest.mark.parametrize("raw,expected", [
        ("2026-04-10", date(2026, 4, 10)),
        ("04/10/2026", date(2026, 4, 10)),
        ("4/1/26", date(2026, 4, 1)),
        ("12/31/71", date(1971, 12, 31)),   # 2-digit pivot at 70
        ("20260410", date(2026, 4, 10)),
    ])
    def test_dates(self, raw, expected):
        assert normalize_date(raw) == expected

    def test_bad_date_raises(self):
        with pytest.raises(ValueError, match="date"):
            normalize_date("April 10th")

    @pytest.mark.parametrize("raw,expected", [
        ("12500.00", 12500.0), ("$12,500.00", 12500.0),
        (" 1,234 ", 1234.0), ("$85", 85.0),
    ])
    def test_amounts(self, raw, expected):
        assert normalize_amount(raw) == expected

    @pytest.mark.parametrize("raw", ["-50", "(1,200.00)", "twelve"])
    def test_bad_amounts_raise(self, raw):
        with pytest.raises(ValueError):
            normalize_amount(raw)

    @pytest.mark.parametrize("code,group,expected,has_note", [
        ("CO-50", None, "CO-50", False),
        ("CO50", None, "CO-50", False),
        ("co 45", None, "CO-45", False),
        ("50", "CO", "CO-50", False),
        ("204", "pr", "PR-204", False),
        ("50", None, "CO-50", True),          # bare code -> CO + note
    ])
    def test_carc(self, code, group, expected, has_note):
        canonical, note = normalize_carc(code, group)
        assert canonical == expected
        assert (note is not None) == has_note

    def test_bad_carc_raises(self):
        with pytest.raises(ValueError):
            normalize_carc("not-a-code")
        with pytest.raises(ValueError):
            normalize_carc("50", "ZZ")

    def test_split_rarcs(self):
        assert split_rarcs("N115|M25") == ["N115", "M25"]
        assert split_rarcs("N115, M25; N30 M76") == ["N115", "M25", "N30", "M76"]
        assert split_rarcs("") == []


class TestSuggestions:
    def test_waystar_style_headers(self):
        s = suggest_mapping(WAYSTAR_HEADERS)
        assert s["claim_id"] == "Claim Number"
        assert s["payer"] == "Carrier"
        assert s["carc_code"] == {"group": "Adj Group", "code": "Reason Code"}
        assert s["rarc_codes"] == "Remark Codes"
        assert s["denial_reason_text"] == "Denial Reason"
        assert s["billed_amount"] == "Total Charges"
        assert s["service_date"] == "DOS"
        assert s["denial_date"] == "Check Date"
        assert "appeal_deadline" not in s

    def test_canonical_headers_map_to_themselves(self):
        s = suggest_mapping(["claim_id", "payer", "carc_code", "billed_amount"])
        assert s["claim_id"] == "claim_id" and s["carc_code"] == "carc_code"

    def test_signature_is_order_and_case_insensitive(self):
        a = header_signature(["Claim Number", "Carrier"])
        b = header_signature(["carrier", "CLAIM NUMBER"])
        assert a == b and len(a) == 64


class TestValidateMapping:
    GOOD = {
        "claim_id": "Claim Number", "payer": "Carrier",
        "carc_code": {"group": "Adj Group", "code": "Reason Code"},
        "billed_amount": "Total Charges", "service_date": "DOS",
        "denial_date": "Check Date",
    }

    def test_good_mapping_passes(self):
        validate_mapping(WAYSTAR_HEADERS, self.GOOD)

    def test_missing_required_field(self):
        bad = {k: v for k, v in self.GOOD.items() if k != "payer"}
        with pytest.raises(ValueError, match="payer"):
            validate_mapping(WAYSTAR_HEADERS, bad)

    def test_unknown_canonical_key(self):
        with pytest.raises(ValueError, match="unknown"):
            validate_mapping(WAYSTAR_HEADERS, {**self.GOOD, "bogus": "Carrier"})

    def test_source_header_not_in_file(self):
        with pytest.raises(ValueError, match="Nope"):
            validate_mapping(WAYSTAR_HEADERS, {**self.GOOD, "payer": "Nope"})


def waystar_row(**over):
    row = {
        "Claim Number": "CLM-1001", "Carrier": "Acme Ins", "Adj Group": "CO",
        "Reason Code": "50", "Remark Codes": "N115",
        "Denial Reason": "Not medically necessary",
        "Total Charges": "$12,500.00", "DOS": "04/10/2026",
        "Check Date": "05/01/2026", "Extra Col": "ignored",
    }
    row.update(over)
    return row


class TestApplyMapping:
    MAPPING = TestValidateMapping.GOOD | {
        "rarc_codes": "Remark Codes", "denial_reason_text": "Denial Reason",
    }

    def test_happy_path_with_deadline_rule(self):
        result = apply_mapping(
            WAYSTAR_HEADERS, [waystar_row()], self.MAPPING,
            default_appeal_days=90,
        )
        assert not result.errors
        (rec,) = result.records
        assert rec.claim_id == "CLM-1001"
        assert rec.carc_code == "CO-50"
        assert rec.rarc_codes == ["N115"]
        assert rec.billed_amount == 12500.0
        assert rec.service_date == date(2026, 4, 10)
        assert rec.denial_date == date(2026, 5, 1)
        # no deadline column mapped -> denial_date + 90
        assert rec.appeal_deadline == date(2026, 7, 30)

    def test_errors_collected_across_rows_not_fail_fast(self):
        rows = [
            waystar_row(),
            waystar_row(**{"Total Charges": "free", "Claim Number": "CLM-1002"}),
            waystar_row(**{"DOS": "bogus", "Claim Number": "CLM-1003"}),
        ]
        result = apply_mapping(WAYSTAR_HEADERS, rows, self.MAPPING,
                               default_appeal_days=90)
        assert len(result.records) == 1
        assert len(result.errors) == 2
        assert {e.row for e in result.errors} == {1, 2}
        assert result.errors[0].field == "billed_amount"
        assert result.errors[0].value == "free"

    def test_bare_carc_without_group_notes(self):
        headers = [h for h in WAYSTAR_HEADERS if h != "Adj Group"]
        mapping = {**self.MAPPING, "carc_code": "Reason Code"}
        row = waystar_row()
        del row["Adj Group"]
        result = apply_mapping(headers, [row], mapping, default_appeal_days=90)
        assert result.records[0].carc_code == "CO-50"
        assert len(result.notes) == 1 and "CO" in result.notes[0].message

    def test_blank_deadline_cell_uses_rule(self):
        headers = WAYSTAR_HEADERS + ["Appeal By"]
        mapping = {**self.MAPPING, "appeal_deadline": "Appeal By"}
        rows = [
            waystar_row(**{"Appeal By": "06/15/2026"}),
            waystar_row(**{"Appeal By": "", "Claim Number": "CLM-1002"}),
        ]
        result = apply_mapping(headers, rows, mapping, default_appeal_days=30)
        assert result.records[0].appeal_deadline == date(2026, 6, 15)
        assert result.records[1].appeal_deadline == date(2026, 5, 31)

    def test_missing_optional_text_defaults_empty(self):
        mapping = {k: v for k, v in self.MAPPING.items()
                   if k != "denial_reason_text"}
        result = apply_mapping(WAYSTAR_HEADERS, [waystar_row()], mapping,
                               default_appeal_days=90)
        assert result.records[0].denial_reason_text == ""
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/server/test_ingest.py -q`
Expected: FAIL — `server.ingest` missing.

- [ ] **Step 3: Implement**

`server/ingest.py`:

```python
"""CSV ingestion adaptation: header mapping, value normalization, deadline rule.

Transport-layer only — the engine's output is the healthflow-agents
DenialRecord contract. No appeal logic lives here.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from healthflow_agents.contracts.denial_record import DenialRecord
from pydantic import ValidationError

REQUIRED_FIELDS: tuple[str, ...] = (
    "claim_id", "payer", "carc_code", "billed_amount",
    "service_date", "denial_date",
)
OPTIONAL_FIELDS: tuple[str, ...] = (
    "rarc_codes", "denial_reason_text", "appeal_deadline",
)
CANONICAL_FIELDS: tuple[str, ...] = REQUIRED_FIELDS + OPTIONAL_FIELDS

_SYNONYMS: dict[str, tuple[str, ...]] = {
    "claim_id": ("claim id", "claim number", "claim no", "claim",
                 "pcn", "patient control number", "patient control no"),
    "payer": ("payer", "payer name", "carrier", "insurance", "plan"),
    "carc_code": ("carc", "carc code", "reason code", "adj reason code",
                  "adjustment reason code", "denial code"),
    "rarc_codes": ("rarc", "rarc code", "rarc codes",
                   "remark code", "remark codes"),
    "denial_reason_text": ("denial reason", "reason", "description", "remark"),
    "billed_amount": ("billed", "billed amount", "charge", "charges",
                      "charge amount", "total charges"),
    "service_date": ("service date", "dos", "date of service", "from date"),
    "denial_date": ("denial date", "denied date", "remit date",
                    "remittance date", "check date"),
    "appeal_deadline": ("appeal deadline", "appeal by", "deadline", "file by"),
}
_GROUP_SYNONYMS = ("group code", "adj group", "adjustment group", "carc group")
_CARC_GROUPS = ("CO", "PR", "OA", "PI", "CR")


def _norm(header: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", header.lower())).strip()


def header_signature(headers: list[str]) -> str:
    joined = "\n".join(sorted(_norm(h) for h in headers))
    return hashlib.sha256(joined.encode()).hexdigest()


def suggest_mapping(headers: list[str]) -> dict:
    by_norm = {_norm(h): h for h in headers}
    out: dict = {}
    for canonical in CANONICAL_FIELDS:
        candidates = (_norm(canonical),) + tuple(
            _norm(s) for s in _SYNONYMS.get(canonical, ())
        )
        for cand in candidates:
            if cand in by_norm:
                out[canonical] = by_norm[cand]
                break
    group_header = next(
        (by_norm[_norm(s)] for s in _GROUP_SYNONYMS if _norm(s) in by_norm),
        None,
    )
    if group_header and isinstance(out.get("carc_code"), str):
        out["carc_code"] = {"group": group_header, "code": out["carc_code"]}
    return out


def validate_mapping(headers: list[str], mapping: dict) -> None:
    header_set = set(headers)

    def check_source(field_name: str, source: str) -> None:
        if source not in header_set:
            raise ValueError(
                f"mapping for {field_name!r} references column {source!r} "
                "which is not in the file"
            )

    for key, source in mapping.items():
        if key not in CANONICAL_FIELDS:
            raise ValueError(f"unknown field {key!r} in mapping")
        if key == "carc_code" and isinstance(source, dict):
            if set(source) != {"group", "code"}:
                raise ValueError("carc_code mapping must be a column name or "
                                 "{'group': ..., 'code': ...}")
            check_source(key, source["group"])
            check_source(key, source["code"])
        elif isinstance(source, str):
            check_source(key, source)
        else:
            raise ValueError(f"mapping for {key!r} must be a column name")
    missing = [f for f in REQUIRED_FIELDS if f not in mapping]
    if missing:
        raise ValueError(f"mapping is missing required fields: {', '.join(missing)}")


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y%m%d")


def normalize_date(s: str) -> date:
    raw = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
        if fmt == "%m/%d/%y":  # strptime pivots at 69; spec pivots at 70
            year = parsed.year % 100
            parsed = parsed.replace(year=(1900 if year >= 70 else 2000) + year)
        return parsed
    raise ValueError(f"could not parse date {s!r} (use YYYY-MM-DD or MM/DD/YYYY)")


def normalize_amount(s: str) -> float:
    raw = s.strip().replace("$", "").replace(",", "").strip()
    if raw.startswith("(") or raw.startswith("-"):
        raise ValueError(f"negative amount {s!r} is not a valid billed amount")
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"could not parse amount {s!r}") from None


def normalize_carc(code: str, group: str | None = None) -> tuple[str, str | None]:
    raw = code.strip().upper()
    match = re.fullmatch(r"(?:(CO|PR|OA|PI|CR)[\s-]?)?(\d{1,3})", raw)
    if match is None:
        raise ValueError(f"could not parse CARC code {code!r}")
    embedded_group, number = match.group(1), match.group(2)
    if group is not None and group.strip():
        g = group.strip().upper()
        if g not in _CARC_GROUPS:
            raise ValueError(f"unknown CARC group {group!r}")
        return f"{g}-{number}", None
    if embedded_group:
        return f"{embedded_group}-{number}", None
    return f"CO-{number}", f"CARC {number} had no group code; assumed CO"


def split_rarcs(s: str) -> list[str]:
    return [p for p in re.split(r"[|,;\s]+", s.strip()) if p]


@dataclass
class RowError:
    row: int
    field: str
    value: str
    message: str

    def as_dict(self) -> dict:
        return {"row": self.row, "field": self.field,
                "value": self.value, "message": self.message}


@dataclass
class RowNote:
    row: int
    message: str

    def as_dict(self) -> dict:
        return {"row": self.row, "message": self.message}


@dataclass
class MappedResult:
    records: list[DenialRecord] = field(default_factory=list)
    notes: list[RowNote] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


def _cell(row: dict, source: str) -> str:
    return (row.get(source) or "").strip()


def apply_mapping(
    headers: list[str],
    rows: list[dict],
    mapping: dict,
    *,
    default_appeal_days: int,
) -> MappedResult:
    validate_mapping(headers, mapping)
    result = MappedResult()

    for i, row in enumerate(rows):
        errors_before = len(result.errors)
        values: dict = {}

        def take(field_name: str, raw: str, fn):
            try:
                values[field_name] = fn(raw)
            except ValueError as exc:
                result.errors.append(RowError(i, field_name, raw, str(exc)))

        claim_id = _cell(row, mapping["claim_id"])
        if not claim_id:
            result.errors.append(RowError(i, "claim_id", "", "claim id is empty"))
        values["claim_id"] = claim_id
        payer = _cell(row, mapping["payer"])
        if not payer:
            result.errors.append(RowError(i, "payer", "", "payer is empty"))
        values["payer"] = payer

        carc_map = mapping["carc_code"]
        if isinstance(carc_map, dict):
            raw_code = _cell(row, carc_map["code"])
            raw_group = _cell(row, carc_map["group"])
        else:
            raw_code, raw_group = _cell(row, carc_map), ""
        try:
            canonical, note = normalize_carc(raw_code, raw_group or None)
            values["carc_code"] = canonical
            if note:
                result.notes.append(RowNote(i, note))
        except ValueError as exc:
            result.errors.append(RowError(i, "carc_code", raw_code, str(exc)))

        take("billed_amount", _cell(row, mapping["billed_amount"]), normalize_amount)
        take("service_date", _cell(row, mapping["service_date"]), normalize_date)
        take("denial_date", _cell(row, mapping["denial_date"]), normalize_date)

        values["rarc_codes"] = (
            split_rarcs(_cell(row, mapping["rarc_codes"]))
            if "rarc_codes" in mapping else []
        )
        values["denial_reason_text"] = (
            _cell(row, mapping["denial_reason_text"])
            if "denial_reason_text" in mapping else ""
        )

        deadline_raw = (
            _cell(row, mapping["appeal_deadline"])
            if "appeal_deadline" in mapping else ""
        )
        if deadline_raw:
            take("appeal_deadline", deadline_raw, normalize_date)
        elif "denial_date" in values and isinstance(values["denial_date"], date):
            values["appeal_deadline"] = (
                values["denial_date"] + timedelta(days=default_appeal_days)
            )

        if len(result.errors) > errors_before:
            continue
        try:
            result.records.append(DenialRecord(**values))
        except ValidationError as exc:
            result.errors.append(RowError(i, "record", claim_id, str(exc)[:200]))

    return result
```

- [ ] **Step 4: Run to verify pass; commit**

Run: `.venv/bin/python -m pytest tests/server/ -q` — all pass (108 + ~20 new).

```bash
git add server/ingest.py tests/server/test_ingest.py
git commit -m "ingest: CSV mapping engine — suggestions, normalizers, deadline rule"
```

---

### Task 2: Migration 0004, org setting, mapping persistence API

**Files:**
- Modify: `server/models.py` (Org.default_appeal_days; CsvMapping model)
- Create: `server/migrations/versions/0004_csv_mappings.py`
- Modify: `server/api/org.py` (org payload + PATCH; csv-mappings list/delete)
- Modify: `server/payloads.py` — none needed (org payload lives in org.py)
- Test: `tests/server/test_csv_mappings_api.py`; extend `tests/server/test_org_api.py` expectations if they assert the exact GET /org dict

**Interfaces:**
- Produces: `Org.default_appeal_days: int` (default 90); `CsvMapping(id, org_id, name, header_signature, headers jsonb, mapping jsonb, created_at, last_used_at)` with `UniqueConstraint(org_id, header_signature)`.
- Routes: `GET /api/v1/org` gains `defaultAppealDays`; `PATCH /api/v1/org {defaultAppealDays}` (admin; 422 unless 1–365) → org info payload; `GET /api/v1/org/csv-mappings` (member) → `[{id, name, headers, mapping, lastUsedAt}]`; `DELETE /api/v1/org/csv-mappings/{id}` (admin; 404 unknown/foreign).
- Helper for Task 3: `upsert_csv_mapping(session, org_id, headers, mapping) -> CsvMapping` (exported from `server/api/org.py`).

- [ ] **Step 1: Write the failing tests**

`tests/server/test_csv_mappings_api.py`:

```python
from tests.server.conftest import login_as, make_org, make_user

MAPPING = {
    "claim_id": "Claim Number", "payer": "Carrier",
    "carc_code": {"group": "Adj Group", "code": "Reason Code"},
    "billed_amount": "Total Charges", "service_date": "DOS",
    "denial_date": "Check Date",
}
HEADERS = ["Claim Number", "Carrier", "Adj Group", "Reason Code",
           "Total Charges", "DOS", "Check Date"]


def org_admin(client, session_factory, name="Acme RCM"):
    org = make_org(session_factory, name=name)
    make_user(session_factory, "boss@acme.com", "pw12345678", org=org, role="admin")
    login_as(client, "boss@acme.com", "pw12345678")
    return org


def test_default_appeal_days_get_and_patch(client, session_factory):
    org_admin(client, session_factory)
    assert client.get("/api/v1/org").json()["defaultAppealDays"] == 90
    r = client.patch("/api/v1/org", json={"defaultAppealDays": 120})
    assert r.status_code == 200 and r.json()["defaultAppealDays"] == 120
    assert client.patch("/api/v1/org", json={"defaultAppealDays": 0}).status_code == 422
    assert client.patch("/api/v1/org", json={"defaultAppealDays": 400}).status_code == 422


def test_patch_requires_admin(client, session_factory):
    org = org_admin(client, session_factory)
    make_user(session_factory, "biller@acme.com", "pw12345678", org=org)
    login_as(client, "biller@acme.com", "pw12345678")
    assert client.patch("/api/v1/org", json={"defaultAppealDays": 60}).status_code == 403


def test_mapping_upsert_and_list(client, session_factory):
    from server.api.org import upsert_csv_mapping
    org = org_admin(client, session_factory)
    with session_factory() as s:
        upsert_csv_mapping(s, org.id, HEADERS, MAPPING)
        upsert_csv_mapping(s, org.id, list(reversed(HEADERS)), MAPPING)  # same sig
        s.commit()
    listed = client.get("/api/v1/org/csv-mappings").json()
    assert len(listed) == 1
    assert listed[0]["mapping"]["claim_id"] == "Claim Number"
    assert listed[0]["headers"] == HEADERS


def test_mapping_delete_scoped(client, session_factory):
    from server.api.org import upsert_csv_mapping
    org = org_admin(client, session_factory)
    other = make_org(session_factory, name="Other Org")
    with session_factory() as s:
        mine = upsert_csv_mapping(s, org.id, HEADERS, MAPPING)
        theirs = upsert_csv_mapping(s, other.id, HEADERS, MAPPING)
        s.commit()
        mine_id, theirs_id = str(mine.id), str(theirs.id)
    assert client.delete(f"/api/v1/org/csv-mappings/{theirs_id}").status_code == 404
    assert client.delete(f"/api/v1/org/csv-mappings/{mine_id}").status_code == 200
    assert client.get("/api/v1/org/csv-mappings").json() == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/server/test_csv_mappings_api.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`server/models.py` — on `Org` add:

```python
    default_appeal_days: Mapped[int] = mapped_column(default=90)
```

and add the model:

```python
class CsvMapping(Base):
    __tablename__ = "csv_mappings"
    __table_args__ = (UniqueConstraint("org_id", "header_signature"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(default="Mapping")
    header_signature: Mapped[str]
    headers: Mapped[list] = mapped_column(JSONB, default=list)
    mapping: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
```

`server/migrations/versions/0004_csv_mappings.py` (down_revision `"0003_dismiss_reason"`):

```python
"""orgs.default_appeal_days + csv_mappings table"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0004_csv_mappings"
down_revision = "0003_dismiss_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orgs", sa.Column("default_appeal_days", sa.Integer(),
                                    nullable=False, server_default="90"))
    op.create_table(
        "csv_mappings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True),
                  sa.ForeignKey("orgs.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False, server_default="Mapping"),
        sa.Column("header_signature", sa.String(), nullable=False),
        sa.Column("headers", JSONB, nullable=False),
        sa.Column("mapping", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("org_id", "header_signature"),
    )


def downgrade() -> None:
    op.drop_table("csv_mappings")
    op.drop_column("orgs", "default_appeal_days")
```

Apply: `DATABASE_URL=postgresql+psycopg://overturn:overturn@localhost:5433/overturn .venv/bin/alembic upgrade head`

`server/api/org.py` — extend `org_info` payload with
`"defaultAppealDays": ctx.org.default_appeal_days`; add:

```python
from server.ingest import header_signature
from server.models import CsvMapping, utcnow


class OrgPatch(BaseModel):
    defaultAppealDays: int


@router.patch("")
def patch_org(
    body: OrgPatch,
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> dict:
    if not (1 <= body.defaultAppealDays <= 365):
        raise HTTPException(422, detail="defaultAppealDays must be 1-365")
    org = session.get(type(ctx.org), ctx.org.id)
    org.default_appeal_days = body.defaultAppealDays
    return {
        "id": str(org.id), "name": org.name, "role": ctx.role,
        "hasApiKey": org.anthropic_key_encrypted is not None,
        "apiKeyLast4": org.anthropic_key_last4,
        "defaultAppealDays": org.default_appeal_days,
    }


def upsert_csv_mapping(session: Session, org_id, headers: list, mapping: dict):
    sig = header_signature(headers)
    existing = session.scalars(
        select(CsvMapping).where(CsvMapping.org_id == org_id,
                                 CsvMapping.header_signature == sig)
    ).first()
    if existing is not None:
        existing.mapping = mapping
        existing.headers = headers
        existing.last_used_at = utcnow()
        return existing
    row = CsvMapping(org_id=org_id, header_signature=sig,
                     headers=headers, mapping=mapping,
                     name=f"Mapping ({len(headers)} columns)")
    session.add(row)
    session.flush()
    return row


@router.get("/csv-mappings")
def list_csv_mappings(
    ctx: OrgContext = Depends(current_org),
    session: Session = Depends(get_session),
) -> list[dict]:
    rows = session.scalars(
        select(CsvMapping).where(CsvMapping.org_id == ctx.org.id)
        .order_by(CsvMapping.last_used_at.desc())
    ).all()
    return [
        {"id": str(m.id), "name": m.name, "headers": m.headers,
         "mapping": m.mapping, "lastUsedAt": m.last_used_at.isoformat()}
        for m in rows
    ]


@router.delete("/csv-mappings/{mapping_id}")
def delete_csv_mapping(
    mapping_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> dict:
    row = session.get(CsvMapping, mapping_id)
    if row is None or row.org_id != ctx.org.id:
        raise HTTPException(404, detail="mapping not found")
    session.delete(row)
    return {"deleted": str(mapping_id)}
```

(Route order caution: `@router.get("/csv-mappings")` and the member-info
`@router.get("")` coexist fine; ensure the csv-mappings routes are declared
BEFORE any `/{...}` catch-alls if such exist — currently org.py has only
fixed paths plus `/members/{user_id}`, so no conflict.)

If `tests/server/test_org_api.py::test_org_info_and_key_lifecycle` asserts
exact keys of GET /org, extend its expectation with `defaultAppealDays: 90`
(update-not-delete rule).

- [ ] **Step 4: Run to verify pass; commit**

Run: `.venv/bin/python -m pytest tests/server/ -q` — all pass.

```bash
git add server/ tests/server/
git commit -m "ingest: org default appeal days + saved csv mappings API (migration 0004)"
```

---

### Task 3: Upload integration — mapping form field, structured 422, notes audit

**Files:**
- Modify: `server/api/runs.py` (`create_run` gains `mapping`/`save_mapping`)
- Test: `tests/server/test_upload_mapping.py`

**Interfaces:**
- Consumes Tasks 1–2 (`apply_mapping`, `validate_mapping` errors → 422; `upsert_csv_mapping`).
- Produces: `POST /api/v1/runs` optional form fields `mapping` (JSON string), `save_mapping` (bool). With mapping: generic csv.DictReader parse → `apply_mapping(headers, rows, mapping, default_appeal_days=ctx.org.default_appeal_days)`; any `RowError`s → 422 `{"detail": {"errors": [...≤20], "totalErrors": n}}`; malformed mapping JSON / validate_mapping failure → 422 string detail; notes → one `csv_import_notes` audit event `{count, notes: [...≤20]}`; `save_mapping=true` upserts. Existing checks (extension 415, record cap 413, live-needs-key 422, empty 422) apply in both paths.

- [ ] **Step 1: Write the failing tests**

`tests/server/test_upload_mapping.py`:

```python
import io
import json

from server.models import AuditEvent, Claim, Run
from tests.server.conftest import login_as, make_org, make_user

MESSY_CSV = """\
Claim Number,Carrier,Adj Group,Reason Code,Remark Codes,Denial Reason,Total Charges,DOS,Check Date
CLM-9001,Acme Ins,CO,50,N115,Not medically necessary,"$12,500.00",04/10/2026,05/01/2026
CLM-9002,Acme Ins,PR,204,,Plan exclusion,430.25,03/02/2026,04/15/2026
"""

MAPPING = {
    "claim_id": "Claim Number", "payer": "Carrier",
    "carc_code": {"group": "Adj Group", "code": "Reason Code"},
    "rarc_codes": "Remark Codes", "denial_reason_text": "Denial Reason",
    "billed_amount": "Total Charges", "service_date": "DOS",
    "denial_date": "Check Date",
}


def setup_org(client, session_factory):
    org = make_org(session_factory, name="Mapped Org")
    make_user(session_factory, "m@m.m", "pw12345678", org=org, role="admin")
    login_as(client, "m@m.m", "pw12345678")
    return org


def upload_mapped(client, csv_text=MESSY_CSV, mapping=MAPPING, save=False):
    return client.post(
        "/api/v1/runs",
        files={"file": ("waystar.csv", io.BytesIO(csv_text.encode()), "text/csv")},
        data={"dry_run": "true", "mapping": json.dumps(mapping),
              "save_mapping": "true" if save else "false"},
    )


def test_mapped_upload_creates_run(client, session_factory):
    setup_org(client, session_factory)
    r = upload_mapped(client)
    assert r.status_code == 202, r.text
    with session_factory() as s:
        run = s.query(Run).one()
        assert run.total_records == 2
        claims = {c.claim_id: c for c in s.query(Claim).all()}
        assert claims["CLM-9001"].carc_code == "CO-50"
        assert float(claims["CLM-9001"].billed_amount) == 12500.0
        assert claims["CLM-9001"].service_date.isoformat() == "2026-04-10"
        # deadline rule: denial 2026-05-01 + 90 (org default)
        assert claims["CLM-9001"].appeal_deadline.isoformat() == "2026-07-30"
        assert claims["CLM-9002"].carc_code == "PR-204"


def test_row_errors_structured_422(client, session_factory):
    setup_org(client, session_factory)
    bad = MESSY_CSV.replace('"$12,500.00"', "free").replace("04/15/2026", "nope")
    r = upload_mapped(client, csv_text=bad)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["totalErrors"] == 2
    fields = {e["field"] for e in detail["errors"]}
    assert fields == {"billed_amount", "denial_date"}
    assert all({"row", "field", "value", "message"} <= set(e) for e in detail["errors"])
    with session_factory() as s:
        assert s.query(Run).count() == 0  # nothing persisted


def test_invalid_mapping_422(client, session_factory):
    setup_org(client, session_factory)
    r = upload_mapped(client, mapping={"claim_id": "Claim Number"})
    assert r.status_code == 422
    assert "required" in str(r.json()["detail"])
    r2 = client.post(
        "/api/v1/runs",
        files={"file": ("x.csv", io.BytesIO(MESSY_CSV.encode()), "text/csv")},
        data={"dry_run": "true", "mapping": "{not json"},
    )
    assert r2.status_code == 422


def test_save_mapping_upserts(client, session_factory):
    setup_org(client, session_factory)
    assert upload_mapped(client, save=True).status_code == 202
    listed = client.get("/api/v1/org/csv-mappings").json()
    assert len(listed) == 1
    assert upload_mapped(client, save=True).status_code == 202
    assert len(client.get("/api/v1/org/csv-mappings").json()) == 1  # deduped


def test_notes_recorded_as_audit_event(client, session_factory):
    setup_org(client, session_factory)
    headers = "Claim Number,Carrier,Reason Code,Total Charges,DOS,Check Date"
    row = "CLM-9003,Acme Ins,50,100.00,04/10/2026,05/01/2026"
    mapping = {
        "claim_id": "Claim Number", "payer": "Carrier",
        "carc_code": "Reason Code", "billed_amount": "Total Charges",
        "service_date": "DOS", "denial_date": "Check Date",
    }
    r = upload_mapped(client, csv_text=f"{headers}\n{row}\n", mapping=mapping)
    assert r.status_code == 202
    with session_factory() as s:
        ev = s.query(AuditEvent).filter_by(event_type="csv_import_notes").one()
        assert ev.details["count"] == 1
        assert "CO" in ev.details["notes"][0]["message"]


def test_canonical_path_unchanged(client, session_factory):
    from tests.conftest import SAMPLE_CSV
    setup_org(client, session_factory)
    r = client.post(
        "/api/v1/runs",
        files={"file": ("d.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")},
        data={"dry_run": "true"},
    )
    assert r.status_code == 202
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/server/test_upload_mapping.py -q`
Expected: FAIL (mapping field ignored → canonical parse errors).

- [ ] **Step 3: Implement**

In `server/api/runs.py` `create_run`, add params
`mapping: Optional[str] = Form(None), save_mapping: bool = Form(False)`
(import `Optional` if missing) and replace the parse block with:

```python
    text = (await file.read()).decode("utf-8", errors="replace")
    if mapping is not None:
        if suffix != ".csv":
            raise HTTPException(422, detail="mapping applies to CSV uploads only")
        try:
            mapping_obj = json.loads(mapping)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, detail=f"mapping is not valid JSON: {exc}")
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []
        rows = list(reader)
        try:
            mapped = apply_mapping(
                headers, rows, mapping_obj,
                default_appeal_days=ctx.org.default_appeal_days,
            )
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc))
        if mapped.errors:
            raise HTTPException(422, detail={
                "errors": [e.as_dict() for e in mapped.errors[:20]],
                "totalErrors": len(mapped.errors),
            })
        records = mapped.records
        import_notes = mapped.notes
        if save_mapping:
            upsert_csv_mapping(session, ctx.org.id, headers, mapping_obj)
    else:
        import_notes = []
        try:
            records = (
                parse_remittance_csv(text) if suffix == ".csv"
                else parse_remittance_json(text)
            )
        except RemittanceParseError as exc:
            raise HTTPException(422, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(422, detail=f"could not parse file: {exc}")
```

(new imports: `csv`, `io`, `json`; `from server.ingest import apply_mapping`;
`from server.api.org import upsert_csv_mapping`). Keep the empty/cap/live-key
checks after this block operating on `records` exactly as today. After the
run + claims are added (post-`session.flush()`), record notes:

```python
    if import_notes:
        from server.models import AuditEvent, utcnow
        session.add(AuditEvent(
            run_id=run.id, ts=utcnow(), event_type="csv_import_notes",
            details={"count": len(import_notes),
                     "notes": [n.as_dict() for n in import_notes[:20]]},
        ))
```

- [ ] **Step 4: Run to verify pass; commit**

Run: `.venv/bin/python -m pytest tests/ -q` — all pass.

```bash
git add server/api/runs.py tests/server/test_upload_mapping.py
git commit -m "ingest: mapped uploads — structured row errors, notes audit, mapping upsert"
```

---

### Task 4: Frontend — papaparse inspection, mapping panel, RunsScreen flow

**Files:**
- Modify: `frontend/package.json` (deps: `papaparse`, devDeps: `@types/papaparse`)
- Modify: `frontend/src/app/api.ts` (types + endpoints)
- Create: `frontend/src/app/MappingPanel.tsx`
- Modify: `frontend/src/app/RunsScreen.tsx` (staged-file flow)
- Test: `frontend/src/__tests__/mapping-panel.test.tsx`

**Interfaces:**
- `api.ts` additions:

```ts
export type CarcMapping = string | { group: string; code: string };
export type CsvMappingSpec = Record<string, CarcMapping>;
export interface SavedCsvMapping {
  id: string; name: string; headers: string[];
  mapping: CsvMappingSpec; lastUsedAt: string;
}
export interface RowError { row: number; field: string; value: string; message: string }
export const listCsvMappings = () => request<SavedCsvMapping[]>('/api/v1/org/csv-mappings');
export const deleteCsvMapping = (id: string) =>
  request<{ deleted: string }>(`/api/v1/org/csv-mappings/${id}`, { method: 'DELETE' });
export const patchOrg = (defaultAppealDays: number) =>
  request<OrgInfo>('/api/v1/org', json('PATCH', { defaultAppealDays }));
// OrgInfo gains defaultAppealDays: number
export function uploadRun(
  file: File, dryRun: boolean,
  opts?: { mapping?: CsvMappingSpec; saveMapping?: boolean },
): Promise<{ runId: string }>  // appends mapping/save_mapping form fields when opts.mapping present
```

  `ApiError` gains `detail?: unknown` so the 422 `{errors, totalErrors}` body
  is reachable (`request` stores the parsed detail object on the error).
- Pure helpers exported from `MappingPanel.tsx` for reuse/testing:
  `CANONICAL = [{key, label, required}...]` (nine fields),
  `suggestMapping(headers: string[]): CsvMappingSpec` (client-side mirror of
  the server synonym table — same seed list),
  `headerKey(headers: string[]): string` (sorted-lowercased-joined — used
  ONLY for client-side saved-mapping matching; server recomputes its own
  sha256 signature).
- `MappingPanel` props: `{ headers: string[]; sampleRows: Record<string,string>[]; defaultAppealDays: number; initial?: CsvMappingSpec; onConfirm: (mapping: CsvMappingSpec, remember: boolean) => void; onCancel: () => void }`.
- `RunsScreen` flow: file select → papaparse (`header: true, preview: 5, skipEmptyLines: true`) → canonical headers (all nine-or-subset match canonical names exactly) → old path; saved-mapping match (client compares normalized header sets against fetched `SavedCsvMapping.headers`) → badge "using saved mapping ✓ · Edit"; else panel. Upload errors: if `ApiError.detail` is an object with `errors`, render the row-error table.

- [ ] **Step 1: Install and write failing tests**

Run: `cd frontend && npm install papaparse && npm install -D @types/papaparse`

`frontend/src/__tests__/mapping-panel.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { MappingPanel, suggestMapping } from '../app/MappingPanel';

const HEADERS = ['Claim Number', 'Carrier', 'Adj Group', 'Reason Code',
  'Remark Codes', 'Denial Reason', 'Total Charges', 'DOS', 'Check Date'];
const SAMPLE = [{
  'Claim Number': 'CLM-9001', Carrier: 'Acme Ins', 'Adj Group': 'CO',
  'Reason Code': '50', 'Remark Codes': 'N115',
  'Denial Reason': 'Not medically necessary',
  'Total Charges': '$12,500.00', DOS: '04/10/2026', 'Check Date': '05/01/2026',
}];

test('suggestMapping mirrors the server synonym table', () => {
  const s = suggestMapping(HEADERS);
  expect(s.claim_id).toBe('Claim Number');
  expect(s.carc_code).toEqual({ group: 'Adj Group', code: 'Reason Code' });
  expect(s.denial_date).toBe('Check Date');
  expect(s.appeal_deadline).toBeUndefined();
});

test('panel pre-selects suggestions, shows samples and deadline note, confirms', async () => {
  const onConfirm = vi.fn();
  render(<MappingPanel headers={HEADERS} sampleRows={SAMPLE}
                       defaultAppealDays={90}
                       onConfirm={onConfirm} onCancel={() => {}} />);
  expect(screen.getByLabelText(/claim id/i)).toHaveValue('Claim Number');
  expect(screen.getByText('CLM-9001')).toBeInTheDocument();      // sample value
  expect(screen.getByText(/denial date \+ 90 days/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: /use this mapping/i }));
  expect(onConfirm).toHaveBeenCalledOnce();
  const [mapping, remember] = onConfirm.mock.calls[0];
  expect(mapping.claim_id).toBe('Claim Number');
  expect(remember).toBe(true);                                    // default on
});

test('missing required selection blocks confirm', async () => {
  const onConfirm = vi.fn();
  render(<MappingPanel headers={HEADERS} sampleRows={SAMPLE}
                       defaultAppealDays={90}
                       onConfirm={onConfirm} onCancel={() => {}} />);
  await userEvent.selectOptions(screen.getByLabelText(/payer/i), '');
  await userEvent.click(screen.getByRole('button', { name: /use this mapping/i }));
  expect(onConfirm).not.toHaveBeenCalled();
  expect(screen.getByText(/payer is required/i)).toBeInTheDocument();
});

test('carc toggle switches between single and group+code', async () => {
  render(<MappingPanel headers={HEADERS} sampleRows={SAMPLE}
                       defaultAppealDays={90}
                       onConfirm={() => {}} onCancel={() => {}} />);
  // auto-detected two-column mode: both selects present
  expect(screen.getByLabelText(/carc group column/i)).toHaveValue('Adj Group');
  await userEvent.click(screen.getByRole('button', { name: /single column/i }));
  expect(screen.queryByLabelText(/carc group column/i)).not.toBeInTheDocument();
});
```

Run: `cd frontend && npx vitest run src/__tests__/mapping-panel.test.tsx`
Expected: FAIL (module missing).

- [ ] **Step 2: Implement**

`frontend/src/app/api.ts` — apply the Interfaces block above. Concretely:
`ApiError` becomes:

```ts
export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}
```

and `request` passes the parsed `detail` through:

```ts
  if (!res.ok) {
    let message = res.statusText;
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
      message = typeof detail === 'string' ? detail : message;
    } catch { /* non-json */ }
    throw new ApiError(res.status, message, detail);
  }
```

`uploadRun` gains the optional third arg and appends
`body.append('mapping', JSON.stringify(opts.mapping))` and
`body.append('save_mapping', String(opts.saveMapping ?? false))` when
`opts?.mapping` is present.

`frontend/src/app/MappingPanel.tsx`:

```tsx
import { useMemo, useState } from 'react';
import type { CarcMapping, CsvMappingSpec } from './api';

export const CANONICAL: { key: string; label: string; required: boolean }[] = [
  { key: 'claim_id', label: 'Claim ID', required: true },
  { key: 'payer', label: 'Payer', required: true },
  { key: 'carc_code', label: 'CARC code', required: true },
  { key: 'rarc_codes', label: 'RARC codes', required: false },
  { key: 'denial_reason_text', label: 'Denial reason text', required: false },
  { key: 'billed_amount', label: 'Billed amount', required: true },
  { key: 'service_date', label: 'Service date', required: true },
  { key: 'denial_date', label: 'Denial date', required: true },
  { key: 'appeal_deadline', label: 'Appeal deadline', required: false },
];

const SYNONYMS: Record<string, string[]> = {
  claim_id: ['claim id', 'claim number', 'claim no', 'claim', 'pcn',
    'patient control number', 'patient control no'],
  payer: ['payer', 'payer name', 'carrier', 'insurance', 'plan'],
  carc_code: ['carc', 'carc code', 'reason code', 'adj reason code',
    'adjustment reason code', 'denial code'],
  rarc_codes: ['rarc', 'rarc code', 'rarc codes', 'remark code', 'remark codes'],
  denial_reason_text: ['denial reason', 'reason', 'description', 'remark'],
  billed_amount: ['billed', 'billed amount', 'charge', 'charges',
    'charge amount', 'total charges'],
  service_date: ['service date', 'dos', 'date of service', 'from date'],
  denial_date: ['denial date', 'denied date', 'remit date',
    'remittance date', 'check date'],
  appeal_deadline: ['appeal deadline', 'appeal by', 'deadline', 'file by'],
};
const GROUP_SYNONYMS = ['group code', 'adj group', 'adjustment group', 'carc group'];

const norm = (h: string) =>
  h.toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();

export function suggestMapping(headers: string[]): CsvMappingSpec {
  const byNorm = new Map(headers.map((h) => [norm(h), h]));
  const out: CsvMappingSpec = {};
  for (const { key } of CANONICAL) {
    for (const cand of [key, ...(SYNONYMS[key] ?? [])].map(norm)) {
      const hit = byNorm.get(cand);
      if (hit) { out[key] = hit; break; }
    }
  }
  const group = GROUP_SYNONYMS.map(norm).map((g) => byNorm.get(g)).find(Boolean);
  if (group && typeof out.carc_code === 'string') {
    out.carc_code = { group, code: out.carc_code };
  }
  return out;
}

export const headerKey = (headers: string[]) =>
  headers.map(norm).sort().join('\n');

interface Props {
  headers: string[];
  sampleRows: Record<string, string>[];
  defaultAppealDays: number;
  initial?: CsvMappingSpec;
  onConfirm: (mapping: CsvMappingSpec, remember: boolean) => void;
  onCancel: () => void;
}

const selectStyle = {
  font: 'inherit', fontSize: 12.5, padding: '5px 8px',
  border: '1px solid #DBD8D1', borderRadius: 6,
} as const;

export function MappingPanel(p: Props) {
  const suggestion = useMemo(
    () => p.initial ?? suggestMapping(p.headers), [p.headers, p.initial],
  );
  const initialCarc = suggestion.carc_code as CarcMapping | undefined;
  const [twoColCarc, setTwoColCarc] = useState(
    typeof initialCarc === 'object' && initialCarc !== null,
  );
  const [sel, setSel] = useState<Record<string, string>>(() => {
    const s: Record<string, string> = {};
    for (const { key } of CANONICAL) {
      const v = suggestion[key];
      if (typeof v === 'string') s[key] = v;
    }
    if (typeof initialCarc === 'object' && initialCarc !== null) {
      s.carc_code = initialCarc.code;
      s.carc_group = initialCarc.group;
    }
    return s;
  });
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState('');

  const sample = (header: string | undefined) =>
    header ? (p.sampleRows[0]?.[header] ?? '') : '';

  const confirm = () => {
    for (const { key, label, required } of CANONICAL) {
      if (required && key !== 'carc_code' && !sel[key]) {
        setError(`${label} is required`);
        return;
      }
    }
    if (!sel.carc_code || (twoColCarc && !sel.carc_group)) {
      setError('CARC code is required');
      return;
    }
    const mapping: CsvMappingSpec = {};
    for (const { key } of CANONICAL) {
      if (key === 'carc_code') continue;
      if (sel[key]) mapping[key] = sel[key];
    }
    mapping.carc_code = twoColCarc
      ? { group: sel.carc_group, code: sel.carc_code }
      : sel.carc_code;
    p.onConfirm(mapping, remember);
  };

  const fieldRow = (key: string, label: string, required: boolean) => (
    <div key={key} className="audit-row" style={{ gap: 12, alignItems: 'center' }}>
      <label style={{ flex: '0 0 180px', fontSize: 12.5, color: 'var(--ink-2)' }}>
        {label}{required && <span style={{ color: 'var(--red-fg)' }}> *</span>}
        <select
          aria-label={label}
          value={sel[key] ?? ''}
          onChange={(e) => setSel((s) => ({ ...s, [key]: e.target.value }))}
          style={{ ...selectStyle, display: 'block', marginTop: 3, width: '100%' }}
        >
          <option value="">(not present)</option>
          {p.headers.map((h) => <option key={h} value={h}>{h}</option>)}
        </select>
      </label>
      <span style={{ fontFamily: 'var(--mono)', fontSize: 11.5,
                     color: 'var(--mut)', overflow: 'hidden',
                     textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {sample(sel[key])}
      </span>
    </div>
  );

  return (
    <div className="panel" style={{ marginTop: 12 }}>
      <div className="panel-head">
        <div className="panel-title">Map your columns</div>
        <div className="panel-sub">{p.headers.length} columns detected</div>
      </div>
      <div style={{ marginTop: 8 }}>
        {CANONICAL.filter((f) => f.key !== 'carc_code' && f.key !== 'appeal_deadline')
          .map((f) => fieldRow(f.key, f.label, f.required))}

        <div className="audit-row" style={{ gap: 12, alignItems: 'center' }}>
          <label style={{ flex: '0 0 180px', fontSize: 12.5, color: 'var(--ink-2)' }}>
            CARC code<span style={{ color: 'var(--red-fg)' }}> *</span>
            <select aria-label="CARC code" value={sel.carc_code ?? ''}
                    onChange={(e) => setSel((s) => ({ ...s, carc_code: e.target.value }))}
                    style={{ ...selectStyle, display: 'block', marginTop: 3, width: '100%' }}>
              <option value="">(not present)</option>
              {p.headers.map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
          </label>
          {twoColCarc && (
            <label style={{ flex: '0 0 180px', fontSize: 12.5, color: 'var(--ink-2)' }}>
              CARC group column
              <select aria-label="CARC group column" value={sel.carc_group ?? ''}
                      onChange={(e) => setSel((s) => ({ ...s, carc_group: e.target.value }))}
                      style={{ ...selectStyle, display: 'block', marginTop: 3, width: '100%' }}>
                <option value="">(not present)</option>
                {p.headers.map((h) => <option key={h} value={h}>{h}</option>)}
              </select>
            </label>
          )}
          <button type="button" className="btn"
                  onClick={() => setTwoColCarc((v) => !v)}>
            {twoColCarc ? 'Single column' : 'Group + code columns'}
          </button>
        </div>

        {fieldRow('appeal_deadline', 'Appeal deadline', false)}
        {!sel.appeal_deadline && (
          <div className="sm-note" style={{ marginTop: 4 }}>
            No deadline column — appeal deadline will be denial date + {p.defaultAppealDays} days
            (change in Org Settings).
          </div>
        )}
      </div>
      {error && <div style={{ fontSize: 12.5, color: 'var(--red-fg)', marginTop: 8 }}>{error}</div>}
      <div style={{ display: 'flex', gap: 10, marginTop: 12, alignItems: 'center' }}>
        <label style={{ fontSize: 12.5, color: 'var(--ink-2)', display: 'flex', gap: 6 }}>
          <input type="checkbox" checked={remember}
                 onChange={(e) => setRemember(e.target.checked)} />
          Remember this mapping
        </label>
        <div className="spacer" />
        <button type="button" className="btn" onClick={p.onCancel}>Cancel</button>
        <button type="button" className="btn-primary" onClick={confirm}>
          Use this mapping
        </button>
      </div>
    </div>
  );
}
```

`frontend/src/app/RunsScreen.tsx` rework of the upload form:
- New state: `staged: { file: File; headers: string[]; samples: Record<string,string>[] } | null`,
  `mappingNeeded: boolean`, `activeMapping: CsvMappingSpec | null`,
  `usingSaved: boolean`, `rowErrors: RowError[] | null`, `totalErrors: number`,
  `savedMappings: SavedCsvMapping[]` (fetched on mount alongside runs),
  `orgInfo: OrgInfo | null` (fetched on mount for `defaultAppealDays`).
- On file input change: `Papa.parse(file, { header: true, preview: 5, skipEmptyLines: true, complete })`;
  in `complete`, headers = `meta.fields ?? []`; if every canonical REQUIRED
  name is literally among the headers → `staged` with `mappingNeeded=false`;
  else look up `headerKey(headers)` among
  `savedMappings.map(m => headerKey(m.headers))` → hit: `activeMapping = hit.mapping`,
  `usingSaved=true`; miss: `mappingNeeded=true` (renders `MappingPanel`).
- Submit: `uploadRun(staged.file, dryRun, activeMapping ? { mapping: activeMapping, saveMapping } : undefined)`;
  on `ApiError` with object detail containing `errors`, set
  `rowErrors/totalErrors` and render:

```tsx
        {rowErrors && (
          <div className="panel" style={{ marginTop: 10 }}>
            <div className="panel-title" style={{ color: 'var(--red-fg)' }}>
              {totalErrors} row error{totalErrors === 1 ? '' : 's'} — nothing was imported
            </div>
            <div style={{ marginTop: 6 }}>
              {rowErrors.map((e, i) => (
                <div key={i} className="audit-row" style={{ gap: 10 }}>
                  <span className="pill c-red">row {e.row + 1}</span>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 11.5 }}>{e.field}</span>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 11.5,
                                 color: 'var(--mut)' }}>{e.value}</span>
                  <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>{e.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}
```

- Saved-mapping badge next to the file input when `usingSaved`:
  `<span className="pill c-green">using saved mapping ✓</span>
   <button type="button" className="btn" onClick={() => setMappingNeeded(true)}>Edit</button>`
  (Edit opens `MappingPanel` with `initial={activeMapping}`).
- `MappingPanel.onConfirm` sets `activeMapping`, `saveMapping=remember`,
  closes the panel; upload proceeds on the existing submit button.

- [ ] **Step 3: Run to verify pass; commit**

Run: `cd frontend && npm test && npm run build:app && npm run build:template`
Expected: all green (62 + 4 new = 66); template bytes UNCHANGED (`git status`
— mapping code lives only in `src/app/`; do not commit the template).

```bash
git add frontend/package.json frontend/package-lock.json frontend/src
git commit -m "ingest: mapping panel, saved-mapping auto-apply, row-error table"
```

---

### Task 5: Frontend — Org Settings: default appeal window + saved mappings

**Files:**
- Modify: `frontend/src/app/OrgSettingsScreen.tsx`
- Test: extend `frontend/src/__tests__/org-settings.test.tsx`

**Interfaces:**
- Consumes `patchOrg`, `listCsvMappings`, `deleteCsvMapping`, and
  `OrgInfo.defaultAppealDays` from Task 4.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/__tests__/org-settings.test.tsx` (extend `wire()`'s
base map with `'/api/v1/org'` gaining `defaultAppealDays: 90` and
`'/api/v1/org/csv-mappings': [{ id: 'm1', name: 'Mapping (9 columns)', headers: ['Claim Number'], mapping: {}, lastUsedAt: '2026-07-11' }]`,
plus PATCH/DELETE handlers):

```tsx
test('default appeal window edits via PATCH', async () => {
  wire();
  render(<OrgSettingsScreen onBack={() => {}} />);
  const input = await screen.findByLabelText(/appeal window/i);
  expect(input).toHaveValue(90);
  await userEvent.clear(input);
  await userEvent.type(input, '120');
  await userEvent.click(screen.getByRole('button', { name: /save window/i }));
  const patch = fetchMock.mock.calls.find(
    ([url, init]) => url === '/api/v1/org' && (init as RequestInit)?.method === 'PATCH');
  expect(patch).toBeTruthy();
  expect(JSON.parse((patch![1] as RequestInit).body as string))
    .toEqual({ defaultAppealDays: 120 });
});

test('saved mappings list renders and deletes', async () => {
  wire();
  render(<OrgSettingsScreen onBack={() => {}} />);
  expect(await screen.findByText('Mapping (9 columns)')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: /delete mapping/i }));
  const del = fetchMock.mock.calls.find(
    ([url, init]) => url === '/api/v1/org/csv-mappings/m1'
      && (init as RequestInit)?.method === 'DELETE');
  expect(del).toBeTruthy();
});
```

Run: `cd frontend && npx vitest run src/__tests__/org-settings.test.tsx` — FAIL.

- [ ] **Step 2: Implement**

In `OrgSettingsScreen.tsx`: fetch `listCsvMappings()` in `refresh`; add state
`const [days, setDays] = useState<number | ''>('');` seeded from
`org.defaultAppealDays` when org loads. Add two panels after the API key card:

```tsx
      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-title">Default appeal window</div>
        <div className="sm-note" style={{ marginTop: 6 }}>
          When an uploaded file has no appeal-deadline column, deadlines are
          computed as denial date + this many days.
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'flex-end' }}>
          <label style={{ fontSize: 12.5, color: 'var(--mut)' }}>
            Appeal window (days)
            <input type="number" min={1} max={365} value={days}
                   onChange={(e) => setDays(e.target.value === '' ? '' : Number(e.target.value))}
                   style={{ display: 'block', marginTop: 4, padding: '7px 10px', width: 120,
                            border: '1px solid #DBD8D1', borderRadius: 8, font: 'inherit' }} />
          </label>
          <button type="button" className="btn-primary"
                  onClick={() => typeof days === 'number' && act(patchOrg(days))}>
            Save window
          </button>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-title">Saved CSV mappings</div>
        <div style={{ marginTop: 8 }}>
          {mappings.length === 0 && (
            <div className="sm-note">No saved mappings yet — they're created
            when you map an upload and tick "Remember this mapping".</div>
          )}
          {mappings.map((m) => (
            <div key={m.id} className="audit-row" style={{ gap: 12 }}>
              <div style={{ flex: 1, fontSize: 13 }}>{m.name}</div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 11.5, color: 'var(--mut)' }}>
                {m.headers.length} columns · last used {m.lastUsedAt.slice(0, 10)}
              </div>
              <button type="button" className="btn" aria-label="delete mapping"
                      onClick={() => act(deleteCsvMapping(m.id))}>
                Delete
              </button>
            </div>
          ))}
        </div>
      </div>
```

(with `mappings` state from `listCsvMappings`, and `setDays(org.defaultAppealDays)`
inside the `getOrg().then(...)` chain.)

- [ ] **Step 3: Run to verify pass; commit**

Run: `cd frontend && npm test && npm run build:app` — green (66 + 2 = 68).

```bash
git add frontend/src
git commit -m "ingest: org settings — default appeal window + saved mappings management"
```

---

### Task 6: E2E messy-CSV flow + full verification

**Files:**
- Modify: `frontend/e2e/server.spec.ts` (new spec)
- Test: full suites on the rebuilt stack

**Interfaces:** consumes the compose stack rebuilt with Tasks 1–5.

- [ ] **Step 1: Add the E2E**

Append to `frontend/e2e/server.spec.ts`:

```ts
const MESSY_CSV = `Claim Number,Carrier,Adj Group,Reason Code,Remark Codes,Denial Reason,Total Charges,DOS,Check Date
CLM-MAP-${Date.now()}-1,Acme Ins,CO,50,N115,Not medically necessary,"$12,500.00",04/10/2026,05/01/2026
CLM-MAP-${Date.now()}-2,Acme Ins,PR,204,,Plan exclusion,430.25,03/02/2026,04/15/2026
`;

test('messy CSV maps, imports with deadline rule, and remembers the mapping', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.getByLabel(/email/i).fill(process.env.E2E_EMAIL ?? 'admin@example.com');
  await page.getByLabel(/password/i).fill(process.env.E2E_PASSWORD ?? 'change-me-locally');
  await page.getByRole('button', { name: /log in/i }).click();

  const upload = async () => {
    await page.setInputFiles('input[type=file]', {
      name: 'waystar-export.csv', mimeType: 'text/csv',
      buffer: Buffer.from(MESSY_CSV),
    });
  };

  // first upload: mapping panel appears with suggestions pre-filled
  await upload();
  await expect(page.getByText('Map your columns')).toBeVisible();
  await expect(page.getByLabel('Claim ID')).toHaveValue('Claim Number');
  await expect(page.getByText(/denial date \+ \d+ days/)).toBeVisible();
  await page.getByRole('button', { name: /use this mapping/i }).click();
  await page.getByRole('button', { name: /upload/i }).click();

  const row = page.locator('.audit-row', { hasText: 'waystar-export.csv' }).first();
  await expect(row.getByText('completed')).toBeVisible({ timeout: 90_000 });

  // second upload of the same shape: saved mapping badge, no panel
  await upload();
  await expect(page.getByText(/using saved mapping/i)).toBeVisible();
  await expect(page.getByText('Map your columns')).not.toBeVisible();
});
```

(Note: `Date.now()` in claim ids keeps reruns unique against the persistent
dev DB; the saved-mapping match is header-based so reruns still hit it.)

- [ ] **Step 2: Rebuild and run everything**

```bash
docker compose up -d --build web worker
.venv/bin/python -m pytest tests/ -q
cd frontend && npm test && npm run e2e
```

Expected: pytest all green (Task 1–3 additions included), vitest 68, e2e 3
passed. Verify migration 0004 on the compose db:
`docker compose exec -T db psql -U overturn -c "\d csv_mappings"`.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e
git commit -m "ingest: e2e — messy clearinghouse CSV through mapping to completed run"
```

---

## Self-Review Notes

- Spec coverage: engine incl. all normalizers/synonyms/signature (T1),
  migration + org setting + mapping persistence + org API (T2), upload
  integration with structured 422 + notes audit + upsert (T3), papaparse
  inspection + panel + saved-badge + error table (T4), Org Settings cards
  (T5), E2E + verification (T6). Out-of-scope items have no tasks.
- Type consistency: `CsvMappingSpec`/`CarcMapping` (T4) match the server's
  mapping JSON shape (T1/T3); `RowError` keys identical server/client;
  `upsert_csv_mapping(session, org_id, headers, mapping)` used in T2 tests
  and T3; `OrgInfo.defaultAppealDays` produced T2, consumed T4/T5.
- The client `suggestMapping`/`headerKey` are deliberate mirrors of server
  logic (documented in both files); server remains authoritative
  (`validate_mapping` + its own sha256 signature).
- Canonical-path regression test included (T3) per the byte-for-byte
  constraint; template untouched (mapping UI is `src/app/`-only, T4 verifies).
