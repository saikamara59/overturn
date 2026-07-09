from tests.server.conftest import login, login_as, make_org, make_user


def test_platform_admin_seeded_from_env(client):
    # `login` helper uses settings.admin_email/admin_password
    login(client)
    me = client.get("/api/v1/auth/me").json()
    assert me["email"] == "admin@example.com"
    assert me["isPlatformAdmin"] is True
    assert me["orgName"] == "Overturn HQ"
    assert me["role"] == "admin"


def test_login_wrong_password_401(client):
    r = client.post("/api/v1/auth/login",
                    json={"email": "admin@example.com", "password": "nope"})
    assert r.status_code == 401


def test_login_unknown_email_401(client):
    r = client.post("/api/v1/auth/login",
                    json={"email": "ghost@x.y", "password": "pw"})
    assert r.status_code == 401


def test_member_login_email_case_insensitive(client, session_factory):
    org = make_org(session_factory)
    make_user(session_factory, "biller@acme.com", "pw12345678", org=org)
    me = login_as(client, "BILLER@ACME.COM", "pw12345678")
    assert me["orgName"] == "Acme RCM" and me["role"] == "member"


def test_logout_clears_session(client):
    login(client)
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code == 401
