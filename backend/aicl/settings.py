"""Settings: validation of every row of the consolidated configuration table (E11-1)."""

from __future__ import annotations

from typing import Mapping

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

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        """Validate every row; raise SettingsError (fail startup) on any invalid or missing value."""
        raise NotImplementedError("Settings.from_env is not implemented (E11-1)")
