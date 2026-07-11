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
