from tests.server.conftest import login_as, make_org, make_user


def org_with_admin(client, session_factory, name="Acme RCM"):
    org = make_org(session_factory, name=name)
    make_user(session_factory, "boss@acme.com", "pw12345678", org=org, role="admin")
    make_user(session_factory, "biller@acme.com", "pw12345678", org=org)
    return org


def test_org_info_and_key_lifecycle(client, session_factory):
    org_with_admin(client, session_factory)
    login_as(client, "boss@acme.com", "pw12345678")

    info = client.get("/api/v1/org").json()
    assert info["name"] == "Acme RCM" and info["role"] == "admin"
    assert info["hasApiKey"] is False and info["apiKeyLast4"] is None

    assert client.put("/api/v1/org/api-key",
                      json={"key": "not-a-key"}).status_code == 422
    r = client.put("/api/v1/org/api-key",
                   json={"key": "sk-ant-test0123456789wxyz"})
    assert r.status_code == 200
    assert r.json() == {"hasApiKey": True, "apiKeyLast4": "wxyz"}

    # stored encrypted, decryptable, never equal to plaintext
    from server.models import Org
    with session_factory() as s:
        row = s.query(Org).filter_by(name="Acme RCM").one()
        assert row.anthropic_key_encrypted != "sk-ant-test0123456789wxyz"
        from server.crypto import KeyVault
        vault = KeyVault(client.app.state.settings.key_encryption_secret)
        assert vault.decrypt(row.anthropic_key_encrypted) == "sk-ant-test0123456789wxyz"

    assert client.delete("/api/v1/org/api-key").json() == {"hasApiKey": False}


def test_member_cannot_touch_key_or_members(client, session_factory):
    org_with_admin(client, session_factory)
    login_as(client, "biller@acme.com", "pw12345678")
    assert client.put("/api/v1/org/api-key",
                      json={"key": "sk-ant-test0123456789wxyz"}).status_code == 403
    assert client.get("/api/v1/org/members").status_code == 403
    assert client.get("/api/v1/org").status_code == 200  # info is member-visible


def test_member_management_and_last_admin_guard(client, session_factory):
    from server.models import User

    org_with_admin(client, session_factory)
    login_as(client, "boss@acme.com", "pw12345678")

    members = client.get("/api/v1/org/members").json()
    assert {m["email"] for m in members} == {"boss@acme.com", "biller@acme.com"}
    biller_id = next(m["userId"] for m in members if m["email"] == "biller@acme.com")
    boss_id = next(m["userId"] for m in members if m["email"] == "boss@acme.com")

    assert client.patch(f"/api/v1/org/members/{biller_id}",
                        json={"role": "admin"}).status_code == 200
    assert client.patch(f"/api/v1/org/members/{biller_id}",
                        json={"role": "member"}).status_code == 200
    # boss is the last admin now
    assert client.patch(f"/api/v1/org/members/{boss_id}",
                        json={"role": "member"}).status_code == 409
    assert client.delete(f"/api/v1/org/members/{boss_id}").status_code == 409
    assert client.delete(f"/api/v1/org/members/{biller_id}").status_code == 200
    assert client.patch(f"/api/v1/org/members/{biller_id}",
                        json={"role": "admin"}).status_code == 404
