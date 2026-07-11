import io
import uuid
import zipfile

from server.models import AuditEvent, Claim, Run
from tests.server.conftest import login
from tests.server.test_claims_api import drafted_run


def claims_of(client, run_id):
    return client.get(f"/api/v1/runs/{run_id}/claims").json()["claims"]


def test_dismiss_from_draft_ready_with_reason(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entry = claims_of(client, run_id)[0]

    r = client.patch(f"/api/v1/claims/{entry['dbId']}",
                     json={"status": "dismissed", "dismissReason": "too_small"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "Dismissed"
    assert body["dismissReason"] == "too_small"

    data = client.get(f"/api/v1/runs/{run_id}/claims").json()
    assert data["summary"]["dismissed"] == 1
    # pipeline counters untouched
    assert data["summary"]["drafts"] == 3

    with session_factory() as s:
        ev = s.query(AuditEvent).filter_by(event_type="claim_dismissed").one()
        assert ev.details["claim_id"] == entry["id"]
        assert ev.details["reason"] == "too_small"


def test_dismiss_without_reason_and_from_failed(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    with session_factory() as s:
        c = s.get(Claim, uuid.UUID(entries[1]["dbId"]))
        c.status = "failed"
        c.letter = None
        s.commit()

    ok = client.patch(f"/api/v1/claims/{entries[0]['dbId']}",
                      json={"status": "dismissed"})
    assert ok.status_code == 200 and ok.json()["dismissReason"] is None
    ok2 = client.patch(f"/api/v1/claims/{entries[1]['dbId']}",
                       json={"status": "dismissed"})
    assert ok2.status_code == 200


def test_dismiss_transition_guards(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    db_id = entries[0]["dbId"]

    # invalid reason
    assert client.patch(f"/api/v1/claims/{db_id}",
                        json={"status": "dismissed", "dismissReason": "meh"}
                        ).status_code == 422
    # submitted claims cannot be dismissed
    client.patch(f"/api/v1/claims/{db_id}", json={"status": "submitted"})
    assert client.patch(f"/api/v1/claims/{db_id}",
                        json={"status": "dismissed"}).status_code == 409
    # queued claims cannot be dismissed
    other = entries[1]["dbId"]
    with session_factory() as s:
        s.get(Claim, uuid.UUID(other)).status = "queued"
        s.commit()
    assert client.patch(f"/api/v1/claims/{other}",
                        json={"status": "dismissed"}).status_code == 409


def test_restore_paths_and_guards(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    with_letter, without = entries[0]["dbId"], entries[1]["dbId"]
    with session_factory() as s:
        c = s.get(Claim, uuid.UUID(without))
        c.status = "failed"
        c.letter = None
        s.commit()
    client.patch(f"/api/v1/claims/{with_letter}", json={"status": "dismissed"})
    client.patch(f"/api/v1/claims/{without}", json={"status": "dismissed"})

    # restore not allowed on non-dismissed
    active = entries[2]["dbId"]
    assert client.patch(f"/api/v1/claims/{active}",
                        json={"status": "restored"}).status_code == 409
    # letter edit blocked while dismissed
    assert client.patch(f"/api/v1/claims/{with_letter}",
                        json={"letter": "nope"}).status_code == 409

    r1 = client.patch(f"/api/v1/claims/{with_letter}", json={"status": "restored"})
    assert r1.status_code == 200 and r1.json()["status"] == "Draft Ready"
    assert r1.json()["dismissReason"] is None
    r2 = client.patch(f"/api/v1/claims/{without}", json={"status": "restored"})
    assert r2.status_code == 200 and r2.json()["status"] == "Failed"

    with session_factory() as s:
        evs = s.query(AuditEvent).filter_by(event_type="claim_restored").all()
        assert {e.details["restored_to"] for e in evs} == {"draft_ready", "failed"}


def test_retry_never_requeues_dismissed(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    client.patch(f"/api/v1/claims/{entries[0]['dbId']}",
                 json={"status": "dismissed"})
    with session_factory() as s:
        s.get(Claim, uuid.UUID(entries[1]["dbId"])).status = "failed"
        s.commit()

    r = client.post(f"/api/v1/runs/{run_id}/retry")
    assert r.json() == {"requeued": 1}  # only the failed one, not the dismissed
    with session_factory() as s:
        assert s.get(Claim, uuid.UUID(entries[0]["dbId"])).status == "dismissed"


def test_letters_zip_excludes_dismissed(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    dismissed_id, dismissed_claim_id = entries[0]["dbId"], entries[0]["id"]
    other_claim_ids = [e["id"] for e in entries[1:]]

    r = client.patch(f"/api/v1/claims/{dismissed_id}", json={"status": "dismissed"})
    assert r.status_code == 200

    z = client.get(f"/api/v1/runs/{run_id}/letters.zip")
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert f"{dismissed_claim_id}-appeal.md" not in names
    for cid in other_claim_ids:
        assert f"{cid}-appeal.md" in names
