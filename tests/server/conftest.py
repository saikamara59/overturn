"""Server test harness: real Postgres via docker compose (port 5433)."""
import os

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://overturn:overturn@localhost:5433/overturn_test",
)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        message = "Postgres unreachable — start it with `docker compose up -d db`"
        if os.environ.get("CI"):
            pytest.fail(f"{message} (refusing to skip in CI)", pytrace=False)
        pytest.skip(message, allow_module_level=False)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    from server.models import Base

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def settings():
    from server.config import Settings

    return Settings(
        database_url=TEST_DATABASE_URL,
        admin_email="admin@example.com",
        admin_password="hunter2hunter2",
        secret_key="test-secret",
        anthropic_api_key=None,
        demo_mode=False,
        key_encryption_secret=Fernet.generate_key().decode(),
    )


@pytest.fixture()
def client(settings, session_factory):
    from fastapi.testclient import TestClient

    from server.app import create_app

    app = create_app(settings=settings, session_factory=session_factory)
    with TestClient(app) as c:
        yield c


def login(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "hunter2hunter2"},
    )
    assert r.status_code == 200, r.text


def make_org(session_factory, name="Acme RCM", **over):
    from server.models import Org

    with session_factory() as s:
        org = Org(name=name, **over)
        s.add(org)
        s.commit()
        return org


def make_user(session_factory, email, password, org=None, role="member",
              platform_admin=False):
    from server.crypto import hash_password
    from server.models import Membership, User

    with session_factory() as s:
        user = User(email=email.lower(), password_hash=hash_password(password),
                    is_platform_admin=platform_admin)
        s.add(user)
        s.flush()
        if org is not None:
            s.add(Membership(user_id=user.id, org_id=org.id, role=role))
        s.commit()
        return user


def login_as(client, email, password):
    r = client.post("/api/v1/auth/login",
                    json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()
