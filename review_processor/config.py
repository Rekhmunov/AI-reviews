from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(frozen=True)
class AppConfig:
    app_env: str
    db_url: str | None
    self_registration_enabled: bool

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"


def load_app_config() -> AppConfig:
    app_env = (os.getenv("APP_ENV") or "development").strip().lower() or "development"
    db_url_raw = (os.getenv("APP_DB_URL") or "").strip()
    db_url = db_url_raw or None
    if app_env == "production" and not db_url:
        raise RuntimeError("APP_DB_URL must be set when APP_ENV=production (PostgreSQL-only production mode).")
    self_registration_enabled = _env_bool("APP_SELF_REGISTRATION_ENABLED", False)
    return AppConfig(
        app_env=app_env,
        db_url=db_url,
        self_registration_enabled=self_registration_enabled,
    )
