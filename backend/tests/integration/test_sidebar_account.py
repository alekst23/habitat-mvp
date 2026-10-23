"""The shared owner sidebar shows a safe session label and a working sign-out form."""
from datetime import datetime, timedelta, timezone
from html import unescape
import re
import uuid

import pytest
from fastapi.testclient import TestClient

import aicl.db as db_module
from aicl.app import create_app
from aicl.auth.judge_demo import ENTRY_COOKIE
from aicl.auth.session import SESSION_COOKIE, _sha256
from aicl.db import Database, to_iso
from aicl.settings import Settings
from test_judge_demo import judge_env, open_access_link

ORIGIN = "https://habitat.example"


@pytest.fixture
def sidebar_app(base_env, monkeypatch):
    monkeypatch.setattr("aicl.app.STARTUP_HOOKS", ())

    def no_network(*args, **kwargs):
        raise AssertionError("Account navigation must not send email or call providers")

    app = create_app(Settings.from_env(judge_env(base_env)))
    monkeypatch.setattr(app.state.ctx.ports.magic_link_sender, "send", no_network)
    monkeypatch.setattr("aicl.commerce.paypal_sandbox.PayPalSandboxAdapter._session", no_network)
    monkeypatch.setattr("aicl.workflow.openai_inference.OpenAIInferenceAdapter.generate", no_network)
    return app


def sign_in(client, email):
    page = open_access_link(client)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    response = client.post("/judge/start", data={"csrf_token": token, "email": email},
                           headers={"origin": ORIGIN})
    assert response.status_code == 303


def sidebar(response, expected_name):
    assert response.status_code == 200
    aside = re.search(r'<aside\b[^>]*class="sidebar"[^>]*>(.*?)</aside>', response.text, re.S)[1]
    assert re.search(r'class="[^"]*\bsidebar-account\b[^"]*"', aside)
    label = re.search(r'<[^>]+class="[^"]*\baccount-name\b[^"]*"[^>]*>(.*?)</[^>]+>', aside, re.S)[1]
    assert unescape(label.strip()) == expected_name
    # There must be one logout action on the page, including the workspace.
    forms = re.findall(r'<form\b[^>]*action="/auth/logout"[^>]*>(.*?)</form>', response.text, re.S)
    assert len(forms) == 1 and forms[0] in aside and "Sign out" in forms[0]
    token = re.search(r'name="csrf_token" value="([^"]+)"', forms[0])[1]
    return aside, token


def test_sidebar_username_and_logout_work_across_owner_pages_and_created_result(sidebar_app):
    ctx = sidebar_app.state.ctx
    with TestClient(sidebar_app, base_url=ORIGIN, follow_redirects=False) as client:
        sign_in(client, "  Alice  Example@example.test  ")
        auth = ctx.auth_provider.resolve(dict(client.cookies))
        csrf = ctx.csrf_verifier.token_for(auth.session_id)
        with ctx.db.reader() as conn:
            instance_id = conn.execute("SELECT id FROM agent_instance WHERE owner_id=?", (auth.owner_id,)).fetchone()[0]
        for path in ("/workspace", "/agents/new", "/chat", "/connections", "/audit",
                     f"/instances/{instance_id}", f"/instances/{instance_id}/workflow"):
            _, shown_token = sidebar(client.get(path), "Alice Example")
            assert shown_token == csrf, path
        created = client.post("/agents/new", headers={"origin": ORIGIN}, data={
            "csrf_token": csrf, "idempotency_key": "wiz_" + "a" * 32,
            "name": "Sidebar test agent", "instructions": "Prepare a summary",
        })
        _, created_csrf = sidebar(created, "Alice Example")
        assert created_csrf == csrf
        cookie = client.cookies[SESSION_COOKIE]
        assert client.post("/auth/logout", data={"csrf_token": "wrong"},
                           headers={"origin": ORIGIN}).status_code == 403
        assert ctx.sign_in.resolve_session(cookie) is not None
        assert SESSION_COOKIE in client.cookies and ENTRY_COOKIE in client.cookies
        logged_out = client.post("/auth/logout", data={"csrf_token": created_csrf}, headers={"origin": ORIGIN})
        assert logged_out.status_code == 303
        assert ctx.sign_in.resolve_session(cookie) is None
        assert SESSION_COOKIE not in client.cookies and ENTRY_COOKIE not in client.cookies
        assert client.get("/auth/sign-in").status_code == 403
        assert client.get("/workspace").status_code == 303


def test_sidebar_cosmetic_name_is_bounded_and_html_escaped(sidebar_app):
    localpart = '<img src=x onerror=alert(1)>' + "x" * 90
    with TestClient(sidebar_app, base_url=ORIGIN, follow_redirects=False) as client:
        sign_in(client, localpart + "@example.test")
        aside, _ = sidebar(client.get("/workspace"), localpart[:64])
        assert "<img src=x" not in aside and "&lt;img src=x" in aside
        auth = sidebar_app.state.ctx.auth_provider.resolve(dict(client.cookies))
        assert auth.display_name == localpart[:64]


def test_display_name_migration_preserves_existing_session_and_uses_judge_fallback(base_env, monkeypatch, tmp_path):
    old = tmp_path / "pre-display-name-migrations"
    old.mkdir()
    for source in db_module.MIGRATIONS_DIR.glob("*.sql"):
        if source.name < "0023_":
            (old / source.name).write_text(source.read_text())
    db = Database(base_env["AICL_DATABASE_URL"])
    with monkeypatch.context() as patch:
        patch.setattr(db_module, "MIGRATIONS_DIR", old)
        db.migrate()
    owner_id = str(uuid.uuid4())
    cookie = "legacy-sidebar-session-fixture"
    now = datetime.now(timezone.utc)
    with db.transaction() as conn:
        conn.execute("INSERT INTO owner(id,email_hash,created_at) VALUES (?,?,?)",
                     (owner_id, "legacy-sidebar-identity", to_iso(now)))
        conn.execute("INSERT INTO session(id_hash,owner_id,created_at,expires_at) VALUES (?,?,?,?)",
                     (_sha256(cookie), owner_id, to_iso(now), to_iso(now + timedelta(hours=1))))
        before = dict(conn.execute("SELECT * FROM session").fetchone())
        assert "display_name" not in before
    monkeypatch.setattr("aicl.app.STARTUP_HOOKS", ())
    app = create_app(Settings.from_env(judge_env(base_env)))
    with app.state.ctx.db.reader() as conn:
        after = dict(conn.execute("SELECT * FROM session").fetchone())
        assert after.pop("display_name") is None
        assert after == before
    assert app.state.ctx.sign_in.resolve_session(cookie).display_name is None
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        client.cookies.set(SESSION_COOKIE, cookie, domain="habitat.example", path="/")
        sidebar(client.get("/workspace"), "Judge")
