"""Tests for engine construction — driver normalization for hosted Postgres."""
from server.db import normalize_database_url


def test_bare_postgres_scheme_gets_psycopg_driver():
    # Railway/Heroku-style URLs
    assert normalize_database_url("postgres://u:p@host:5432/db") == (
        "postgresql+psycopg://u:p@host:5432/db"
    )
    assert normalize_database_url("postgresql://u:p@host:5432/db") == (
        "postgresql+psycopg://u:p@host:5432/db"
    )


def test_explicit_driver_urls_unchanged():
    url = "postgresql+psycopg://u:p@host:5432/db"
    assert normalize_database_url(url) == url
