"""Settings: validation of every row of the consolidated configuration table (E11-1)."""

from __future__ import annotations

import base64
from typing import Mapping
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict


class SettingsError(Exception):
    """Startup failure; names the variable, never its value."""

    def __init__(self, variable: str, message: str) -> None:
        super().__init__(f"{variable}: {message}")
        self.variable = variable


class Settings(BaseModel):
    """Typed settings. Defaults mirror architecture.md; required variables have no default."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    environment: str
    test_mode: bool = False
    public_base_url: str = "http://127.0.0.1:4173"
    database_url: str
    session_secret: str
    identity_hmac_key: str
    secret_encryption_key: str
    price_table_path: str
    session_ttl_seconds: int = 28800
    magic_link_ttl_seconds: int = 900
    confirmation_ttl_seconds: int = 300
    reconcile_interval_seconds: int = 60
    hold_stale_seconds: int = 900
    executor_timeout_seconds: int = 30
    provider_mode: str = "fake"
    executor_mode: str = "fake"
    chat_model_mode: str = "fake"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        """Validate every row; raise SettingsError (fail startup) on any invalid or missing value."""
        def get(name: str, default: str | None = None) -> str:
            value = env.get(name, default)
            if value is None or value == "":
                if default is not None:
                    return default
                raise SettingsError(name, "is required")
            return value

        def integer(name: str, default: int, low: int, high: int) -> int:
            raw = env.get(name)
            if raw is None or raw == "":
                return default
            try:
                value = int(raw)
            except ValueError:
                raise SettingsError(name, "must be an integer") from None
            if not low <= value <= high:
                raise SettingsError(name, f"must be between {low} and {high}")
            return value

        environment = get("AICL_ENVIRONMENT")
        if environment not in ("development", "test", "production"):
            raise SettingsError("AICL_ENVIRONMENT", "must be development, test or production")
        flag = env.get("AICL_TEST_MODE", "0") or "0"
        if flag not in ("0", "1"):
            raise SettingsError("AICL_TEST_MODE", "must be 0 or 1")
        if flag == "1" and environment != "test":
            raise SettingsError("AICL_TEST_MODE", "1 is valid only with AICL_ENVIRONMENT=test")

        base_url = get("AICL_PUBLIC_BASE_URL", "http://127.0.0.1:4173")
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise SettingsError("AICL_PUBLIC_BASE_URL", "must be an absolute http(s) URL")
        local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
        if parsed.scheme == "http" and not (environment in ("test", "development") and local):
            raise SettingsError("AICL_PUBLIC_BASE_URL", "must use https outside local test or development")

        database_url = get("AICL_DATABASE_URL")
        if not database_url.startswith("sqlite:///") or len(database_url) <= len("sqlite:///"):
            raise SettingsError("AICL_DATABASE_URL", "must be sqlite:///path")

        placeholders = ("CHANGE_ME_32_BYTES_MINIMUM", "CHANGE_ME_IDENTITY_32_BYTES_MIN", "CHANGE_ME_BASE64_32_BYTES")
        session_secret = get("AICL_SESSION_SECRET")
        identity_key = get("AICL_IDENTITY_HMAC_KEY")
        encryption_key = get("AICL_SECRET_ENCRYPTION_KEY")
        for name, value in (("AICL_SESSION_SECRET", session_secret), ("AICL_IDENTITY_HMAC_KEY", identity_key),
                            ("AICL_SECRET_ENCRYPTION_KEY", encryption_key)):
            if value in placeholders or value.startswith("CHANGE_ME"):
                raise SettingsError(name, "is a placeholder; set a real secret")
        if len(session_secret.encode()) < 32:
            raise SettingsError("AICL_SESSION_SECRET", "must be at least 32 bytes")
        if len(identity_key.encode()) < 32:
            raise SettingsError("AICL_IDENTITY_HMAC_KEY", "must be at least 32 bytes")
        if identity_key == session_secret:
            raise SettingsError("AICL_IDENTITY_HMAC_KEY", "must differ from AICL_SESSION_SECRET")
        try:
            decoded = base64.b64decode(encryption_key, validate=True)
        except ValueError:
            raise SettingsError("AICL_SECRET_ENCRYPTION_KEY", "must be base64") from None
        if len(decoded) != 32:
            raise SettingsError("AICL_SECRET_ENCRYPTION_KEY", "must be base64 of exactly 32 bytes")

        modes = {}
        for name, key, extra in (("AICL_PROVIDER_MODE", "provider_mode", "; provider enablement is not recorded"),
                                 ("AICL_EXECUTOR_MODE", "executor_mode", ""),
                                 ("AICL_CHAT_MODEL_MODE", "chat_model_mode", "")):
            value = env.get(name) or "fake"
            if value != "fake":
                raise SettingsError(name, "only fake is accepted" + extra)
            modes[key] = value

        executor_timeout = integer("AICL_EXECUTOR_TIMEOUT_SECONDS", 30, 1, 300)
        reconcile = integer("AICL_RECONCILE_INTERVAL_SECONDS", 60, 5, 3600)
        hold_stale = integer("AICL_HOLD_STALE_SECONDS", 900, 60, 86400)
        if hold_stale <= executor_timeout + reconcile:
            raise SettingsError("AICL_HOLD_STALE_SECONDS", "must exceed executor timeout plus reconcile interval")
        return cls(
            environment=environment, test_mode=flag == "1", public_base_url=base_url, database_url=database_url,
            session_secret=session_secret, identity_hmac_key=identity_key, secret_encryption_key=encryption_key,
            price_table_path=get("AICL_PRICE_TABLE_PATH"),
            session_ttl_seconds=integer("AICL_SESSION_TTL_SECONDS", 28800, 300, 604800),
            magic_link_ttl_seconds=integer("AICL_MAGIC_LINK_TTL_SECONDS", 900, 60, 3600),
            confirmation_ttl_seconds=integer("AICL_CONFIRMATION_TTL_SECONDS", 300, 30, 3600),
            reconcile_interval_seconds=reconcile, hold_stale_seconds=hold_stale,
            executor_timeout_seconds=executor_timeout,
            smtp_host=env.get("AICL_SMTP_HOST") or "", smtp_port=integer("AICL_SMTP_PORT", 587, 1, 65535),
            smtp_username=env.get("AICL_SMTP_USERNAME") or "", smtp_password=env.get("AICL_SMTP_PASSWORD") or "",
            smtp_from=env.get("AICL_SMTP_FROM") or "", **modes)
