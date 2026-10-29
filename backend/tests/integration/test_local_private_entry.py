"""The local durable demo preserves private entry without SMTP or test bypasses."""
import re

import pytest
from fastapi.testclient import TestClient

from aicl.app import create_app
from aicl.auth.magic_link import DisabledMagicLinkSender
from aicl.settings import Settings, SettingsError

ORIGIN = "http://127.0.0.1:4173"
ACCESS_TOKEN = "local-entry-fixture-" + "a" * 32


def local_env(base_env):
    return {**base_env, "AICL_ENVIRONMENT": "test", "AICL_TEST_MODE": "1",
            "AICL_PUBLIC_BASE_URL": ORIGIN, "AICL_LOCAL_PRIVATE_ENTRY": "1",
            "AICL_ACCESS_LINK_TOKEN": ACCESS_TOKEN, "AICL_SMTP_HOST": "",
            "AICL_AGENT_RUNTIME_MODE": "openai", "AICL_CHAT_MODEL_MODE": "openai",
            "OPENAI_API_KEY": "sk-local-test-never-dispatched"}


def test_private_entry_reaches_durable_chat_without_email_or_auth_bypass(base_env, monkeypatch):
    monkeypatch.setattr("aicl.app.STARTUP_HOOKS", ())
    app = create_app(Settings.from_env(local_env(base_env)))
    ctx = app.state.ctx
    assert ctx.settings.private_entry_enabled and not ctx.settings.judge_demo_mode
    assert ctx.agent_runtime is not None
    assert isinstance(ctx.ports.magic_link_sender, DisabledMagicLinkSender)
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        for path in ("/", "/auth/sign-in", "/auth/access?token=invalid"):
            locked = client.get(path)
            assert locked.status_code == 403 and "Private access link required" in locked.text
        assert client.post("/__test__/seed-session", json={"fixture": "owner-a"}).status_code == 404
        assert client.get("/__test__/last-magic-link?email=demo@example.test").status_code == 404
        assert client.post("/auth/magic-link", data={"email": "demo@example.test"}).status_code == 404
        assert client.get("/auth/verify?token=old").status_code == 404
        assert client.post("/auth/verify", data={"token": "old"}).status_code == 404
        unlocked = client.get("/auth/access", params={"token": ACCESS_TOKEN})
        assert unlocked.status_code == 303 and unlocked.headers["location"] == "/auth/sign-in"
        assert "HttpOnly" in unlocked.headers["set-cookie"] and "SameSite=lax" in unlocked.headers["set-cookie"]
        assert "Secure" not in unlocked.headers["set-cookie"]  # Explicit loopback HTTP only.
        entry = client.get("/auth/sign-in")
        assert "No email will be sent" in entry.text and "PayPal" not in entry.text
        nonce = re.search(r'name="csrf_token" value="([^"]+)"', entry.text)[1]
        payload = {"csrf_token": nonce, "email": "tester@example.test"}
        assert client.post("/judge/start", data=payload).status_code == 403
        signed_in = client.post("/judge/start", data=payload, headers={"Origin": ORIGIN})
        assert signed_in.status_code == 303 and signed_in.headers["location"] == "/work"
        assert "HttpOnly" in signed_in.headers["set-cookie"] and "Secure" not in signed_in.headers["set-cookie"]
        chat = client.get("/chat", follow_redirects=True)
        assert chat.status_code == 200 and 'data-agent-workspace' in chat.text
        assert chat.url.path.startswith('/agent-workspaces/')
        assert client.get("/").headers["location"] == "/work"
        agents = client.get("/workspace")
        assert agents.status_code == 200 and "Your agents" in agents.text
        assert 'class="brand" href="/work"' in agents.text
        assert 'href="/work"' in agents.text and "Review inbox" in agents.text
        assert re.search(r'href="/workspace"[^>]*>.*?</span>Agents</a>', agents.text)
        with ctx.db.reader() as conn:
            assert conn.execute("SELECT count(*) FROM owner").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM magic_link").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM assistant_inference_attempt").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM agent_run").fetchone()[0] == 0
        auth = ctx.auth_provider.resolve(dict(client.cookies))
        csrf = ctx.csrf_verifier.token_for(auth.session_id)
        assert client.post("/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}).status_code == 303
        assert client.get("/").status_code == 403


@pytest.mark.parametrize("change", [
    {"AICL_LOCAL_PRIVATE_ENTRY": "yes"},
    {"AICL_ENVIRONMENT": "production", "AICL_TEST_MODE": "0", "AICL_PUBLIC_BASE_URL": "https://habitat.example"},
    {"AICL_TEST_MODE": "0"},
    {"AICL_PUBLIC_BASE_URL": "https://habitat.example"},
    {"AICL_WORKFLOW_EXECUTION_MODE": "render"},
    {"AICL_ACCESS_LINK_TOKEN": ""},
])
def test_local_private_entry_cannot_enable_hosted_or_unlocked_access(base_env, change):
    with pytest.raises(SettingsError):
        Settings.from_env({**local_env(base_env), **change})
