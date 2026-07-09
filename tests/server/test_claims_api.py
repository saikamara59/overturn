import io
import zipfile

from overturn.dryrun import DryRunClient
from server.models import Claim
from server.worker import claim_next_run, process_run
from tests.server.conftest import login
from tests.server.test_runs_api import upload


def drafted_run(client, session_factory):
    login(client)
    run_id = upload(client).json()["runId"]
    with session_factory() as s:
        claim_next_run(s)
    import uuid
    process_run(uuid.UUID(run_id), session_factory=session_factory,
                client=DryRunClient())
    return run_id


def test_worklist_payload_shape(client, session_factory):
    run_id = drafted_run(client, session_factory)
    data = client.get(f"/api/v1/runs/{run_id}/claims").json()
    assert data["summary"] == {"processed": 3, "drafts": 3, "failed": 0}
    assert data["totalBilled"] == 21230.25
    assert data["model"]  # recorded by DbInvocationTracker
    ids = [c["id"] for c in data["claims"]]
    assert ids[0] == "CLM-001"          # overdue first (deadline urgency)
    entry = data["claims"][0]
    for key in ("dbId", "payer", "carc", "carcText", "rarcs", "billed", "dos",
                "denialDate", "deadline", "days", "status", "denialText",
                "letter", "refined", "rule", "error"):
        assert key in entry, key
    assert entry["status"] == "Draft Ready"
    assert isinstance(data["audit"], list) and len(data["audit"]) > 0
    for e in data["audit"]:
        assert set(e) == {"time", "type", "detail"}


def test_audit_endpoint_maps_events(client, session_factory):
    run_id = drafted_run(client, session_factory)
    events = client.get(f"/api/v1/runs/{run_id}/audit").json()
    types = {e["type"] for e in events}
    assert "agent_invocation" in types and "phi_redacted" in types
    assert all(set(e) == {"time", "type", "detail"} for e in events)


def test_patch_letter_edit_and_revert(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entry = client.get(f"/api/v1/runs/{run_id}/claims").json()["claims"][0]
    db_id = entry["dbId"]

    r = client.patch(f"/api/v1/claims/{db_id}", json={"letter": "edited text"})
    assert r.status_code == 200 and r.json()["letter"] == "edited text"

    r = client.patch(f"/api/v1/claims/{db_id}", json={"letter": None})
    assert r.status_code == 200
    assert r.json()["letter"] == entry["letter"]  # restored original


def test_patch_approve_persists(client, session_factory):
    run_id = drafted_run(client, session_factory)
    db_id = client.get(f"/api/v1/runs/{run_id}/claims").json()["claims"][0]["dbId"]
    r = client.patch(f"/api/v1/claims/{db_id}", json={"status": "submitted"})
    assert r.status_code == 200 and r.json()["status"] == "Submitted"
    # persists across a fresh read
    data = client.get(f"/api/v1/runs/{run_id}/claims").json()
    assert data["claims"][0]["status"] == "Submitted"


def test_patch_rules(client, session_factory):
    run_id = drafted_run(client, session_factory)
    db_id = client.get(f"/api/v1/runs/{run_id}/claims").json()["claims"][0]["dbId"]
    assert client.patch(f"/api/v1/claims/{db_id}", json={"status": "won"}).status_code == 422
    with session_factory() as s:
        c = s.query(Claim).filter_by(id=db_id).one()
        c.status = "queued"
        s.commit()
    assert client.patch(f"/api/v1/claims/{db_id}", json={"status": "submitted"}).status_code == 409


def test_letter_and_zip_exports(client, session_factory):
    run_id = drafted_run(client, session_factory)
    db_id = client.get(f"/api/v1/runs/{run_id}/claims").json()["claims"][0]["dbId"]
    md = client.get(f"/api/v1/claims/{db_id}/letter.md")
    assert md.status_code == 200
    assert md.text.startswith("# Appeal — claim CLM-001")
    assert "## Refined recommendation" in md.text

    z = client.get(f"/api/v1/runs/{run_id}/letters.zip")
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert sorted(names) == [
        "CLM-001-appeal.md", "CLM-002-appeal.md", "CLM-003-appeal.md"
    ]
