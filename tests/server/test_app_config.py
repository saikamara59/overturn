"""Misconfiguration must fail loudly, naming the missing env vars."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_ENV = [
    "DATABASE_URL",
    "ADMIN_EMAIL",
    "ADMIN_PASSWORD",
    "SECRET_KEY",
    "KEY_ENCRYPTION_SECRET",
]


def test_build_app_raises_on_missing_env(monkeypatch):
    """The Dockerfile preflight (`get_settings()`) must crash on incomplete env.

    build_app() -> get_settings() must propagate pydantic's ValidationError
    naming the missing fields rather than booting a half-configured app.
    """
    from server import app as app_module
    from server.config import get_settings

    for var in REQUIRED_ENV:
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError) as excinfo:
            app_module.build_app()
        assert "key_encryption_secret" in str(excinfo.value)
    finally:
        get_settings.cache_clear()


def test_module_import_prints_fatal_cause_on_missing_env():
    """`import server.app` with incomplete env must name the real cause on stderr."""
    env = {k: v for k, v in os.environ.items() if k not in REQUIRED_ENV}
    result = subprocess.run(
        [sys.executable, "-c", "import server.app"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )
    assert "FATAL: server configuration invalid" in result.stderr
    assert "key_encryption_secret" in result.stderr
