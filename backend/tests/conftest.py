"""Shared fixtures. Fixtures only build plain data or factories: every stub is called from the test
body, so an unimplemented behavior fails at the test's assertion point, not during fixture setup."""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from aicl.clock import FakeClock
from aicl.control.audit import SqliteAuditLog
from aicl.control.auth import AuthContext
from aicl.control.budget import SqliteBudgetPort
from aicl.control.confirmation import SqliteConfirmationStore
from aicl.control.instances import (
    CATALOG_CAPABILITIES, AgentInstance, CapabilityGrant, Limits, SqliteInstanceRepository,
)
from aicl.control.price_table import import_price_table
from aicl.db import Database
from support import EXAMPLE_PRICE_TABLE

T0 = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
# Example price table: input 1000 micro-USD/1000 tokens, output 3000/1000 tokens, compute 5000/minute.
GENEROUS = Limits(1_000_000, 10_000_000, 1_000_000, 10_000_000)


@dataclass
class Env:
    db: Database
    clock: FakeClock
    budget: SqliteBudgetPort
    instances: SqliteInstanceRepository
    audit: SqliteAuditLog
    confirmations: SqliteConfirmationStore

    def new_instance(self, limits: Limits = GENEROUS, capabilities: tuple[str, ...] = ()):
        """Insert a draft instance for a fresh tenant (tenant_id == owner_id); return (auth, instance)."""
        owner = str(uuid.uuid4())
        auth = AuthContext(owner_id=owner, tenant_id=owner, session_id=str(uuid.uuid4()),
                           expires_at=T0 + timedelta(days=3650))
        now = self.clock.now()
        draft = AgentInstance(
            id=str(uuid.uuid4()), tenant_id=owner, owner_id=owner, template_id="default", name="Default",
            instructions="private instructions", lifecycle="draft", gated_reason=None, gate_context=None,
            version=1, limits=limits, network_domains=(), created_at=now, updated_at=now)
        grants = tuple(CapabilityGrant(draft.id, c, c in capabilities) for c in CATALOG_CAPABILITIES)
        with self.db.transaction() as conn:
            saved = self.instances.insert_draft(conn, auth, draft, grants)
        return auth, saved


@pytest.fixture
def build_env(tmp_path):
    def build(start: datetime = T0, hold_stale_seconds: int = 900, ttl_seconds: int = 300) -> Env:
        db = Database(f"sqlite:///{tmp_path / 'aicl.db'}")
        db.migrate()
        with db.transaction() as conn:
            import_price_table(conn, EXAMPLE_PRICE_TABLE)
        clock = FakeClock(start)
        return Env(db, clock, SqliteBudgetPort(db, clock, hold_stale_seconds), SqliteInstanceRepository(),
                   SqliteAuditLog(), SqliteConfirmationStore(ttl_seconds))
    return build


@pytest.fixture
def base_env(tmp_path) -> dict[str, str]:
    """A valid development configuration mapping (AICL_* names); tests override single rows."""
    return {
        "AICL_ENVIRONMENT": "development",
        "AICL_DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        "AICL_PRICE_TABLE_PATH": str(EXAMPLE_PRICE_TABLE),
        "AICL_SESSION_SECRET": "s" * 40,
        "AICL_IDENTITY_HMAC_KEY": "i" * 40,
        "AICL_SECRET_ENCRYPTION_KEY": base64.b64encode(bytes(range(32))).decode(),
        "AICL_SMTP_HOST": "smtp.invalid",  # O-4: required outside the test composition; no connection until a send
    }
