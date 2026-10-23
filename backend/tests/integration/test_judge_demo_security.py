"""Independent public-demo security proofs; no email, payment or model network calls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from aicl.app import create_app
from aicl.clock import FakeClock
from aicl.db import to_iso
from aicl.ports import build_ports
from aicl.settings import Settings
from test_hosted_runtime import hosted_env

ORIGIN = "https://habitat.example"
ENTRY_COOKIE = "aicl_judge_entry"


@pytest.fixture
def judge_app(base_env, monkeypatch):
    monkeypatch.setattr("aicl.app.STARTUP_HOOKS", ())
    settings = Settings.from_env({
        **hosted_env(base_env),
        "AICL_JUDGE_DEMO_MODE": "1",
        "AICL_SMTP_HOST": "", "AICL_SMTP_FROM": "",
        "AICL_PAYMENT_MODE": "paypal_sandbox",
        "AICL_PAYPAL_CLIENT_ID": "fixture-paypal-client",
        "AICL_PAYPAL_CLIENT_SECRET": "fixture-paypal-secret",
        "AICL_PAYPAL_MERCHANT_ID": "FIXTURE123",
        "AICL_SESSION_TTL_SECONDS": "172800",
    })
    clock = FakeClock(datetime(2026, 10, 22, 12, tzinfo=timezone.utc))
    ports = build_ports(settings).model_copy(update={"clock": clock})

    def no_network(*args, **kwargs):
        raise AssertionError("Public demo entry must not send mail or call a provider")

    monkeypatch.setattr(ports.magic_link_sender, "send", no_network)
    monkeypatch.setattr("aicl.commerce.paypal_sandbox.PayPalSandboxAdapter._session", no_network)
    monkeypatch.setattr("aicl.workflow.openai_inference.OpenAIInferenceAdapter.generate", no_network)
    return create_app(settings, ports=ports)


def records(app, table):
    with app.state.ctx.db.reader() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM " + table)]


def entry(client):
    page = client.get("/auth/sign-in")
    assert page.status_code == 200
    nonce = client.cookies[ENTRY_COOKIE]
    assert nonce in page.text and 'action="/judge/start"' in page.text
    return nonce


def start(client, nonce, **extra):
    return client.post("/judge/start", data={"csrf_token": nonce, **extra}, headers={"origin": ORIGIN})


@pytest.mark.parametrize("failure", ["no_origin", "foreign_origin", "cross_site", "no_cookie", "wrong_cookie", "forged_nonce"])
def test_entry_requires_same_origin_and_browser_bound_signed_nonce(judge_app, failure):
    with TestClient(judge_app, base_url=ORIGIN, follow_redirects=False) as client:
        nonce = entry(client)
        headers = {"origin": ORIGIN}
        if failure == "no_origin":
            headers = {}
        elif failure == "foreign_origin":
            headers["origin"] = "https://other.example"
        elif failure == "cross_site":
            headers["sec-fetch-site"] = "cross-site"
        elif failure == "no_cookie":
            client.cookies.clear()
        elif failure == "wrong_cookie":
            client.cookies.clear()
            client.cookies.set(ENTRY_COOKIE, "different-browser-nonce")
        elif failure == "forged_nonce":
            nonce = nonce[:-1] + ("a" if nonce[-1] != "a" else "b")
            client.cookies.clear()
            client.cookies.set(ENTRY_COOKIE, nonce)
        response = client.post("/judge/start", data={"csrf_token": nonce}, headers=headers)
        assert response.status_code in (400, 403)
    assert records(judge_app, "owner") == []
    assert records(judge_app, "session") == []


def test_concurrent_anonymous_replay_consumes_one_entry_nonce(judge_app):
    with TestClient(judge_app, base_url=ORIGIN, follow_redirects=False) as browser:
        nonce = entry(browser)
    barrier = Barrier(2)

    def enter_once():
        with TestClient(judge_app, base_url=ORIGIN, follow_redirects=False) as client:
            client.cookies.set(ENTRY_COOKIE, nonce)
            barrier.wait(timeout=5)
            return start(client, nonce).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: enter_once(), range(2)))
    assert sorted(statuses) == [303, 409]
    assert len(records(judge_app, "owner")) == 1
    assert len(records(judge_app, "session")) == 1
    assert len(records(judge_app, "judge_demo_workspace")) == 1
    assert len(records(judge_app, "agent_instance")) == 1


def test_judge_sessions_keep_tenant_and_csrf_isolation_without_fake_funding(judge_app):
    ctx = judge_app.state.ctx
    with TestClient(judge_app, base_url=ORIGIN, follow_redirects=False) as a, TestClient(judge_app, base_url=ORIGIN, follow_redirects=False) as b:
        nonce_a = entry(a)
        entered_a = start(a, nonce_a)
        assert entered_a.status_code == 303
        cookie_flags = entered_a.headers.get("set-cookie", "").lower()
        assert "secure" in cookie_flags and "httponly" in cookie_flags and "samesite=lax" in cookie_flags
        auth_a = ctx.auth_provider.resolve(dict(a.cookies))
        nonce_b = entry(b)
        assert start(b, nonce_b, owner_id=auth_a.owner_id, tenant_id=auth_a.tenant_id).status_code == 303
        auth_b = ctx.auth_provider.resolve(dict(b.cookies))
        assert auth_a.owner_id != auth_b.owner_id
        assert auth_a.owner_id == auth_a.tenant_id and auth_b.owner_id == auth_b.tenant_id
        assert auth_a.session_id != auth_b.session_id
        instances = records(judge_app, "agent_instance")
        instance_a, = [r for r in instances if r["owner_id"] == auth_a.owner_id]
        instance_b, = [r for r in instances if r["owner_id"] == auth_b.owner_id]
        assert instance_a["id"] != instance_b["id"]
        assert a.get("/instances/" + instance_a["id"] + "/workflow").status_code == 200
        assert b.get("/instances/" + instance_a["id"] + "/workflow").status_code == 404
        csrf_a = ctx.csrf_verifier.token_for(auth_a.session_id)
        csrf_b = ctx.csrf_verifier.token_for(auth_b.session_id)
        path = "/instances/" + instance_a["id"] + "/workflow/config"
        assert b.post(path, data={}, headers={"origin": ORIGIN, "x-csrf-token": csrf_a}).status_code == 403
        assert b.post(path, data={}, headers={"origin": ORIGIN, "x-csrf-token": csrf_b}).status_code == 404
        assert records(judge_app, "agent_instance") == instances
        assert start(a, nonce_a).status_code == 303
        assert ctx.auth_provider.resolve(dict(a.cookies)) == auth_a
        assert len(records(judge_app, "agent_instance")) == len(records(judge_app, "owner")) == 2
        for table in ("mock_commerce_order", "mock_commerce_receipt", "mock_commerce_purchase", "mock_commerce_ledger"):
            assert records(judge_app, table) == []
        assert all(r["enabled"] == 0 for r in records(judge_app, "mock_workflow_config"))
        assert all(r["lifecycle"] == "draft" for r in instances)


def test_expired_nonce_and_logged_out_session_cannot_reenter_the_same_account(judge_app):
    ctx = judge_app.state.ctx
    with TestClient(judge_app, base_url=ORIGIN, follow_redirects=False) as expired:
        nonce = entry(expired)
        ctx.clock.advance(timedelta(seconds=601))
        assert start(expired, nonce).status_code in (400, 403)
        assert not records(judge_app, "owner")
    with TestClient(judge_app, base_url=ORIGIN, follow_redirects=False) as client:
        nonce = entry(client)
        assert start(client, nonce).status_code == 303
        cookie = client.cookies["aicl_session"]
        auth = ctx.auth_provider.resolve(dict(client.cookies))
        headers = {"origin": ORIGIN, "x-csrf-token": ctx.csrf_verifier.token_for(auth.session_id)}
        assert client.post("/auth/logout", headers=headers).status_code == 303
        assert ctx.sign_in.resolve_session(cookie) is None
        assert start(client, nonce).status_code == 409
        assert len(records(judge_app, "owner")) == 1


def test_workspace_expiry_denies_even_an_independently_unexpired_session(judge_app):
    ctx = judge_app.state.ctx
    with TestClient(judge_app, base_url=ORIGIN, follow_redirects=False) as client:
        assert start(client, entry(client)).status_code == 303
        auth = ctx.auth_provider.resolve(dict(client.cookies))
        instance, = records(judge_app, "agent_instance")
        # Prove the workspace bound is enforced independently of session TTL.
        with ctx.db.transaction() as conn:
            conn.execute("UPDATE session SET expires_at=? WHERE id_hash=?", (to_iso(ctx.clock.now() + timedelta(days=3)), auth.session_id))
        ctx.clock.advance(timedelta(hours=24, seconds=1))
        assert ctx.auth_provider.resolve(dict(client.cookies)) is None
        assert client.get("/workspace").status_code == 303
        headers = {"origin": ORIGIN, "x-csrf-token": ctx.csrf_verifier.token_for(auth.session_id)}
        assert client.post("/instances/" + instance["id"] + "/workflow/schedule", headers=headers,
                           data={"enabled": "true", "expected_version": "1", "expected_instance_version": "1"}).status_code == 401


def test_judge_deployment_has_no_magic_link_test_or_manual_clock_routes(judge_app):
    with TestClient(judge_app, base_url=ORIGIN, follow_redirects=False) as client:
        for method, path in (
            ("POST", "/auth/magic-link"), ("GET", "/auth/verify?token=anything"), ("POST", "/auth/verify"),
            ("POST", "/__test__/seed-session"), ("GET", "/__test__/last-magic-link"), ("GET", "/__test__/clock"),
            ("POST", "/__demo__/advance"),
        ):
            assert client.request(method, path).status_code == 404
        assert start(client, entry(client)).status_code == 303
        instance, = records(judge_app, "agent_instance")
        assert client.post("/instances/" + instance["id"] + "/workflow/advance").status_code == 404


def test_existing_named_owner_is_preserved_if_judge_mode_was_enabled_later(judge_app, monkeypatch):
    ctx = judge_app.state.ctx
    sent = []
    monkeypatch.setattr(ctx.ports.magic_link_sender, "send", lambda address, link: sent.append(link))
    with TestClient(judge_app, base_url=ORIGIN, follow_redirects=False) as client:
        nonce = entry(client)
        # Seed an ordinary account through its real sign-in service. Public
        # email routes remain disabled; this models a prior authenticated user.
        ctx.sign_in.request_link("existing-owner@example.test", "127.0.0.1")
        token = parse_qs(urlsplit(sent[0]).query)["token"][0]
        signed = ctx.sign_in.verify(token, None)
        client.cookies.set("aicl_session", signed.cookie_value, domain="habitat.example", path="/")
        assert start(client, nonce).status_code == 303
        assert ctx.auth_provider.resolve(dict(client.cookies)) == signed.context
        assert records(judge_app, "judge_demo_workspace") == []
        assert records(judge_app, "agent_instance") == []
        assert len(records(judge_app, "owner")) == 1
        session, = records(judge_app, "session")
        assert session["owner_id"] == signed.context.owner_id and session["revoked_at"] is None
