"""Settings validation, build_ports and create_app / test server (F1-S12 startup, foundation proofs)."""

from __future__ import annotations

import base64
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aicl import hooks, routes
from aicl.app import create_app
from aicl.clock import FakeClock
from aicl.control.csrf import require_csrf
from aicl.ports import REQUIRED_PORTS, Ports, build_ports
from aicl.settings import Settings
from support import STARTUP_FAILURES

REPO = Path(__file__).resolve().parents[3]
TEST_FLAGS = {"AICL_ENVIRONMENT": "test", "AICL_TEST_MODE": "1"}
SECRET_PLACEHOLDERS = ("CHANGE_ME_32_BYTES_MINIMUM", "CHANGE_ME_IDENTITY_32_BYTES_MIN", "CHANGE_ME_BASE64_32_BYTES")


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/settings.py:Settings")
def test_settings_accepts_a_valid_configuration_and_rejects_every_invalid_row(base_env):
    ok = Settings.from_env(base_env)
    assert ok.environment == "development" and ok.test_mode is False and ok.hold_stale_seconds == 900
    assert ok.confirmation_ttl_seconds == 300 and ok.provider_mode == "fake"
    assert Settings.from_env({**base_env, **TEST_FLAGS}).test_mode is True

    b64_short = base64.b64encode(b"x" * 16).decode()
    invalid = {
        "environment": {"AICL_ENVIRONMENT": "staging"},
        "missing environment": {"AICL_ENVIRONMENT": None},
        "test mode outside test env": {"AICL_TEST_MODE": "1"},
        "malformed test mode flag": {"AICL_TEST_MODE": "yes"},
        "short session secret": {"AICL_SESSION_SECRET": "short"},
        "placeholder session secret": {"AICL_SESSION_SECRET": SECRET_PLACEHOLDERS[0]},
        "placeholder identity key": {"AICL_IDENTITY_HMAC_KEY": SECRET_PLACEHOLDERS[1]},
        "identity key equals session secret": {"AICL_IDENTITY_HMAC_KEY": "s" * 40},
        "short encryption key": {"AICL_SECRET_ENCRYPTION_KEY": b64_short},
        "placeholder encryption key": {"AICL_SECRET_ENCRYPTION_KEY": SECRET_PLACEHOLDERS[2]},
        "missing secret": {"AICL_SESSION_SECRET": None},
        "real provider mode": {"AICL_PROVIDER_MODE": "live"},
        "real executor mode": {"AICL_EXECUTOR_MODE": "live"},
        "real chat model mode": {"AICL_CHAT_MODEL_MODE": "live"},
        "confirmation ttl below range": {"AICL_CONFIRMATION_TTL_SECONDS": "29"},
        "confirmation ttl above range": {"AICL_CONFIRMATION_TTL_SECONDS": "3601"},
        "reconcile interval below range": {"AICL_RECONCILE_INTERVAL_SECONDS": "4"},
        "executor timeout above range": {"AICL_EXECUTOR_TIMEOUT_SECONDS": "301"},
        "hold stale below range": {"AICL_HOLD_STALE_SECONDS": "59"},
        "session ttl below range": {"AICL_SESSION_TTL_SECONDS": "299"},
        "magic link ttl above range": {"AICL_MAGIC_LINK_TTL_SECONDS": "3601"},
        "non-sqlite database": {"AICL_DATABASE_URL": "postgresql://x/y"},
        "https required in production": {"AICL_ENVIRONMENT": "production", "AICL_PUBLIC_BASE_URL": "http://example.com"},
    }
    for label, change in invalid.items():
        mapping = {k: v for k, v in {**base_env, **change}.items() if v is not None}
        with pytest.raises(STARTUP_FAILURES) as err:
            Settings.from_env(mapping)
        for secret in (base_env["AICL_SESSION_SECRET"], *SECRET_PLACEHOLDERS):
            assert secret not in str(err.value), label  # errors name the variable, never the value

    # hold-stale cross-check: must exceed executor timeout + reconcile interval (60 + 30 = 90)
    for stale, accepted in ((90, False), (89, False), (91, True)):
        mapping = {**base_env, "AICL_HOLD_STALE_SECONDS": str(stale)}
        if accepted:
            assert Settings.from_env(mapping).hold_stale_seconds == stale
        else:
            with pytest.raises(STARTUP_FAILURES):
                Settings.from_env(mapping)


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/ports.py:build_ports")
def test_build_ports_requires_exactly_the_clock_and_ignores_later_ticket_ports(base_env):
    settings = Settings.from_env(base_env)
    # design-mandated E11-2 extension (DR-30: each owning ticket extends the tuple)
    # O-3: E11-3 appends magic_link_sender (CaptureMagicLinkSender in test mode, SMTP sender otherwise)
    # E11-4 appends chat_model (ScriptedChatModel, the only enabled chat model)
    assert REQUIRED_PORTS == ("clock", "secret_store", "credential_broker", "provider_oauth", "work_executor",
                              "resolver", "magic_link_sender", "chat_model")
    ports = build_ports(settings)
    assert isinstance(ports, Ports) and hasattr(ports.clock, "now") and ports.clock.now().tzinfo is not None
    assert hasattr(ports, "secret_store") and hasattr(ports, "magic_link_sender")
    with pytest.raises(ValidationError):
        ports.clock = FakeClock(ports.clock.now())  # frozen model


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/app.py:create_app")
def test_create_app_migrates_imports_prices_starts_with_empty_extension_points_and_gates_test_routes(base_env, tmp_path):
    # Machine routes are registered as an extension but enabled only by the explicit Render profile.
    assert len(routes.ROUTE_FACTORIES) == 9 and len(hooks.STARTUP_HOOKS) == 3
    assert {"commerce_router", "workflow_router", "render_router"} <= {factory.__name__ for factory in routes.ROUTE_FACTORIES}

    dev = create_app(Settings.from_env(base_env))
    with TestClient(dev) as client:
        assert [r.path for r in dev.routes if r.path.startswith("/__test__")] == []
        assert not any(r.path.startswith("/internal/render") for r in dev.routes)
        assert client.get("/__test__/last-magic-link", params={"email": "a@b.co"}).status_code == 404
        assert client.post("/__test__/seed-session", json={"fixture": "owner-a"}).status_code == 404
        assert client.get("/__test__/clock").status_code == 404
    db_file = Path(base_env["AICL_DATABASE_URL"].removeprefix("sqlite:///"))
    with sqlite3.connect(db_file) as conn:  # migrations ran and the price table was imported at startup
        assert conn.execute("SELECT count(*) FROM schema_migration").fetchone()[0] >= 1
        assert conn.execute("SELECT version FROM price_table_version WHERE explicit_only=0").fetchall() == [("2026-10-01",)]
        assert conn.execute("SELECT version FROM price_table_version WHERE explicit_only=1 ORDER BY version").fetchall() == [
            ("gpt-6-sol-2026-10-22",), ("render-flex-bound-2026-10-22",)]

    test_env = {**base_env, **TEST_FLAGS, "AICL_DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}"}
    test_app = create_app(Settings.from_env(test_env))
    with TestClient(test_app) as client:
        paths = {r.path for r in test_app.routes}
        assert not any(path.startswith("/internal/render") for path in paths)
        assert "/__test__/seed-session" in paths and "/__test__/clock" in paths
        seeded = client.post("/__test__/seed-session", json={"fixture": "owner-a"})
        assert seeded.status_code == 200 and "aicl_session" in seeded.cookies
        assert client.get("/__test__/clock").status_code == 200
        assert "/__test__/last-magic-link" in paths  # O-3: E11-3 owns the test-mode-only capture route

    # startup failures: unusable price table, and a changed table under an already-imported version
    missing = {**base_env, "AICL_PRICE_TABLE_PATH": str(tmp_path / "nope.json")}
    with pytest.raises(STARTUP_FAILURES):
        create_app(Settings.from_env(missing))
    changed = tmp_path / "changed.json"
    changed.write_text((REPO / "backend/aicl/price_table.example.json").read_text().replace('"micro_usd": 5000', '"micro_usd": 5001'))
    with pytest.raises(STARTUP_FAILURES):
        create_app(Settings.from_env({**base_env, "AICL_PRICE_TABLE_PATH": str(changed)}))


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/test_server.py:main")
def test_test_server_module_serves_the_app_with_test_routes_on_loopback(tmp_path):
    env = {"PYTHONPATH": str(REPO / "backend"), "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    proc = subprocess.Popen([sys.executable, "-m", "aicl.test_server"], cwd=REPO, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        status = None
        for _ in range(50):
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen("http://127.0.0.1:4173/__test__/clock", timeout=1) as resp:
                    status = resp.status
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.2)
        assert proc.poll() is None, f"test server exited early: {proc.stderr.read()[-500:]}"
        assert status == 200
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/control/csrf.py:require_csrf")
def test_require_csrf_dependency_authenticates_then_checks_token_and_origin(base_env, tmp_path):
    app = create_app(Settings.from_env({**base_env, **TEST_FLAGS, "AICL_DATABASE_URL": f"sqlite:///{tmp_path / 'csrf.db'}"}))

    @app.post("/__csrf_probe__")
    def probe(auth=Depends(require_csrf(app.state.ctx))):
        return {"owner_id": auth.owner_id}

    own_origin = app.state.ctx.settings.public_base_url
    with TestClient(app) as anonymous:
        denied = anonymous.post("/__csrf_probe__", headers={"x-csrf-token": "fixture-csrf-token"})
        assert denied.status_code == 401 and denied.json()["error"] == "unauthenticated"
    with TestClient(app) as client:
        seeded = client.post("/__test__/seed-session", json={"fixture": "owner-a"}).json()
        for headers in ({}, {"x-csrf-token": "wrong"}, {"x-csrf-token": seeded["csrf_token"], "origin": "http://evil.example"}):
            refused = client.post("/__csrf_probe__", headers=headers)
            assert refused.status_code == 403, headers
            assert refused.json()["error"] == "denied" and refused.json()["reason"] == "csrf_failed"
        ok = client.post("/__csrf_probe__", headers={"x-csrf-token": seeded["csrf_token"], "origin": own_origin})
        assert ok.status_code == 200 and ok.json() == {"owner_id": seeded["owner_id"]}
