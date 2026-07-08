from tests.server.conftest import login


def test_me_unauthenticated_is_401(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_success_sets_session(client):
    login(client)
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.json() == {"email": "admin@example.com"}


def test_login_wrong_password_is_401(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "wrong"},
    )
    assert r.status_code == 401


def test_logout_clears_session(client):
    login(client)
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code == 401
