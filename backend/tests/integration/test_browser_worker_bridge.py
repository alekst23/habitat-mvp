"""The worker can read a saved session only through its bound, funded AICL job."""
from datetime import timedelta
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import SecretStr

from aicl.control.errors import AiclError, ERROR_HTTP_STATUS
from aicl.db import to_iso
from aicl.owner_requests.service import OwnerRequestService
from aicl.render.service import MAX_COMPUTE_MINUTES, RenderExecution
from render_worker.client import AICLClient, ClientConfig
from test_render_execution import claim, complete, queued


class Browser:
    def __init__(self, env):
        self.env, self.calls = env, []

    def worker_page(self, auth, request_id, workflow_run_id, url, *, authorize=None):
        # No open SQLite write transaction while the broker navigates.
        assert getattr(self.env.db._local, "conn", None) is None
        self.calls.append((auth, request_id, workflow_run_id, url))
        if authorize:
            with self.env.db.transaction() as conn:
                authorize(conn)
        return {"url": url + "?code=private-callback#token=private", "title": "Campaigns", "text": "Draft campaign",
                "cookies": [{"value": "must-never-cross-the-boundary"}], "cdp_url": "secret"}


def running(build_env):
    env, wf, _, auth, inst, ops, _, execution, dispatch = queued(build_env)
    attempt, = claim(execution, dispatch)["attempts"]
    browser = Browser(env)
    execution = RenderExecution(wf, browser=browser)
    request = OwnerRequestService(wf).create(auth, inst.id, attempt["workflow_run_id"],
        "authentication", "Sign in to the campaign service", "Read the saved campaign draft",
        details={"domain": "ads.example.com"}, dedupe_key="campaign-session")
    # A trusted broker resolves this in production. Here the transport-boundary
    # test supplies a ready session, independently of browser authentication tests.
    with env.db.transaction() as conn:
        conn.execute("UPDATE owner_request SET status='resolved',response_json=? WHERE id=?",
                     (json.dumps({"decision": "session_provided", "browser_session_id": "saved-session"}), request["id"]))
        conn.execute("UPDATE mock_workflow_run SET state=? WHERE id=?", (request["paused_state"], request["job_id"]))
        now, expires = to_iso(env.clock.now()), to_iso(env.clock.now() + timedelta(hours=24))
        conn.execute("INSERT INTO browser_session(id,tenant_id,owner_id,instance_id,request_id,workflow_run_id,request_version,domain,mode,state,expires_at,credential_expires_at,secret_ref,created_at,updated_at) "
                     "VALUES ('saved-session',?,?,?,?,?,1,'ads.example.com','owner','complete',?,?,'fixture-opaque-ref',?,?)",
                     (auth.tenant_id, auth.owner_id, inst.id, request["id"], request["job_id"], now, expires, now, now))
    return env, wf, auth, inst, ops, execution, dispatch, request, browser


def test_browser_page_is_bound_to_active_job_and_never_returns_session_material(build_env):
    env, _, auth, inst, _, execution, dispatch, request, browser = running(build_env)
    call = lambda task="render-task-1", job=request["job_id"], rid=request["id"]: execution.browser_page(
        dispatch["id"], task, job, rid, "https://ads.example.com/campaigns")
    for kwargs in ({"task": "other-task"}, {"job": "other-job"}, {"rid": "other-request"}):
        with pytest.raises(AiclError):
            call(**kwargs)
    assert browser.calls == []
    result = call()
    assert result == {"url": "https://ads.example.com/campaigns", "title": "Campaigns", "text": "Draft campaign", "access_verified": False}
    passed_auth, _, _, _ = browser.calls[0]
    assert (passed_auth.tenant_id, passed_auth.owner_id) == (auth.tenant_id, auth.owner_id)
    with env.db.transaction() as conn:
        conn.execute("UPDATE render_dispatch SET state='attention' WHERE id=?", (dispatch["id"],))
    with pytest.raises(AiclError):
        call()
    assert len(browser.calls) == 1


@pytest.mark.parametrize("change", ["pending", "declined", "paused", "schedule", "released", "expired"])
def test_browser_page_rechecks_owner_wait_controls_and_compute_lease(build_env, change):
    env, wf, auth, inst, ops, execution, dispatch, request, browser = running(build_env)
    if change in ("pending", "declined"):
        with env.db.transaction() as conn:
            conn.execute("UPDATE owner_request SET status=? WHERE id=?", (change, request["id"]))
    elif change == "paused":
        ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "pause")
    elif change == "schedule":
        wf.schedule(auth, inst.id, False)
    elif change == "released":
        with env.db.transaction() as conn:
            conn.execute("UPDATE budget_hold SET state='released' WHERE id=(SELECT hold_id FROM render_dispatch WHERE id=?)", (dispatch["id"],))
    elif change == "expired":
        env.clock.advance(timedelta(minutes=MAX_COMPUTE_MINUTES))
    with pytest.raises(AiclError):
        execution.browser_page(dispatch["id"], "render-task-1", request["job_id"], request["id"],
                               "https://ads.example.com/campaigns")
    assert browser.calls == []


def test_browser_result_is_withheld_if_owner_pauses_during_page_read(build_env):
    env, _, auth, inst, ops, execution, dispatch, request, browser = running(build_env)
    read = browser.worker_page
    def paused_read(*args, **kwargs):
        result = read(*args, **kwargs)
        ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "pause")
        return result
    browser.worker_page = paused_read
    with pytest.raises(AiclError):
        execution.browser_page(dispatch["id"], "render-task-1", request["job_id"], request["id"],
                               "https://ads.example.com/campaigns")
    assert len(browser.calls) == 1


def test_restarted_worker_discovers_saved_signin_request_without_credentials(build_env):
    env, workflow, _, _, _, execution, dispatch, request, _ = running(build_env)
    # Rebuilding the service models a new process with none of the earlier
    # request_owner response in memory. Only explicit, safe metadata is returned.
    restarted = RenderExecution(workflow)
    attempt, = restarted.claim(dispatch["id"], "render-task-1")["attempts"]
    assert attempt["workflow_run_id"] == request["job_id"]
    assert attempt["snapshot"]["browser_requests"] == [{"request_id": request["id"],
        "domain": "ads.example.com", "requested_access": "", "access_verified": False,
        "credential_expires_at": to_iso(env.clock.now() + timedelta(hours=24))}]
    assert "browser_session_id" not in str(attempt) and "secret_ref" not in str(attempt)


def test_later_cron_job_reuses_only_same_agents_current_handoff(build_env):
    from test_owner_requests import request_env
    from test_pocketplan_workflow import pay

    env, workflow, auth, inst, _, execution, dispatch, request, browser = running(build_env)
    complete(execution, dispatch, execution.claim(dispatch["id"], "render-task-1"))
    purchase, = workflow.overview(auth, inst.id)["purchases"]
    pay(workflow, workflow.commerce, auth, purchase["id"])
    # Choose an hourly next job so the explicit 24-hour owner grant is current.
    next_due = env.clock.now() + timedelta(hours=1)
    with env.db.transaction() as conn:
        conn.execute("UPDATE mock_workflow_config SET next_due=? WHERE instance_id=?", (to_iso(next_due), inst.id))
    env.clock.set(next_due)
    future, = execution.dispatch()["dispatches"]
    future_claim = claim(execution, future, "next-cron-task")
    attempt, = future_claim["attempts"]
    assert attempt["workflow_run_id"] != request["job_id"]
    assert attempt["snapshot"]["browser_requests"][0]["request_id"] == request["id"]
    execution.browser_page(future["id"], "next-cron-task", attempt["workflow_run_id"], request["id"], "https://ads.example.com/")
    assert browser.calls[-1][2] == attempt["workflow_run_id"]

    _, _, _, other_auth, other_inst, other_requests, other_job = request_env(lambda: env)
    other = other_requests.create(other_auth, other_inst.id, other_job["id"], "authentication", "Sign in", "Another agent's account",
                                  details={"domain": "ads.example.com"}, dedupe_key="other-login")
    with pytest.raises(AiclError) as denied:
        execution.browser_page(future["id"], "next-cron-task", attempt["workflow_run_id"], other["id"], "https://ads.example.com/")
    assert denied.value.error == "not_found" and len(browser.calls) == 1
    with env.db.transaction() as conn:
        conn.execute("UPDATE browser_session SET state='revoked',secret_ref=NULL WHERE id='saved-session'")
    refreshed, = RenderExecution(workflow).claim(future["id"], "next-cron-task")["attempts"]
    assert "browser_requests" not in refreshed["snapshot"]


def test_worker_client_exposes_only_page_request_not_browser_credentials():
    sent = []
    def transport(request):
        import json
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"title": "Campaigns", "text": "Draft", "url": "https://ads.example.com/"})
    with AICLClient(ClientConfig("http://localhost:4180", "w" * 40), transport=httpx.MockTransport(transport)) as client:
        assert client.browser_page("dispatch", "task", "job", "request", "https://ads.example.com/")["title"] == "Campaigns"
    assert sent == [("/internal/render/jobs/dispatch/browser/page", {
        "task_run_id": "task", "workflow_run_id": "job", "request_id": "request", "url": "https://ads.example.com/"})]


def test_browser_http_route_requires_worker_identity_and_rejects_owner_override(build_env, monkeypatch):
    import aicl.browser.factory as browser_factory
    import aicl.render.routes as routes

    _, workflow, _, _, _, _, dispatch, request, browser = running(build_env)
    worker, scheduler = "worker-test-token" * 3, "scheduler-test-token" * 3
    ctx = SimpleNamespace(settings=SimpleNamespace(workflow_execution_mode="render",
                          worker_token=SecretStr(worker), scheduler_token=SecretStr(scheduler)))
    monkeypatch.setattr(routes, "workflow_service", lambda _: workflow)
    monkeypatch.setattr(browser_factory, "browser_broker", lambda _: browser)
    app = FastAPI()
    app.include_router(routes.render_router(ctx))
    @app.exception_handler(AiclError)
    async def error_handler(_, error):
        return JSONResponse({"error": error.error}, status_code=ERROR_HTTP_STATUS[error.error])
    path = f"/internal/render/jobs/{dispatch['id']}/browser/page"
    payload = {"task_run_id": "render-task-1", "workflow_run_id": request["job_id"],
               "request_id": request["id"], "url": "https://ads.example.com/campaigns"}
    with TestClient(app) as client:
        for token in ("", scheduler):
            assert client.post(path, json=payload, headers={"authorization": "Bearer " + token}).status_code == 401
        headers = {"authorization": "Bearer " + worker}
        assert client.post(path, json={**payload, "owner_id": "another-owner"}, headers=headers).status_code == 422
        assert client.post(path, json={**payload, "task_run_id": "wrong-task"}, headers=headers).status_code == 403
        response = client.post(path, json=payload, headers=headers)
        assert response.status_code == 200 and response.json()["title"] == "Campaigns"
    assert len(browser.calls) == 1
