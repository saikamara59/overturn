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
