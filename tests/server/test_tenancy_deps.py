from tests.server.conftest import login_as, make_org, make_user


def test_disabled_org_gets_403(client, session_factory):
    org = make_org(session_factory, name="Doomed", status="active")
    make_user(session_factory, "u@doomed.com", "pw12345678", org=org)
    login_as(client, "u@doomed.com", "pw12345678")
    from server.models import Org
    with session_factory() as s:
        s.query(Org).filter_by(name="Doomed").update({"status": "disabled"})
        s.commit()
    r = client.get("/api/v1/runs")
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"]


def test_seeding_is_idempotent(client, session_factory):
    # client fixture already ran lifespan seeding once; run it again
    from server.app import create_app  # noqa: F401  (app factory import sanity)
    from server.seed import seed_platform

    from tests.server.conftest import TEST_DATABASE_URL  # noqa: F401
    seed_platform(session_factory, client.app.state.settings)
    from server.models import Membership, Org, User
    with session_factory() as s:
        assert s.query(Org).filter_by(name="Overturn HQ").count() == 1
        assert s.query(User).filter_by(email="admin@example.com").count() == 1
        assert s.query(Membership).count() == 1
