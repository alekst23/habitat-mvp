"""Hosted demonstration entry provisions ordinary, isolated owner state."""
import re

import pytest
from fastapi.testclient import TestClient

from aicl.app import create_app
from aicl.auth.magic_link import DisabledMagicLinkSender
from aicl.settings import Settings, SettingsError

ACCESS_TOKEN = "access-fixture-" + "a" * 32


def judge_env(base_env):
    return {**base_env, "AICL_ENVIRONMENT": "production", "AICL_TEST_MODE": "0",
            "AICL_PUBLIC_BASE_URL": "https://habitat.example", "AICL_HOSTED_WORKFLOW": "1",
            "AICL_JUDGE_DEMO_MODE": "1", "AICL_WORKFLOW_EXECUTION_MODE": "render",
            "AICL_ACCESS_LINK_TOKEN": ACCESS_TOKEN,
            "AICL_SCHEDULER_TOKEN": "judge-scheduler-fixture-" + "s" * 32,
            "AICL_WORKER_TOKEN": "judge-worker-fixture-" + "w" * 32,
            "AICL_PAYMENT_MODE": "paypal_sandbox", "AICL_PAYPAL_CLIENT_ID": "judge-client-fixture",
            "AICL_PAYPAL_CLIENT_SECRET": "judge-secret-fixture", "AICL_PAYPAL_MERCHANT_ID": "JUDGESELLER",
            "AICL_SMTP_HOST": "", "AICL_SMTP_FROM": ""}


def open_access_link(client):
    accepted = client.get("/auth/access", params={"token": ACCESS_TOKEN})
    assert accepted.status_code == 303 and accepted.headers["location"] == "/auth/sign-in"
    assert accepted.headers["cache-control"] == "no-store"
    assert accepted.headers["referrer-policy"] == "no-referrer"
    assert "SameSite=lax" in accepted.headers["set-cookie"]
    assert "Secure" in accepted.headers["set-cookie"] and "HttpOnly" in accepted.headers["set-cookie"]
    assert ACCESS_TOKEN not in accepted.text and ACCESS_TOKEN not in accepted.headers["set-cookie"]
    return client.get("/auth/sign-in")


@pytest.mark.parametrize("change,variable", [
    ({"AICL_JUDGE_DEMO_MODE": "yes"}, "AICL_JUDGE_DEMO_MODE"),
    ({"AICL_JUDGE_DEMO_MODE": "0"}, "AICL_SMTP_HOST"),
    ({"AICL_HOSTED_WORKFLOW": "0"}, "AICL_JUDGE_DEMO_MODE"),
    ({"AICL_PAYMENT_MODE": "mock"}, "AICL_PAYMENT_MODE"),
    ({"AICL_RENDER_MAX_SPEND_MICRO_USD": "0"}, "AICL_RENDER_MAX_SPEND_MICRO_USD"),
    ({"AICL_RENDER_MAX_DISPATCHES": "1001"}, "AICL_RENDER_MAX_DISPATCHES"),
])
def test_judge_mode_is_explicit_sandbox_only_and_keeps_global_limits(base_env, change, variable):
    with pytest.raises(SettingsError) as failure:
        Settings.from_env({**judge_env(base_env), **change})
    assert failure.value.variable == variable


def test_email_prompt_creates_paused_sample_without_sending_email_or_funding(base_env, monkeypatch):
    monkeypatch.setattr("aicl.app.STARTUP_HOOKS", ())
    app = create_app(Settings.from_env(judge_env(base_env)))
    ctx = app.state.ctx
    assert isinstance(ctx.ports.magic_link_sender, DisabledMagicLinkSender)
    assert ctx.settings.render_max_spend_micro_usd == 1_000_000
    assert ctx.settings.render_max_dispatches == 100
    with TestClient(app, base_url="https://habitat.example", follow_redirects=False) as client:
        page = open_access_link(client)
        assert page.status_code == 200 and "Sign in" in page.text and 'name="email"' in page.text
        assert page.headers["referrer-policy"] == "same-origin"
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
        entered = client.post("/judge/start", data={"csrf_token": token, "email": "demo"}, headers={"origin": "https://habitat.example"})
        assert entered.status_code == 303 and entered.headers["location"] == "/workspace"
        assert "Secure" in entered.headers["set-cookie"] and "HttpOnly" in entered.headers["set-cookie"]
        assert "PocketPlan Marketing" in client.get("/workspace").text
        with ctx.db.reader() as conn:
            owner = conn.execute("SELECT * FROM judge_demo_workspace").fetchone()
            instance = conn.execute("SELECT * FROM agent_instance").fetchone()
            config = conn.execute("SELECT * FROM mock_workflow_config").fetchone()
            assert instance["owner_id"] == instance["tenant_id"] == owner["owner_id"]
            assert instance["lifecycle"] == "draft" and config["enabled"] == 0
            assert '"scenario":"pocketplan_ads"' in config["data_json"]
            assert conn.execute("SELECT count(*) FROM magic_link").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM mock_commerce_order").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM mock_commerce_ledger").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM render_dispatch").fetchone()[0] == 0
        assert client.post("/judge/start", data={"csrf_token": token, "email": "demo"}, headers={"origin": "https://habitat.example"}).status_code == 303
        with ctx.db.reader() as conn:
            assert conn.execute("SELECT count(*) FROM owner").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM agent_instance").fetchone()[0] == 1


def test_failed_sample_provisioning_rolls_back_owner_session_and_nonce(base_env, monkeypatch):
    monkeypatch.setattr("aicl.app.STARTUP_HOOKS", ())
    app = create_app(Settings.from_env(judge_env(base_env)))
    def fail(*_args):
        raise RuntimeError("fixture provisioning failure")
    monkeypatch.setattr("aicl.auth.judge_demo._sample", fail)
    with TestClient(app, base_url="https://habitat.example", follow_redirects=False) as client:
        token = re.search(r'name="csrf_token" value="([^"]+)"', open_access_link(client).text)[1]
        with pytest.raises(RuntimeError, match="fixture provisioning failure"):
            client.post("/judge/start", data={"csrf_token": token, "email": "demo"}, headers={"origin": "https://habitat.example"})
    with app.state.ctx.db.reader() as conn:
        for table in ("owner", "session", "judge_demo_workspace", "agent_instance"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("fields", [{}, {"email": "   "}, {"email": "x" * 255}])
def test_email_prompt_rejects_missing_or_oversized_input_without_state(base_env, monkeypatch, fields):
    monkeypatch.setattr("aicl.app.STARTUP_HOOKS", ())
    app = create_app(Settings.from_env(judge_env(base_env)))
    with TestClient(app, base_url="https://habitat.example", follow_redirects=False) as client:
        token = re.search(r'name="csrf_token" value="([^"]+)"', open_access_link(client).text)[1]
        response = client.post("/judge/start", data={"csrf_token": token, **fields},
                               headers={"origin": "https://habitat.example"})
        assert response.status_code == 422 and 'role="alert"' in response.text
        assert "Enter an email" in response.text
        assert response.headers["cache-control"] == "no-store"
        with app.state.ctx.db.reader() as conn:
            for table in ("owner", "session", "judge_demo_workspace", "agent_instance", "magic_link"):
                assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        # Invalid email reuses the granted proof without extending access.
        retry_token = re.search(r'name="csrf_token" value="([^"]+)"', response.text)[1]
        assert retry_token == token and "set-cookie" not in response.headers
        assert client.post("/judge/start", data={"csrf_token": retry_token, "email": "  demo  "},
                           headers={"origin": "https://habitat.example"}).status_code == 303
