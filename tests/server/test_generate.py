"""POST /runs/{id}/generate — requeue selected claims for (re)generation."""
import uuid

from overturn.dryrun import DryRunClient
from server.models import AuditEvent, Claim, Org, Run
from server.worker import claim_next_run, process_run
from tests.server.conftest import login_as, make_org, make_user
from tests.server.test_claims_api import drafted_run


def claims_of(client, run_id):
    return client.get(f"/api/v1/runs/{run_id}/claims").json()["claims"]


def _fail_claim(session_factory, db_id):
    with session_factory() as s:
        c = s.get(Claim, uuid.UUID(db_id))
        c.status = "failed"
        c.error = "boom"
        c.letter = None
        run = s.get(Run, c.run_id)
        run.drafted -= 1
        run.failed_records += 1
        s.commit()


def test_generate_requeues_and_recomputes(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    _fail_claim(session_factory, entries[1]["dbId"])

    r = client.post(f"/api/v1/runs/{run_id}/generate",
                    json={"claimIds": [entries[0]["dbId"], entries[1]["dbId"]]})
    assert r.status_code == 200, r.text
    assert r.json() == {"queued": 2, "skipped": 0}

    with session_factory() as s:
        run = s.get(Run, uuid.UUID(run_id))
        assert run.status == "queued"
        assert run.finished_at is None and run.error is None
        assert run.drafted == 1          # only the untouched third claim
        assert run.failed_records == 0   # the failed one is queued again
        for db_id in (entries[0]["dbId"], entries[1]["dbId"]):
            c = s.get(Claim, uuid.UUID(db_id))
            assert c.status == "queued" and c.error is None
        ev = s.query(AuditEvent).filter_by(
            event_type="regeneration_requested").one()
        assert ev.details["count"] == 2
        assert len(ev.details["claim_ids"]) == 2


def test_generate_then_worker_redrafts(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    with session_factory() as s:  # simulate a user edit that regen replaces
        c = s.get(Claim, uuid.UUID(entries[0]["dbId"]))
        c.letter = "EDITED BY HAND"
        s.commit()
    _fail_claim(session_factory, entries[1]["dbId"])

    r = client.post(f"/api/v1/runs/{run_id}/generate",
                    json={"claimIds": [entries[0]["dbId"], entries[1]["dbId"]]})
    assert r.status_code == 200

    with session_factory() as s:
        assert claim_next_run(s) == uuid.UUID(run_id)
    process_run(uuid.UUID(run_id), session_factory=session_factory,
                client=DryRunClient())

    with session_factory() as s:
        run = s.get(Run, uuid.UUID(run_id))
        assert run.status == "completed"
        assert run.drafted == 3 and run.failed_records == 0
        redrafted = s.get(Claim, uuid.UUID(entries[0]["dbId"]))
        assert redrafted.status == "draft_ready"
        assert redrafted.letter and redrafted.letter != "EDITED BY HAND"
        assert redrafted.letter == redrafted.letter_original
        revived = s.get(Claim, uuid.UUID(entries[1]["dbId"]))
        assert revived.status == "draft_ready" and revived.letter


def test_generate_skips_ineligible_statuses(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    client.patch(f"/api/v1/claims/{entries[0]['dbId']}", json={"status": "submitted"})
    client.patch(f"/api/v1/claims/{entries[1]['dbId']}", json={"status": "dismissed"})

    r = client.post(f"/api/v1/runs/{run_id}/generate",
                    json={"claimIds": [e["dbId"] for e in entries]})
    assert r.status_code == 200
    assert r.json() == {"queued": 1, "skipped": 2}
    with session_factory() as s:  # only queued work requeues the run
        assert s.get(Run, uuid.UUID(run_id)).status == "queued"


def test_generate_validation_and_guards(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)

    assert client.post(f"/api/v1/runs/{run_id}/generate",
                       json={"claimIds": []}).status_code == 422
    assert client.post(f"/api/v1/runs/{run_id}/generate",
                       json={"claimIds": ["not-a-uuid"]}).status_code == 422
    assert client.post(f"/api/v1/runs/{run_id}/generate",
                       json={"claimIds": [str(uuid.uuid4())]}).status_code == 422

    # live run without an org key is rejected up front
    with session_factory() as s:
        s.get(Run, uuid.UUID(run_id)).dry_run = False
        s.commit()
    r = client.post(f"/api/v1/runs/{run_id}/generate",
                    json={"claimIds": [entries[0]["dbId"]]})
    assert r.status_code == 422 and "API key" in r.json()["detail"]
    with session_factory() as s:
        s.get(Run, uuid.UUID(run_id)).dry_run = True
        s.commit()

    # demo run is read-only
    with session_factory() as s:
        s.get(Run, uuid.UUID(run_id)).is_demo = True
        s.commit()
    assert client.post(f"/api/v1/runs/{run_id}/generate",
                       json={"claimIds": [entries[0]["dbId"]]}).status_code == 409


def test_generate_cross_org_is_404(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entries = claims_of(client, run_id)
    other = make_org(session_factory, name="Rival RCM")
    make_user(session_factory, "rival@example.com", "hunter2hunter2",
              org=other, role="admin")
    login_as(client, "rival@example.com", "hunter2hunter2")
    r = client.post(f"/api/v1/runs/{run_id}/generate",
                    json={"claimIds": [entries[0]["dbId"]]})
    assert r.status_code == 404
