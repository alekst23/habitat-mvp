"""E11-2 composition: shared service components per Settings, port factories, startup hooks and route
dependencies. Registered through the E11-1 extension points (PORT_REGISTRY, STARTUP_HOOKS, ROUTE_FACTORIES)."""

from __future__ import annotations

import base64
import threading
from dataclasses import dataclass

from aicl.auth.magic_link import CaptureMagicLinkSender, SmtpConfig, SmtpMagicLinkSender
from aicl.auth.purge import MagicLinkPurge
from aicl.chat.ports import ScriptedChatModel
from aicl.clock import SystemClock
from aicl.connections.ports import AesGcmSecretStore, FakeProviderOAuth
from aicl.connections.service import SqliteConnectionService, SqliteCredentialBroker, SqliteRevocationSweeper
from aicl.control.budget import SqliteBudgetPort
from aicl.control.confirmation import SqliteConfirmationStore
from aicl.db import Database, LazyDatabase
from aicl.network.policy import FakeResolver
from aicl.settings import Settings, SettingsError
from aicl.work.gate import SqliteHoldReconciler, SqliteWorkGate
from aicl.work.ports import FakeWorkExecutor

# Deterministic public addresses for the fixed provider hosts only; everything else resolves to nothing
# (denied as address_not_public). The fake composition makes no network call.
PROVIDER_HOSTS = {"gmail.googleapis.com": ["142.250.0.1"], "oauth.reddit.com": ["151.101.1.140"]}


@dataclass
class Components:
    secret_store: AesGcmSecretStore
    provider_oauth: FakeProviderOAuth
    resolver: FakeResolver
    credential_broker: SqliteCredentialBroker
    work_executor: FakeWorkExecutor


_LOCK = threading.Lock()
_BY_SETTINGS: dict[int, tuple[Settings, Components]] = {}


def components_for(settings: Settings) -> Components:
    """One set of E11-2 ports per Settings instance, so factories share state (the broker, executor and
    connection service must use the same store and fake provider)."""
    with _LOCK:
        cached = _BY_SETTINGS.get(id(settings))
        if cached is not None and cached[0] is settings:
            return cached[1]
        db = LazyDatabase()
        clock = SystemClock()
        store = AesGcmSecretStore(base64.b64decode(settings.secret_encryption_key), db)
        oauth = FakeProviderOAuth()
        resolver = FakeResolver(PROVIDER_HOSTS)
        broker = SqliteCredentialBroker(db, clock, oauth, store, resolver)
        built = Components(store, oauth, resolver, broker, FakeWorkExecutor(broker, Database(settings.database_url)))
        _BY_SETTINGS[id(settings)] = (settings, built)
        return built


def magic_link_sender(settings: Settings):
    """Capture fake only in the test composition (both flags); else the SMTP sender, which needs AICL_SMTP_HOST
    (startup fails when it is unset)."""
    if settings.test_mode and settings.environment == "test":
        return CaptureMagicLinkSender()
    if not settings.smtp_host:
        raise SettingsError("AICL_SMTP_HOST", "is required outside the test composition")
    return SmtpMagicLinkSender(SmtpConfig(settings.smtp_host, settings.smtp_port, settings.smtp_username,
                                          settings.smtp_password, settings.smtp_from))


def chat_model(settings: Settings) -> ScriptedChatModel:
    """The only chat model is the deterministic fake (Settings rejects any other AICL_CHAT_MODEL_MODE)."""
    return ScriptedChatModel()


PORT_FACTORIES = {
    "chat_model": chat_model,
    "magic_link_sender": magic_link_sender,
    "secret_store": lambda settings: components_for(settings).secret_store,
    "credential_broker": lambda settings: components_for(settings).credential_broker,
    "provider_oauth": lambda settings: components_for(settings).provider_oauth,
    "work_executor": lambda settings: components_for(settings).work_executor,
    "resolver": lambda settings: components_for(settings).resolver,
}


# -- services for routes ---------------------------------------------------------------------------
def connection_service(ctx) -> SqliteConnectionService:
    return SqliteConnectionService(ctx.db, ctx.clock, ctx.ports.provider_oauth, ctx.ports.secret_store,
                                   ctx.settings.public_base_url)


def work_gate(ctx) -> SqliteWorkGate:
    budget = SqliteBudgetPort(ctx.db, ctx.clock, ctx.settings.hold_stale_seconds)
    confirmations = SqliteConfirmationStore(ctx.settings.confirmation_ttl_seconds, ctx.clock)
    return SqliteWorkGate(ctx.db, ctx.clock, budget, confirmations, ctx.ports.work_executor, ctx.ports.resolver,
                          ctx.settings.hold_stale_seconds, ctx.settings.executor_timeout_seconds)


# -- startup hooks (sweeper first, then reconciler) ---------------------------------------------------
def start_revocation_sweeper(ctx) -> None:
    """Destroys the secrets of every revoked connection that still has one; a failure fails startup."""
    SqliteRevocationSweeper(ctx.db, ctx.clock, ctx.ports.secret_store).run_once()


def start_hold_reconciler(ctx) -> None:
    """Runs reconcile_holds once at startup, then every AICL_RECONCILE_INTERVAL_SECONDS in-process."""
    budget = SqliteBudgetPort(ctx.db, ctx.clock, ctx.settings.hold_stale_seconds)
    reconciler = SqliteHoldReconciler(ctx.db, ctx.clock, budget, ctx.ports.work_executor)
    reconciler.run_once()
    interval = ctx.settings.reconcile_interval_seconds

    def loop() -> None:
        while True:
            threading.Event().wait(interval)
            reconciler.run_once()

    threading.Thread(target=loop, name="aicl-hold-reconciler", daemon=True).start()


def start_magic_link_purge(ctx) -> None:
    """Deletes magic_link rows expired for more than 24 hours at startup, then hourly in-process."""
    purge = MagicLinkPurge(ctx.db, ctx.clock)
    purge.run_once()

    def loop() -> None:
        while True:
            threading.Event().wait(3600)
            try:
                purge.run_once()
            except Exception:  # a failed hourly sweep must not kill the thread
                pass

    threading.Thread(target=loop, name="aicl-magic-link-purge", daemon=True).start()
