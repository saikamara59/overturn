"""Env-driven settings. Exact env names are part of the spec."""
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    anthropic_api_key: str | None = None
    admin_email: str
    admin_password: str
    secret_key: str
    max_upload_records: int = 200
    demo_mode: bool = True
    spa_dir: str | None = None
    secure_cookies: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
