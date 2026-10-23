"""Scheduled browser work pauses for login and only creates an owner proposal."""
from datetime import timedelta
import json
from types import SimpleNamespace

import pytest

from aicl.browser.service import BrowserBroker
from aicl.browser.task_config import browser_purchase_preset
from aicl.connections.ports import AesGcmSecretStore
from aicl.control.errors import AiclError
from aicl.db import from_iso
from aicl.owner_requests.service import OwnerRequestService
from aicl.render.service import RenderExecution
from aicl.settings import Settings
from aicl.workflow.openai_inference import InferenceResult
from render_worker.runner import execute
from test_browser_sessions import Runtime
from test_workflow_inference import live, rows


def browser_flow(build_env, base_env):
    env, wf, commerce, auth, inst, ops, adapter = live(build_env)
    wf.execution_mode = "render"
    wf.schedule(auth, inst.id, False)
    config = browser_purchase_preset()
    config["cadence"] = "hourly"
    config["browser_task"]["service_url"] = "https://ads.example.com/account"
    wf.save_config(auth, inst.id, config, wf.config(auth, inst.id)["version"])
    wf.schedule(auth, inst.id, True)
    settings = Settings.from_env({**base_env, "AICL_BROWSER_SERVICE_URL": "http://habitat-browser:3001",
                                 "AICL_BROWSER_SERVICE_TOKEN": "b" * 40})
    requests = OwnerRequestService(wf, browser_enabled=True)
    ctx = SimpleNamespace(settings=settings, db=env.db, clock=env.clock,
                          ports=SimpleNamespace(secret_store=AesGcmSecretStore(bytes(range(32)), env.db)))
    runtime = Runtime(env.db)
    runtime.page = lambda _: {"url": "https://ads.example.com/account", "title": "Advertising account",
                             "text": "Account: Orbit Studio. Campaign drafts. Mobile game audience: puzzle fans."}
    broker = BrowserBroker(ctx, requests, runtime)
    requests.browser_cancel = broker.cancel
    execution = RenderExecution(wf, browser=broker)

    def generate(snapshot, spec, feedback=""):
        assert snapshot["browser_evidence"]["text"].startswith("Account: Orbit Studio")
        adapter.calls.append(snapshot)
        return InferenceResult("Recommend a small advertising test for Orbit Quest; no checkout occurred.",
            [{"criterion": c, "passed": True, "reason": "Covered in the proposed scope."} for c in spec["criteria"]],
            100, 100, "resp_browser_" + str(len(adapter.calls)), "gpt-6-sol", browser_review={
                "access_status": "authenticated", "access_evidence": "Account: Orbit Studio",
                "amount_minor": 1500, "description": "Orbit Quest audience test", "rationale": "Test the game's puzzle audience with a bounded campaign.",
                "evidence_excerpt": "Mobile game audience: puzzle fans."})
    adapter.generate = generate
    return env, wf, commerce, auth, inst, requests, broker, runtime, execution, adapter


class LocalWorker:
    def __init__(self, execution):
        self.execution = execution
    def __getattr__(self, name):
        return getattr(self.execution, name)


def run_due(env, wf, auth, inst, execution, task):
    env.clock.set(from_iso(wf.config(auth, inst.id)["next_due"]))
    dispatch, = execution.dispatch()["dispatches"]
    execution.submitted(dispatch["id"], task)
    return execute(LocalWorker(execution), dispatch["id"], task)


@pytest.mark.parametrize("continuation", ["now", "schedule"])
def test_schedule_login_resume_proposal_and_no_checkout(build_env, base_env, continuation):
    env, wf, commerce, auth, inst, requests, broker, runtime, execution, adapter = browser_flow(build_env, base_env)
    before_orders = len(rows(env, "mock_commerce_order"))
    first = run_due(env, wf, auth, inst, execution, "first-task")
    assert first["state"] == "attention" and adapter.calls == []
    login, = rows(env, "owner_request")
    assert login["kind"] == "authentication" and login["status"] == "pending"
    assert json.loads(login["details_json"])["domain"] == "ads.example.com"
    assert rows(env, "mock_workflow_run")[0]["state"] == "waiting_owner"
    assert not rows(env, "mock_commerce_purchase")
    broker.start(auth, login["id"], 1)
    broker.complete(auth, login["id"], 1, continuation)
    if continuation == "schedule":
        assert execution.dispatch()["dispatches"] == []
        env.clock.set(from_iso(wf.config(auth, inst.id)["next_due"]))
    dispatch, = execution.dispatch()["dispatches"]
    execution.submitted(dispatch["id"], "resumed-task")
    result = execute(LocalWorker(execution), dispatch["id"], "resumed-task")
    assert result["state"] == "completed" and len(adapter.calls) == 1
    proposal, = rows(env, "browser_purchase_proposal")
    assert proposal["workflow_run_id"] == login["workflow_run_id"]
    assert proposal["state"] == "pending" and proposal["amount_minor"] == 1500
    assert len(rows(env, "mock_commerce_order")) == before_orders
    assert not rows(env, "mock_commerce_purchase")
    assert len(rows(env, "mock_workflow_deliverable")) == 1
    assert len([r for r in runtime.creates if r["mode"] == "worker"]) == 1
    assert execute(LocalWorker(execution), dispatch["id"], "resumed-task")["state"] == "completed"
    assert len(adapter.calls) == 1 and len(rows(env, "browser_purchase_proposal")) == 1


def test_generate_cannot_bypass_browser_evidence(build_env, base_env):
    env, wf, _, auth, inst, _, _, _, execution, adapter = browser_flow(build_env, base_env)
    env.clock.set(from_iso(wf.config(auth, inst.id)["next_due"]))
    dispatch, = execution.dispatch()["dispatches"]
    execution.submitted(dispatch["id"], "task")
    attempt, = execution.claim(dispatch["id"], "task")["attempts"]
    with pytest.raises(AiclError):
        execution.generate(dispatch["id"], "task", attempt["id"])
    assert adapter.calls == [] and not rows(env, "browser_purchase_proposal")
