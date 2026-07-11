"""THE critical Phase 2 suite: cross-org access must always 404."""
import uuid

from overturn.dryrun import DryRunClient
from server.worker import claim_next_run, process_run
from tests.server.conftest import login_as, make_org, make_user
from tests.server.test_runs_api import upload


def two_orgs_with_runs(client, session_factory):
    org_a = make_org(session_factory, name="Org A")
    org_b = make_org(session_factory, name="Org B")
    make_user(session_factory, "a@a.a", "pw12345678", org=org_a)
    make_user(session_factory, "b@b.b", "pw12345678", org=org_b)

    login_as(client, "a@a.a", "pw12345678")
    run_a = upload(client).json()["runId"]
    with session_factory() as s:
        claim_next_run(s)
    process_run(uuid.UUID(run_a), session_factory=session_factory,
                client=DryRunClient())
    claims_a = client.get(f"/api/v1/runs/{run_a}/claims").json()["claims"]

    login_as(client, "b@b.b", "pw12345678")
    return run_a, claims_a


def test_foreign_run_is_404_everywhere(client, session_factory):
    run_a, claims_a = two_orgs_with_runs(client, session_factory)
    assert client.get(f"/api/v1/runs/{run_a}").status_code == 404
    assert client.get(f"/api/v1/runs/{run_a}/claims").status_code == 404
    assert client.get(f"/api/v1/runs/{run_a}/audit").status_code == 404
    assert client.get(f"/api/v1/runs/{run_a}/letters.zip").status_code == 404
    assert client.post(f"/api/v1/runs/{run_a}/retry").status_code == 404


def test_foreign_claim_is_404_everywhere(client, session_factory):
    _, claims_a = two_orgs_with_runs(client, session_factory)
    db_id = claims_a[0]["dbId"]
    assert client.get(f"/api/v1/claims/{db_id}").status_code == 404
    assert client.patch(f"/api/v1/claims/{db_id}",
                        json={"status": "submitted"}).status_code == 404
    assert client.get(f"/api/v1/claims/{db_id}/letter.md").status_code == 404


def test_runs_list_only_shows_own_org(client, session_factory):
    two_orgs_with_runs(client, session_factory)
    assert client.get("/api/v1/runs").json() == []


def test_live_upload_requires_org_key(client, session_factory):
    org = make_org(session_factory, name="Keyless")
    make_user(session_factory, "k@k.k", "pw12345678", org=org)
    login_as(client, "k@k.k", "pw12345678")
    r = upload(client, dry_run=False)
    assert r.status_code == 422
    assert "API key" in r.json()["detail"]


def test_upload_stamps_org_id(client, session_factory):
    from server.models import Run

    org = make_org(session_factory, name="Stamped")
    make_user(session_factory, "s@s.s", "pw12345678", org=org)
    login_as(client, "s@s.s", "pw12345678")
    run_id = upload(client).json()["runId"]
    with session_factory() as s:
        assert str(s.get(Run, uuid.UUID(run_id)).org_id) == str(org.id)
