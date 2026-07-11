from tests.server.conftest import login, login_as, make_org, make_user


def test_platform_admin_gate(client, session_factory):
    org = make_org(session_factory)
    make_user(session_factory, "pleb@acme.com", "pw12345678", org=org)
    login_as(client, "pleb@acme.com", "pw12345678")
    assert client.get("/api/v1/admin/orgs").status_code == 403


def test_create_list_disable_org(client, session_factory):
    login(client)  # seeded platform admin
    r = client.post("/api/v1/admin/orgs", json={"name": "NewCo"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["org"]["name"] == "NewCo"
    assert "#/invite/" in out["inviteUrl"]
    assert client.post("/api/v1/admin/orgs",
                       json={"name": "NewCo"}).status_code == 409

    orgs = client.get("/api/v1/admin/orgs").json()
    names = {o["name"] for o in orgs}
    assert {"Overturn HQ", "NewCo"} <= names

    org_id = out["org"]["id"]
    assert client.patch(f"/api/v1/admin/orgs/{org_id}",
                        json={"status": "disabled"}).status_code == 200
    assert client.patch(f"/api/v1/admin/orgs/{org_id}",
                        json={"status": "bogus"}).status_code == 422

    # the new org's invite still works after re-enable
    client.patch(f"/api/v1/admin/orgs/{org_id}", json={"status": "active"})
    client.post("/api/v1/auth/logout")
    r = client.post(f"/api/v1/invites/{out['token']}/accept",
                    json={"email": "founder@newco.com", "password": "pw12345678"})
    assert r.status_code == 200 and r.json()["role"] == "admin"


def test_accept_invite_for_disabled_org_410(client, session_factory):
    login(client)  # seeded platform admin
    r = client.post("/api/v1/admin/orgs", json={"name": "DisabledCo"})
    assert r.status_code == 200, r.text
    out = r.json()
    org_id = out["org"]["id"]

    assert client.patch(f"/api/v1/admin/orgs/{org_id}",
                        json={"status": "disabled"}).status_code == 200

    client.post("/api/v1/auth/logout")
    r = client.post(f"/api/v1/invites/{out['token']}/accept",
                    json={"email": "founder@disabledco.com",
                          "password": "pw12345678"})
    assert r.status_code == 410
    assert "organization" in r.json()["detail"].lower()
