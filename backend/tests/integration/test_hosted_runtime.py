"""Hosted workflows keep owner authentication and machine credentials separate."""

import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from aicl.app import create_app
from aicl.auth.magic_link import SmtpMagicLinkSender
from aicl.settings import Settings, SettingsError


def hosted_env(base_env):
    return {
        **base_env,
        "AICL_ENVIRONMENT": "production",
        "AICL_PUBLIC_BASE_URL": "https://habitat.example",
        "AICL_HOSTED_WORKFLOW": "1",
        "AICL_WORKFLOW_EXECUTION_MODE": "render",
        "AICL_SCHEDULER_TOKEN": "scheduler-fixture-" + "s" * 32,
        "AICL_WORKER_TOKEN": "worker-fixture-" + "w" * 32,
        "AICL_SMTP_FROM": "signin@habitat.example",
    }


def test_hosted_profile_is_explicit_and_machine_secrets_are_redacted(base_env):
    ordinary = Settings.from_env(base_env)
    assert ordinary.workflow_execution_mode == "local"
    assert not ordinary.hosted_workflow
    settings = Settings.from_env({
        **hosted_env(base_env),
        "AICL_INFERENCE_MODE": "openai", "OPENAI_API_KEY": "fixture-private-openai-key",
        "AICL_PAYMENT_MODE": "paypal_sandbox",
        "AICL_PAYPAL_CLIENT_ID": "fixture-client-id",
        "AICL_PAYPAL_CLIENT_SECRET": "fixture-private-paypal-secret",
        "AICL_PAYPAL_MERCHANT_ID": "FIXTURE123",
    })
    assert settings.workflow_enabled and settings.hosted_workflow
    assert settings.inference_mode == "openai" and settings.payment_mode == "paypal_sandbox"
    for token in (settings.worker_token, settings.scheduler_token):
        assert token.get_secret_value() not in repr(settings)
        assert token.get_secret_value() not in settings.model_dump_json()


@pytest.mark.parametrize("change,variable", [
    ({"AICL_HOSTED_WORKFLOW": "yes"}, "AICL_HOSTED_WORKFLOW"),
    ({"AICL_HOSTED_WORKFLOW": "0"}, "AICL_WORKFLOW_EXECUTION_MODE"),
    ({"AICL_ENVIRONMENT": "development"}, "AICL_HOSTED_WORKFLOW"),
    ({"AICL_TEST_MODE": "1"}, "AICL_TEST_MODE"),
    ({"AICL_PUBLIC_BASE_URL": "http://127.0.0.1:4173"}, "AICL_PUBLIC_BASE_URL"),
    ({"AICL_WORKFLOW_EXECUTION_MODE": "other"}, "AICL_WORKFLOW_EXECUTION_MODE"),
    ({"AICL_SCHEDULER_TOKEN": ""}, "AICL_SCHEDULER_TOKEN"),
    ({"AICL_WORKER_TOKEN": "short-secret"}, "AICL_WORKER_TOKEN"),
    ({"AICL_WORKER_TOKEN": "CHANGE_ME_" + "x" * 32}, "AICL_WORKER_TOKEN"),
    ({"AICL_WORKER_TOKEN": "worker fixture " + "x" * 32}, "AICL_WORKER_TOKEN"),
    ({"AICL_WORKER_TOKEN": "scheduler-fixture-" + "s" * 32}, "AICL_WORKER_TOKEN"),
    ({"AICL_SMTP_HOST": ""}, "AICL_SMTP_HOST"),
    ({"AICL_SMTP_FROM": ""}, "AICL_SMTP_FROM"),
])
def test_unsafe_hosted_configuration_fails_closed(base_env, change, variable):
    with pytest.raises(SettingsError) as caught:
        Settings.from_env({**hosted_env(base_env), **change})
    assert caught.value.variable == variable
    assert "fixture-private" not in str(caught.value)
    assert "short-secret" not in str(caught.value)


def test_hosted_composition_has_assets_health_and_real_auth_no_test_routes(base_env, monkeypatch):
    monkeypatch.setattr("aicl.app.STARTUP_HOOKS", ())
    app = create_app(Settings.from_env(hosted_env(base_env)))
    assert isinstance(app.state.ctx.ports.magic_link_sender, SmtpMagicLinkSender)
    with TestClient(app, base_url="https://habitat.example", follow_redirects=False) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/health/ready").json() == {"status": "ready"}
        assert client.get("/static/brand/paypal-logo-black.png").status_code == 200
        assert client.get("/workspace").status_code in (302, 303)
        assert client.post("/__test__/seed-session", json={"fixture": "owner-a"}).status_code == 404
        assert client.get("/__test__/last-magic-link").status_code == 404
        def unavailable():
            raise sqlite3.OperationalError("private disk path must not leak")
        monkeypatch.setattr(app.state.ctx.db, "_connect", unavailable)
        unavailable_response = client.get("/health/ready")
        assert unavailable_response.status_code == 503
        assert unavailable_response.json() == {"status": "unavailable"}
        assert client.get("/health/live").status_code == 200


def test_app_revalidates_hosted_settings_after_unvalidated_copy(base_env):
    valid = Settings.from_env(hosted_env(base_env))
    with pytest.raises(SettingsError, match="AICL_TEST_MODE"):
        create_app(valid.model_copy(update={"test_mode": True}))


def test_hosted_owner_journey_exposes_schedule_and_audit_without_manual_demo_runs(base_env, monkeypatch):
    monkeypatch.setattr("aicl.app.STARTUP_HOOKS", ())
    app = create_app(Settings.from_env(hosted_env(base_env)))
    sent = []
    # Replace only delivery; link verification, session cookies and CSRF remain real.
    monkeypatch.setattr(app.state.ctx.ports.magic_link_sender, "send", lambda email, link: sent.append(link))
    with TestClient(app, base_url="https://habitat.example", follow_redirects=False) as client:
        assert client.post("/auth/magic-link", data={"email": "hosted-owner@example.test"}).status_code == 202
        token = parse_qs(urlsplit(sent[0]).query)["token"][0]
        signed = client.post("/auth/verify", data={"token": token}, headers={"origin": "https://habitat.example"})
        assert signed.status_code == 303 and "Secure" in signed.headers["set-cookie"]
        auth = app.state.ctx.auth_provider.resolve(dict(client.cookies))
        headers = {"origin": "https://habitat.example", "x-csrf-token": app.state.ctx.csrf_verifier.token_for(auth.session_id)}
        created = client.post("/agents/new", headers=headers, data={
            "idempotency_key": "wiz_" + "h" * 32, "name": "Hosted agent", "instructions": "Market the app",
            "capabilities": ["inference"],
        })
        assert created.status_code == 200
        with app.state.ctx.db.reader() as conn:
            instance_id = conn.execute("SELECT id FROM agent_instance WHERE owner_id=?", (auth.owner_id,)).fetchone()[0]
        workflow_url = f"/instances/{instance_id}/workflow"
        assert workflow_url in client.get("/workspace").text
        page = client.get(workflow_url)
        assert page.status_code == 200
        assert "Enable schedule" in page.text and "Render checks for due work automatically" in page.text
        assert "Demo controls" not in page.text and "Demo scenario" not in page.text
        assert "/workflow/advance" not in page.text
        instance = client.get(f"/instances/{instance_id}")
        assert instance.status_code == 200 and "Fund with PayPal" in instance.text
        assert 'id="work-form"' not in instance.text
        for path in (workflow_url + "/advance", f"/instances/{instance_id}/commerce/runs", "/commerce/runs/old/resume"):
            assert client.post(path, headers=headers).status_code == 404
        assert client.get("/audit?view=purchases").status_code == 200
        assert client.get("/audit?view=deliverables").status_code == 200
