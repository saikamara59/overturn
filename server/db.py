from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker


def normalize_database_url(url: str) -> str:
    """Force the psycopg (v3) driver onto bare postgres URLs.

    Hosted Postgres (Railway, Heroku) hands out `postgres://` or
    `postgresql://` URLs; SQLAlchemy would resolve those to psycopg2,
    which this app does not ship.
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def make_engine(url: str) -> Engine:
    return create_engine(normalize_database_url(url), pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
