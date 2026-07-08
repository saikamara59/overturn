from server.demo import seed_demo
from server.models import Run


def test_seed_demo_is_idempotent(session_factory):
    a = seed_demo(session_factory)
    b = seed_demo(session_factory)
    assert a == b
    with session_factory() as s:
        run = s.query(Run).one()
        assert run.is_demo and run.dry_run
        assert run.status == "completed"
        assert run.total_records == 50 and run.drafted == 50


def test_demo_endpoints_are_public_and_read_only(client, session_factory):
    seed_demo(session_factory)
    data = client.get("/api/v1/demo/claims").json()      # no login
    assert data["summary"]["processed"] == 50
    assert len(data["claims"]) == 50
    audit = client.get("/api/v1/demo/audit").json()
    assert len(audit) > 0

    # write endpoints refuse the demo run even when authenticated
    from tests.server.conftest import login
    login(client)
    db_id = data["claims"][0]["dbId"]
    assert client.patch(
        f"/api/v1/claims/{db_id}", json={"status": "submitted"}
    ).status_code == 409


def test_demo_404_when_not_seeded(client):
    assert client.get("/api/v1/demo/claims").status_code == 404
