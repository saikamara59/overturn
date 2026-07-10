from datetime import timedelta

from server.models import Invite, utcnow
from tests.server.conftest import login_as, make_org, make_user


def admin_org(client, session_factory, name="Acme RCM"):
    org = make_org(session_factory, name=name)
    make_user(session_factory, "boss@acme.com", "pw12345678", org=org, role="admin")
    login_as(client, "boss@acme.com", "pw12345678")
    return org


def create_invite(client, role="member", email=None):
    r = client.post("/api/v1/org/invites", json={"role": role, "email": email})
    assert r.status_code == 200, r.text
    return r.json()


def test_invite_lifecycle_new_user(client, session_factory):
    admin_org(client, session_factory)
    inv = create_invite(client, email="newbie@acme.com")
    assert "#/invite/" in inv["inviteUrl"]

    client.post("/api/v1/auth/logout")
    peek = client.get(f"/api/v1/invites/{inv['token']}").json()
    assert peek["orgName"] == "Acme RCM" and peek["role"] == "member"
    assert peek["email"] == "newbie@acme.com"

    r = client.post(f"/api/v1/invites/{inv['token']}/accept",
                    json={"email": "Newbie@acme.com", "password": "freshpw123"})
    assert r.status_code == 200
    assert r.json()["orgName"] == "Acme RCM" and r.json()["role"] == "member"
    # session live
    assert client.get("/api/v1/auth/me").json()["email"] == "newbie@acme.com"
    # single use
    assert client.get(f"/api/v1/invites/{inv['token']}").status_code == 410
    r2 = client.post(f"/api/v1/invites/{inv['token']}/accept",
                     json={"email": "x@y.z", "password": "whatever123"})
    assert r2.status_code == 410


def test_accept_existing_user_requires_their_password(client, session_factory):
    org_b = make_org(session_factory, name="Org B")
    make_user(session_factory, "veteran@x.y", "veteranpw123", org=org_b)
    admin_org(client, session_factory)
    inv = create_invite(client)
    client.post("/api/v1/auth/logout")

    r = client.post(f"/api/v1/invites/{inv['token']}/accept",
                    json={"email": "veteran@x.y", "password": "wrong"})
    assert r.status_code == 401
    r = client.post(f"/api/v1/invites/{inv['token']}/accept",
                    json={"email": "veteran@x.y", "password": "veteranpw123"})
    assert r.status_code == 200
    assert r.json()["orgName"] == "Acme RCM"


def test_accept_when_already_member_409(client, session_factory):
    org = admin_org(client, session_factory)
    make_user(session_factory, "dupe@acme.com", "pw12345678", org=org)
    inv = create_invite(client)
    client.post("/api/v1/auth/logout")
    r = client.post(f"/api/v1/invites/{inv['token']}/accept",
                    json={"email": "dupe@acme.com", "password": "pw12345678"})
    assert r.status_code == 409


def test_expired_invite_410(client, session_factory):
    admin_org(client, session_factory)
    inv = create_invite(client)
    with session_factory() as s:
        s.query(Invite).filter_by(token=inv["token"]).update(
            {"expires_at": utcnow() - timedelta(days=1)})
        s.commit()
    client.post("/api/v1/auth/logout")
    assert client.get(f"/api/v1/invites/{inv['token']}").status_code == 410


def test_unknown_token_404_and_revoke(client, session_factory):
    admin_org(client, session_factory)
    assert client.get("/api/v1/invites/nope").status_code == 404
    inv = create_invite(client)
    pending = client.get("/api/v1/org/invites").json()
    assert len(pending) == 1
    assert client.delete(f"/api/v1/org/invites/{inv['id']}").status_code == 200
    assert client.get("/api/v1/org/invites").json() == []
    assert client.get(f"/api/v1/invites/{inv['token']}").status_code == 404


def test_short_password_422(client, session_factory):
    admin_org(client, session_factory)
    inv = create_invite(client)
    client.post("/api/v1/auth/logout")
    r = client.post(f"/api/v1/invites/{inv['token']}/accept",
                    json={"email": "a@b.c", "password": "short"})
    assert r.status_code == 422
