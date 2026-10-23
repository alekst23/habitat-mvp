"""Opt-in real Chromium handoff against an isolated, local test login server.

Run BROWSER_REAL_TEST=1 when the matching Playwright browser is installed. This
uses no real account and proves owner input -> cookie snapshot -> new worker.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading
import time

from fastapi.testclient import TestClient
import pytest

from browser_service.app import create_app
from browser_service.runtime import Settings


@pytest.mark.skipif(os.environ.get("BROWSER_REAL_TEST") != "1", reason="Opt-in real Chromium fixture test")
def test_real_owner_login_snapshot_restore_and_worker_handoff():
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/account" and "fixture_session=owner-approved" in self.headers.get("Cookie", ""):
                body = b"<html><head><title>Fixture account</title></head><body>Protected account content</body></html>"
            else:
                body = b'<html><head><title>Fixture login</title></head><body><form method="post" action="/login"><input name="password" type="password" style="position:absolute;left:20px;top:40px;width:250px;height:30px"><button style="position:absolute;left:20px;top:100px">Sign in</button></form></body></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            if body != b"password=fixture-test-password":
                self.send_response(403)
                self.end_headers()
                return
            self.send_response(303)
            self.send_header("Set-Cookie", "fixture_session=owner-approved; HttpOnly; SameSite=Lax; Path=/")
            self.send_header("Location", "/account")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    token = "real-fixture-token-" + "x" * 32
    headers = {"Authorization": "Bearer " + token}
    settings = Settings(token, test_mode=True, environment="test", fixture_origin=base)
    try:
        with TestClient(create_app(settings)) as client:
            response = client.post("/sessions", headers=headers, json={"idempotency_key": "fixture-owner", "url": base + "/login"})
            assert response.status_code == 200, response.text
            sid = response.json()["session_id"]
            frame = client.get(f"/sessions/{sid}/frame", headers=headers)
            assert frame.status_code == 200 and len(frame.json()["image"]) > 1000
            for action in ({"type": "click", "x": 100, "y": 55}, {"type": "text", "text": "fixture-test-password"}, {"type": "key", "key": "Enter"}):
                assert client.post(f"/sessions/{sid}/input", headers=headers, json=action).status_code == 200
            deadline = time.monotonic() + 5
            while True:
                snapshot = client.post(f"/sessions/{sid}/snapshot", headers=headers)
                assert snapshot.status_code == 200
                if any(cookie["name"] == "fixture_session" for cookie in snapshot.json()["storage_state"]["cookies"]) or time.monotonic() > deadline:
                    break
                time.sleep(0.05)
            assert snapshot.json()["url"].endswith("/account")
            state = snapshot.json()["storage_state"]
            assert any(cookie["name"] == "fixture_session" for cookie in state["cookies"])
            assert client.delete(f"/sessions/{sid}", headers=headers).status_code == 200
            worker = client.post("/sessions", headers=headers, json={"idempotency_key": "fixture-worker", "url": base + "/account", "mode": "worker", "storage_state": state})
            assert worker.status_code == 200, worker.text
            wid = worker.json()["session_id"]
            page = client.get(f"/sessions/{wid}/page", headers=headers)
            assert page.status_code == 200 and "Protected account content" in page.json()["text"]
            assert client.post(f"/sessions/{wid}/navigate", headers=headers, json={"url": "http://127.0.0.1:1/"}).status_code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
