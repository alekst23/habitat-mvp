"""Studio AI is prohibited; credentials and legacy config cannot enable it."""

from importlib.util import find_spec

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aicl.app import create_app
from aicl.settings import Settings, SettingsError


ORIGIN = "http://127.0.0.1:4173"
METERING_TABLES = (
    "studio_ai_request", "workflow_inference_attempt", "assistant_inference_attempt",
    "budget_hold", "budget_usage", "mock_commerce_ledger",
)


@pytest.fixture
def no_provider_http(monkeypatch):
    """Block actual HTTP transports without blocking TestClient's ASGI transport."""
    calls = []

    def reject(_self, request):
        calls.append(str(request.url))
        raise AssertionError("Studio must not dispatch provider HTTP")

    async def reject_async(_self, request):
        return reject(_self, request)

    for module in (httpx, httpx2):
        monkeypatch.setattr(module.HTTPTransport, "handle_request", reject)
        monkeypatch.setattr(module.AsyncHTTPTransport, "handle_async_request", reject_async)
    return calls


def configured_settings(base_env):
    # Other product features may use the key; that must never enable Studio AI.
    return Settings.from_env({
        **base_env, "AICL_ENVIRONMENT": "test", "AICL_TEST_MODE": "1",
        "AICL_INFERENCE_MODE": "openai", "AICL_CHAT_MODEL_MODE": "openai",
        "OPENAI_API_KEY": "sk-test-never-real-studio-key",
    })


def metering_rows(app):
    with app.state.ctx.db.reader() as conn:
        return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table}")]
                for table in METERING_TABLES}


def test_authenticated_studio_ai_is_always_denied_without_provider_or_metering(base_env, no_provider_http):
    with TestClient(create_app(configured_settings(base_env)), base_url=ORIGIN) as client:
        seed = client.post("/__test__/seed-session", json={"fixture": "owner-a"}).json()
        headers = {"X-CSRF-Token": seed["csrf_token"], "Origin": ORIGIN}
        before = metering_rows(client.app)
        assert all(not rows for rows in before.values())
        native_request = {"request_id": "29ebdbbb-dac5-4f49-9418-02aee0d3c084", "request": {
            "input": [{"id": "user-1", "kind": "input", "type": "message", "role": "user",
                       "status": "completed", "content": [{"type": "text", "text": "Show spending."}]}],
            "tools": [], "toolChoice": "auto", "responseFormat": {"type": "text"},
        }}
        # Valid requests, caller-supplied enable/config flags and malformed bodies
        # all hit the same unconditional policy denial before request processing.
        responses = [
            client.post("/audit/studio/ai", json=native_request, headers=headers),
            client.post("/audit/studio/ai", json={**native_request, "enabled": True,
                        "providerUrl": "https://api.openai.com/v1/responses"}, headers=headers),
            client.post("/audit/studio/ai", content=b"{", headers={**headers, "Content-Type": "application/json"}),
        ]
        for response in responses:
            assert response.status_code == 403, response.text
            body = response.json()
            assert body["error"] == "denied"
            assert "disabled" in body["message"].lower()
            assert "policy" in body["message"].lower()
        assert metering_rows(client.app) == before
        assert no_provider_http == []


def test_disabled_route_still_requires_authentication_and_csrf(base_env, no_provider_http):
    with TestClient(create_app(configured_settings(base_env)), base_url=ORIGIN) as client:
        anonymous = client.post("/audit/studio/ai", json={})
        assert anonymous.status_code == 401
        assert anonymous.json()["error"] == "unauthenticated"
        seed = client.post("/__test__/seed-session", json={"fixture": "owner-a"}).json()
        for headers in ({}, {"X-CSRF-Token": seed["csrf_token"], "Origin": "https://other.invalid"}):
            denied = client.post("/audit/studio/ai", json={}, headers=headers)
            assert denied.status_code == 403
            assert denied.json()["reason"] == "csrf_failed"
        assert all(not rows for rows in metering_rows(client.app).values())
        assert no_provider_http == []


def test_dashboard_data_and_saved_layouts_work_without_an_ai_service(base_env, no_provider_http):
    assert find_spec("aicl.studio.ai") is None
    with TestClient(create_app(configured_settings(base_env)), base_url=ORIGIN) as client:
        seed = client.post("/__test__/seed-session", json={"fixture": "owner-a"}).json()
        headers = {"X-CSRF-Token": seed["csrf_token"], "Origin": ORIGIN}
        assert client.get("/audit/studio").status_code == 200
        data = client.get("/audit/studio/data")
        assert data.status_code == 200
        assert data.json()["costs"] == []
        assert client.get("/audit/studio/state").json() == {"state": None, "version": 0}
        layout = {"version": "3.0.0", "pages": [{"id": "operations", "widgets": []}]}
        saved = client.put("/audit/studio/state", json={"state": layout, "expected_version": 0}, headers=headers)
        assert saved.status_code == 200, saved.text
        assert saved.json()["state"] == layout
        assert client.get("/audit/studio/state").json() == saved.json()
        assert all(not rows for rows in metering_rows(client.app).values())
        assert no_provider_http == []


@pytest.mark.parametrize("value", ["1", "true", "false", "yes", "01", " 0 "])
def test_legacy_studio_ai_enable_configuration_fails_closed(base_env, value):
    with pytest.raises(SettingsError, match="AICL_STUDIO_AI_ENABLED"):
        Settings.from_env({**base_env, "AICL_STUDIO_AI_ENABLED": value,
                           "OPENAI_API_KEY": "sk-test-never-real-studio-key"})


@pytest.mark.parametrize("value", [None, "", "0"])
def test_absent_or_disabled_legacy_configuration_remains_valid(base_env, value):
    values = dict(base_env)
    if value is not None:
        values["AICL_STUDIO_AI_ENABLED"] = value
    settings = Settings.from_env(values)
    assert "studio_ai_enabled" not in settings.model_dump()
    assert "studio_ai_max_spend_micro_usd" not in settings.model_dump()


@pytest.mark.parametrize("legacy", [{"studio_ai_enabled": True}, {"studio_ai_max_spend_micro_usd": 1_000_000}])
def test_direct_constructor_rejects_removed_studio_ai_controls(base_env, legacy):
    valid = configured_settings(base_env).model_dump()
    with pytest.raises(ValidationError):
        Settings(**{**valid, **legacy})
