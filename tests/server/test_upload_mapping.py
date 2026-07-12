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


def test_non_object_mapping_422(client, session_factory):
    setup_org(client, session_factory)
    for raw in ('null', '[]', '"hello"'):
        r = client.post(
            "/api/v1/runs",
            files={"file": ("x.csv", io.BytesIO(MESSY_CSV.encode()), "text/csv")},
            data={"dry_run": "true", "mapping": raw},
        )
        assert r.status_code == 422, raw
        assert "mapping" in str(r.json()["detail"]), raw


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
