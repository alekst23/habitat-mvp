"""Hosted demonstration entry provisions ordinary, isolated owner state."""
import re

import pytest
from fastapi.testclient import TestClient

from aicl.app import create_app
from aicl.auth.magic_link import DisabledMagicLinkSender
from aicl.settings import Settings, SettingsError


def judge_env(base_env):
    return {**base_env, "AICL_ENVIRONMENT": "production", "AICL_TEST_MODE": "0",
            "AICL_PUBLIC_BASE_URL": "https://habitat.example", "AICL_HOSTED_WORKFLOW": "1",
            "AICL_JUDGE_DEMO_MODE": "1", "AICL_WORKFLOW_EXECUTION_MODE": "render",
            "AICL_SCHEDULER_TOKEN": "judge-scheduler-fixture-" + "s" * 32,
            "AICL_WORKER_TOKEN": "judge-worker-fixture-" + "w" * 32,
            "AICL_PAYMENT_MODE": "paypal_sandbox", "AICL_PAYPAL_CLIENT_ID": "judge-client-fixture",
            "AICL_PAYPAL_CLIENT_SECRET": "judge-secret-fixture", "AICL_PAYPAL_MERCHANT_ID": "JUDGESELLER",
            "AICL_SMTP_HOST": "", "AICL_SMTP_FROM": ""}


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


def test_public_entry_creates_paused_sample_without_email_or_funding(base_env, monkeypatch):
    monkeypatch.setattr("aicl.app.STARTUP_HOOKS", ())
    app = create_app(Settings.from_env(judge_env(base_env)))
    ctx = app.state.ctx
    assert isinstance(ctx.ports.magic_link_sender, DisabledMagicLinkSender)
    assert ctx.settings.render_max_spend_micro_usd == 1_000_000
    assert ctx.settings.render_max_dispatches == 100
    with TestClient(app, base_url="https://habitat.example", follow_redirects=False) as client:
        page = client.get("/")
        assert page.status_code == 200 and "Try the demo" in page.text and 'name="email"' not in page.text
        assert page.headers["referrer-policy"] == "same-origin"
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
        entered = client.post("/judge/start", data={"csrf_token": token}, headers={"origin": "https://habitat.example"})
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
        assert client.post("/judge/start", data={"csrf_token": token}, headers={"origin": "https://habitat.example"}).status_code == 303
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
        token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/").text)[1]
        with pytest.raises(RuntimeError, match="fixture provisioning failure"):
            client.post("/judge/start", data={"csrf_token": token}, headers={"origin": "https://habitat.example"})
    with app.state.ctx.db.reader() as conn:
        for table in ("owner", "session", "judge_demo_workspace", "agent_instance"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
