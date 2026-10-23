"""Authenticated owner handoff routes, rendered UX and secret-free responses."""
from fastapi.testclient import TestClient

from aicl.app import FIXTURE_CSRF_TOKEN
from test_browser_sessions import prepared_browser, COOKIE
from test_owner_request_pages import application


def test_sign_in_handoff_routes_require_owner_csrf_and_render_saved_revoke_state(build_env, base_env, monkeypatch):
    env, _, auth, _, _, requests, login, _, runtime, broker = prepared_browser(build_env, base_env)
    monkeypatch.setattr("aicl.browser.routes.browser_broker", lambda ctx, requests: broker)
    app, origin = application(env, auth, {**base_env,
        "AICL_BROWSER_SERVICE_URL": "http://habitat-browser:8090",
        "AICL_BROWSER_SERVICE_TOKEN": "browser-only-token-" + "x" * 32})
    path = f"/requests/{login['id']}/browser"
    fields = {"expected_version": "1", "csrf_token": FIXTURE_CSRF_TOKEN}
    headers = {**origin, "X-CSRF-Token": FIXTURE_CSRF_TOKEN}
    with TestClient(app, follow_redirects=False) as client:
        assert client.get(path).status_code == 303
        assert client.post(path + "/frame", json={}).status_code == 401
        client.cookies.set("aicl_session", "owner")
        inbox = client.get("/requests", params={"selected": login["id"]})
        assert "Open secure sign-in" in inbox.text and "disabled aria-describedby" not in inbox.text
        assert client.post(path + "/start", data={"expected_version": "1"}, headers=origin).status_code == 403
        opened = client.post(path + "/start", data=fields, headers=origin)
        assert opened.status_code == 303 and opened.headers["location"] == path
        page = client.get(path)
        assert page.status_code == 200 and "You have control" in page.text
        assert "Return session to agent" in page.text and "The worker must check access" in page.text
        assert page.headers["cache-control"] == "no-store"
        # no-referrer makes Chromium send Origin:null for normal POST forms,
        # which correctly fails our CSRF guard. Same-origin keeps local forms working.
        assert page.headers["referrer-policy"] == "same-origin"
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert client.post(path + "/frame", json={}).status_code == 403
        client.cookies.set("aicl_session", "other")
        assert client.get(path).status_code == 404
        assert client.post(path + "/frame", json={}, headers=headers).status_code == 404
        client.cookies.set("aicl_session", "owner")
        frame = client.post(path + "/frame", json={}, headers=headers)
        assert frame.status_code == 200 and frame.json()["url"] == "https://login.example"
        assert "oauth-secret" not in frame.text
        typed = client.post(path + "/input", json={"type": "text", "text": "fixture password"}, headers=headers)
        assert typed.json() == {"ok": True} and "fixture password" not in typed.text
        saved = client.post(path + "/complete", data={**fields, "continuation": "schedule"}, headers=origin)
        assert saved.status_code == 303 and "session_provided" in saved.headers["location"]
        history = client.get(saved.headers["location"])
        assert "Session provided" in history.text and "Revoke saved access" in history.text
        assert COOKIE not in history.text
        assert client.post(path + "/input", json={"type": "key", "key": "Enter"}, headers=headers).status_code == 409
        assert client.post(path + "/revoke", data={"csrf_token": FIXTURE_CSRF_TOKEN}, headers=origin).status_code == 303
        revoked = client.get("/requests", params={"selected": login["id"]})
        assert "Saved browser access is revoked" in revoked.text
        assert "Revoke saved access" not in revoked.text
        assert requests.get(auth, login["id"])["browser_state"] == "revoked"
