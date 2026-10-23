"""Opt-in real Chromium proof of scheduled login, continuation and proposal only.

BROWSER_REAL_TEST=1 uses a loopback fixture and deterministic assessment adapter.
No third-party account, paid inference, merchant checkout or live ad is involved.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import time
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
import httpx
import pytest

from aicl.browser.client import BrowserClient
from aicl.db import from_iso
from browser_service.app import create_app
from browser_service.runtime import Settings
from render_worker.runner import execute
from test_browser_scheduled_flow import LocalWorker, browser_flow, run_due
from test_workflow_inference import rows


@pytest.mark.skipif(os.environ.get("BROWSER_REAL_TEST") != "1", reason="Opt-in real Chromium fixture test")
def test_real_scheduled_agent_requests_login_resumes_and_stops_at_proposal(build_env, base_env):
    session_cookie = "fictional-orbit-owner"

    class Website(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if "fixture_session=" + session_cookie in self.headers.get("Cookie", ""):
                self.wfile.write(b"""<html><head><title>Orbit advertising account</title></head><body>
                    <script>localStorage.setItem('fixture_account', 'Orbit Studio');</script>
                    Account: Orbit Studio. Campaign drafts. Mobile game audience: puzzle fans.
                    </body></html>""")
            else:
                self.wfile.write(b"""<html><head><title>Sign in</title></head><body>
                    <form method="post" action="/login">
                    <input name="password" type="password" style="position:absolute;left:20px;top:40px;width:250px;height:30px">
                    <button style="position:absolute;left:20px;top:100px">Sign in</button></form>
                    </body></html>""")

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            assert self.path == "/login" and body == b"password=fictional-password"
            self.send_response(303)
            self.send_header("Set-Cookie", "fixture_session=" + session_cookie + "; HttpOnly; SameSite=Lax; Path=/")
            self.send_header("Location", "/account")
            self.end_headers()

    env, wf, _, auth, inst, requests, broker, _, execution, adapter = browser_flow(build_env, base_env)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Website)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    token = broker.ctx.settings.browser_service_token.get_secret_value()
    runtime = create_app(Settings(token, test_mode=True, environment="test", fixture_origin=origin))
    try:
        with TestClient(runtime) as private_runtime:
            def transport(request):
                assert getattr(env.db._local, "conn", None) is None
                response = private_runtime.request(request.method, request.url.raw_path.decode(),
                                                   headers=dict(request.headers), content=request.content)
                return httpx.Response(response.status_code, headers=response.headers, content=response.content)

            class FixtureClient(BrowserClient):
                def create(self, **payload):
                    parsed = urlsplit(payload["url"])
                    assert parsed.scheme == "https" and parsed.netloc == "ads.example.com"
                    assert not parsed.query and not parsed.fragment
                    payload["url"] = origin + (parsed.path or "/")
                    return super().create(**payload)

                def page(self, runtime_id):
                    result = super().page(runtime_id)
                    assert result["url"].startswith(origin + "/")
                    # Paired with the test-only inbound rewrite. Production
                    # browser URLs are never rewritten by this fixture adapter.
                    return {**result, "url": "https://ads.example.com" + result["url"][len(origin):]}

            client = FixtureClient("http://habitat-browser", token, transport=httpx.MockTransport(transport))
            broker.client = client
            order_count = len(rows(env, "mock_commerce_order"))
            first = run_due(env, wf, auth, inst, execution, "browser-first-task")
            assert first["state"] == "attention" and not adapter.calls
            login, = rows(env, "owner_request")
            assert login["kind"] == "authentication" and login["status"] == "pending"
            assert rows(env, "mock_workflow_run")[0]["state"] == "waiting_owner"
            assert not rows(env, "browser_purchase_proposal")

            owner = broker.start(auth, login["id"], 1)
            for action in ({"type": "click", "x": 100, "y": 55},
                           {"type": "text", "text": "fictional-password"}, {"type": "key", "key": "Enter"}):
                broker.input(auth, login["id"], action)
            with env.db.reader() as conn:
                runtime_id = conn.execute("SELECT runtime_id FROM browser_session WHERE id=?", (owner["id"],)).fetchone()[0]
            deadline = time.monotonic() + 5
            while True:
                snapshot = client.snapshot(runtime_id)
                if "fixture_account" in json.dumps(snapshot) or time.monotonic() >= deadline:
                    break
                time.sleep(0.05)
            assert "fixture_account" in json.dumps(snapshot)
            assert broker.complete(auth, login["id"], 1, "schedule")["status"] == "resolved"
            assert runtime.state.browser_manager.sessions == {}
            assert execution.dispatch()["dispatches"] == []

            env.clock.set(from_iso(wf.config(auth, inst.id)["next_due"]))
            dispatch, = execution.dispatch()["dispatches"]
            execution.submitted(dispatch["id"], "browser-resumed-task")
            result = execute(LocalWorker(execution), dispatch["id"], "browser-resumed-task")
            assert result["state"] == "completed" and len(adapter.calls) == 1
            assert runtime.state.browser_manager.sessions == {}
            proposal, = rows(env, "browser_purchase_proposal")
            assert proposal["state"] == "pending" and proposal["amount_minor"] == 1500
            assert proposal["workflow_run_id"] == login["workflow_run_id"]
            assert "Mobile game audience: puzzle fans." in proposal["evidence_json"]
            assert len(rows(env, "mock_workflow_deliverable")) == 1
            assert len(rows(env, "mock_commerce_order")) == order_count
            assert not rows(env, "mock_commerce_purchase")
            assert len([row for row in rows(env, "browser_session") if row["mode"] == "worker" and row["state"] == "complete"]) == 1
            persisted = json.dumps(rows(env, "owner_request") + rows(env, "browser_attempt_evidence") + rows(env, "browser_purchase_proposal"))
            assert session_cookie not in persisted and "fictional-password" not in persisted
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
