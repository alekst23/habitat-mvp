"""Opt-in Chromium proof of durable cookie/localStorage refresh across jobs.

BROWSER_REAL_TEST=1 requires the matching Playwright Chromium installation.
The only website is a temporary loopback fixture; no real accounts are used.
"""
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
import uuid

from fastapi.testclient import TestClient
import httpx
import pytest

from aicl.browser.client import BrowserClient
from aicl.browser.service import BrowserBroker
from aicl.connections.ports import AesGcmSecretStore, SecretUnavailable
from browser_service.app import create_app
from browser_service.runtime import Settings
from test_browser_sessions import prepared_browser


@pytest.mark.skipif(os.environ.get("BROWSER_REAL_TEST") != "1", reason="Opt-in real Chromium fixture test")
def test_real_worker_writeback_survives_reconstruction_and_next_job(build_env, base_env):
    initial, rotated = "fictional-owner-session", "fictional-refreshed-session"

    class Website(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def html(self, body, *, cookie=None):
            content = ("<html><head><title>Fictional account</title></head><body>" + body + "</body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(content)))
            if cookie:
                self.send_header("Set-Cookie", "fixture_session=" + cookie + "; HttpOnly; SameSite=Lax; Path=/")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            cookie = self.headers.get("Cookie", "")
            if self.path == "/account" and "fixture_session=" + initial in cookie:
                self.html("<script>localStorage.setItem('account', 'fictional-initial-storage');</script>Owner signed in")
            elif self.path == "/rotate" and "fixture_session=" + initial in cookie:
                self.html("""<script>
                    if (localStorage.getItem('account') === 'fictional-initial-storage') {
                        localStorage.setItem('account', 'fictional-refreshed-storage');
                        document.write('First job refreshed access');
                    } else document.write('Missing initial storage');
                    </script>""", cookie=rotated)
            elif self.path == "/protected" and "fixture_session=" + rotated in cookie:
                self.html("""<script>
                    document.write(localStorage.getItem('account') === 'fictional-refreshed-storage'
                        ? 'Next job reused refreshed access' : 'Missing refreshed storage');
                    </script>""")
            else:
                self.html('''<form method="post" action="/login">
                    <input name="password" type="password" style="position:absolute;left:20px;top:40px;width:250px;height:30px">
                    <button style="position:absolute;left:20px;top:100px">Sign in</button></form>''')

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path != "/login" or body != b"password=fictional-password":
                self.send_response(403)
                self.end_headers()
                return
            self.send_response(303)
            self.send_header("Set-Cookie", "fixture_session=" + initial + "; HttpOnly; SameSite=Lax; Path=/")
            self.send_header("Location", "/account")
            self.end_headers()

    env, _, auth, _, job, requests, login, store, _, broker = prepared_browser(build_env, base_env)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Website)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    token = broker.ctx.settings.browser_service_token.get_secret_value()
    app = create_app(Settings(token, test_mode=True, environment="test", fixture_origin=origin))
    try:
        with TestClient(app) as private_runtime:
            def transport(request):
                assert getattr(env.db._local, "conn", None) is None
                response = private_runtime.request(request.method, request.url.raw_path.decode(),
                                                   headers=dict(request.headers), content=request.content)
                return httpx.Response(response.status_code, headers=response.headers, content=response.content)

            class FixtureClient(BrowserClient):
                def create(self, **payload):
                    # This test adapter alone rewrites an exact fictional domain.
                    parsed = urlsplit(payload["url"])
                    assert parsed.scheme == "https" and parsed.netloc == "login.example"
                    assert not parsed.query and not parsed.fragment
                    payload["url"] = origin + (parsed.path or "/")
                    return super().create(**payload)

            client = FixtureClient("http://habitat-browser", token, transport=httpx.MockTransport(transport))
            broker.client = client
            owner = broker.start(auth, login["id"], 1)
            for action in ({"type": "click", "x": 100, "y": 55},
                           {"type": "text", "text": "fictional-password"}, {"type": "key", "key": "Enter"}):
                broker.input(auth, login["id"], action)
            with env.db.reader() as conn:
                runtime_id = conn.execute("SELECT runtime_id FROM browser_session WHERE id=?", (owner["id"],)).fetchone()[0]
            deadline = time.monotonic() + 5
            while True:
                snapshot = client.snapshot(runtime_id)
                if "fictional-initial-storage" in json.dumps(snapshot) or time.monotonic() >= deadline:
                    break
                time.sleep(0.05)
            assert "fictional-initial-storage" in json.dumps(snapshot)
            assert broker.complete(auth, login["id"], 1, "schedule")["status"] == "resolved"
            assert app.state.browser_manager.sessions == {}
            with env.db.reader() as conn:
                original = dict(conn.execute("SELECT * FROM browser_session WHERE id=?", (owner["id"],)).fetchone())

            env.clock.advance(timedelta(hours=1))
            first = broker.worker_page(auth, login["id"], job["id"], "https://login.example/rotate")
            assert first["text"] == "First job refreshed access"
            assert app.state.browser_manager.sessions == {}
            with env.db.reader() as conn:
                saved = dict(conn.execute("SELECT * FROM browser_session WHERE id=?", (owner["id"],)).fetchone())
                ciphertext = bytes(conn.execute("SELECT ciphertext FROM secret_blob WHERE ref=?", (saved["secret_ref"],)).fetchone()[0])
            assert saved["secret_ref"] != original["secret_ref"]
            assert saved["credential_expires_at"] == original["credential_expires_at"]
            assert rotated.encode() not in ciphertext and b"fictional-refreshed-storage" not in ciphertext
            updated = json.loads(store.get(saved["secret_ref"], auth.owner_id, owner["id"]))
            assert any(cookie["value"] == rotated for cookie in updated["cookies"])
            assert any(item == {"name": "account", "value": "fictional-refreshed-storage"}
                       for site in updated["origins"] for item in site["localStorage"])
            with pytest.raises(SecretUnavailable):
                store.get(original["secret_ref"], auth.owner_id, owner["id"])

            later_id = str(uuid.uuid4())
            with env.db.transaction() as conn:
                source = dict(conn.execute("SELECT * FROM mock_workflow_run WHERE id=?", (job["id"],)).fetchone())
                later = {**source, "id": later_id}
                conn.execute("INSERT INTO mock_workflow_run(" + ",".join(later) + ") VALUES(" + ",".join("?" for _ in later) + ")", tuple(later.values()))
            env.clock.advance(timedelta(hours=1))
            # New adapters have no copy of the first worker's Chromium context.
            restored_ctx = SimpleNamespace(settings=broker.ctx.settings, db=env.db, clock=env.clock,
                                           ports=SimpleNamespace(secret_store=AesGcmSecretStore(bytes(range(32)), env.db)))
            restored = BrowserBroker(restored_ctx, requests, client)
            second = restored.worker_page(auth, login["id"], later_id, "https://login.example/protected")
            assert second["text"] == "Next job reused refreshed access"
            assert app.state.browser_manager.sessions == {}
            for result in (first, second):
                serialized = json.dumps(result)
                assert not any(value in serialized for value in (initial, rotated, "fictional-password", "fictional-refreshed-storage",
                                                                  "storage_state", "cookies", "secret_ref"))
            with env.db.reader() as conn:
                final = conn.execute("SELECT credential_expires_at FROM browser_session WHERE id=?", (owner["id"],)).fetchone()[0]
                assert final == original["credential_expires_at"]
                assert conn.execute("SELECT COUNT(*) FROM browser_session WHERE state IN ('starting','active','saving','closing')").fetchone()[0] == 0
                assert conn.execute("SELECT COUNT(*) FROM browser_session WHERE mode='worker' AND state='complete'").fetchone()[0] == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
