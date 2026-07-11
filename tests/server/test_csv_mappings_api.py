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
