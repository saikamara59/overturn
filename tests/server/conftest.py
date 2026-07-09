"""Server test harness: real Postgres via docker compose (port 5433)."""
import os

import pytest
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
        pytest.skip(
            "Postgres unreachable — start it with `docker compose up -d db`",
            allow_module_level=False,
        )
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
