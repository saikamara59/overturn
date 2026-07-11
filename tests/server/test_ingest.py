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
