"""Public waitlist: private Google sink, honest receipts, and bounded anonymous writes."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from aicl.app import create_app
from aicl.settings import Settings, SettingsError
from test_judge_demo import judge_env

WEBHOOK = "https://script.google.com/macros/s/waitlist-fixture/exec"
TOKEN = "waitlist-fixture-" + "w" * 32
ORIGIN = "http://127.0.0.1:4173"


def configured(base_env):
    return {**base_env, "AICL_WAITLIST_WEBHOOK_URL": WEBHOOK, "AICL_WAITLIST_WEBHOOK_TOKEN": TOKEN}


def client_for(env, monkeypatch):
    monkeypatch.setattr("aicl.app.STARTUP_HOOKS", ())
    return TestClient(create_app(Settings.from_env(env)), base_url=env.get("AICL_PUBLIC_BASE_URL", ORIGIN))


def mock_google(monkeypatch, handler):
    from aicl.web import waitlist
    original = httpx.Client
    monkeypatch.setattr(waitlist, "google_client", lambda: original(transport=httpx.MockTransport(handler)))


def test_waitlist_is_below_judges_on_secured_landing_and_separate_from_sign_in(base_env, monkeypatch):
    with client_for(configured(judge_env(base_env)), monkeypatch) as client:
        page = client.get("/")
        assert 'action="/waitlist"' in page.text
        assert page.text.index("For hackathon judges") < page.text.index("Join the waitlist")
        assert "Private access link required" in page.text
        assert TOKEN not in page.text and WEBHOOK not in page.text
        assert client.get("/waitlist").status_code == 200
    with client_for(configured(base_env), monkeypatch) as client:
        assert "Create your first agent" in client.get("/").text


def test_waitlist_disabled_and_partial_or_unsafe_configuration_fail_closed(base_env, monkeypatch):
    with client_for(base_env, monkeypatch) as client:
        assert 'action="/waitlist"' not in client.get("/").text
        response = client.post("/waitlist", data={"email": "reader@example.com"}, headers={"origin": ORIGIN})
        assert response.status_code == 503
        assert "You’re on the list" not in response.text
    for change in ({"AICL_WAITLIST_WEBHOOK_TOKEN": ""},
                   {"AICL_WAITLIST_WEBHOOK_URL": ""},
                   {"AICL_WAITLIST_WEBHOOK_URL": WEBHOOK + "?token=secret"},
                   {"AICL_WAITLIST_WEBHOOK_URL": "https://attacker.example/exec"},
                   {"AICL_WAITLIST_WEBHOOK_TOKEN": "short"}):
        with pytest.raises(SettingsError) as exc:
            Settings.from_env({**configured(base_env), **change})
        assert TOKEN not in str(exc.value)


def test_google_receipt_and_duplicate_retry_do_not_create_a_login_or_expose_data(base_env, monkeypatch):
    seen = []

    def google(request):
        seen.append(request)
        if request.method == "POST":
            assert str(request.url) == WEBHOOK
            assert json.loads(request.content) == {"token": TOKEN, "email": "reader+demo@example.com"}
            return httpx.Response(302, headers={"location": "https://script.googleusercontent.com/macros/echo?receipt=fixture"})
        assert not request.content and "authorization" not in request.headers
        return httpx.Response(200, json={"ok": True})

    mock_google(monkeypatch, google)
    with client_for(configured(base_env), monkeypatch) as client:
        for _ in range(2):
            response = client.post("/waitlist", data={"email": " Reader+Demo@Example.com "}, headers={"origin": ORIGIN})
            assert response.status_code == 200 and "You’re on the list" in response.text
            assert response.headers["cache-control"] == "no-store"
            assert TOKEN not in response.text and "reader+demo" not in response.text
            assert "set-cookie" not in response.headers
        with client.app.state.ctx.db.reader() as conn:
            for table in ("owner", "session", "magic_link"):
                assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert [request.method for request in seen] == ["POST", "GET", "POST", "GET"]


@pytest.mark.parametrize("reply", [
    httpx.Response(200, json={"ok": False}),
    httpx.Response(200, text="<html>Sign in to Google</html>"),
    httpx.Response(503),
    httpx.Response(302, headers={"location": "https://attacker.example/"}),
    httpx.Response(307, headers={"location": "https://script.googleusercontent.com/macros/echo"}),
    "timeout",
])
def test_google_failure_is_retryable_and_never_shows_success(base_env, monkeypatch, reply):
    seen = []

    def google(request):
        seen.append(request)
        if reply == "timeout":
            raise httpx.ReadTimeout("secret provider details", request=request)
        return reply

    mock_google(monkeypatch, google)
    with client_for(configured(base_env), monkeypatch) as client:
        response = client.post("/waitlist", data={"email": "reader@example.com"}, headers={"origin": ORIGIN})
        assert response.status_code == 503 and 'role="alert"' in response.text
        assert 'value="reader@example.com"' in response.text
        assert "You’re on the list" not in response.text
        assert "secret provider details" not in response.text and TOKEN not in response.text
    assert len(seen) == 1


def test_validation_origin_honeypot_body_limit_and_rate_limit_prevent_google_writes(base_env, monkeypatch):
    seen = []

    def google(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    mock_google(monkeypatch, google)
    with client_for(configured(base_env), monkeypatch) as client:
        assert client.post("/waitlist", data={"email": "reader@example.com"}).status_code == 403
        assert client.post("/waitlist", data={"email": "reader@example.com"}, headers={"origin": "https://attacker.example"}).status_code == 403
        for email in ("missing-at", "a@", "a@b..com", "a b@example.com", "a\n@example.com", "a" * 255 + "@example.com"):
            assert client.post("/waitlist", data={"email": email}, headers={"origin": ORIGIN}).status_code == 422
        assert client.post("/waitlist", content="email=" + "x" * 2048,
                           headers={"origin": ORIGIN, "content-type": "application/x-www-form-urlencoded"}).status_code == 413
        assert client.post("/waitlist", data={"email": "reader@example.com", "website": "bot"}, headers={"origin": ORIGIN}).status_code == 200
        assert not seen
        for _ in range(5):
            assert client.post("/waitlist", data={"email": "reader@example.com"}, headers={"origin": ORIGIN}).status_code == 200
        limited = client.post("/waitlist", data={"email": "READER@example.com"}, headers={"origin": ORIGIN})
        assert limited.status_code == 429 and limited.headers["retry-after"]
        assert len(seen) == 5
        with client.app.state.ctx.db.reader() as conn:
            stored = str([tuple(row) for row in conn.execute("SELECT * FROM waitlist_rate_limit")])
            assert "reader@example.com" not in stored and "testclient" not in stored
