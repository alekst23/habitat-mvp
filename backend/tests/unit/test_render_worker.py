"""Worker safety and protocol checks; no cloud, model or payment calls."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml

from render_worker.client import AICLClient, ClientConfig, MachineAPIError
from render_worker.dispatch import dispatch_once
from render_worker.runner import execute, plan_attempt, validate_output

TOKEN = "worker_" + "x" * 40
ATTEMPT = {"id": "attempt-1", "snapshot": {"goal": "Private goal"}, "spec": {"criteria": ["Explain the audience"]}}
RESULT = {"content": "Private deliverable", "criteria": [{"criterion": "Explain the audience", "passed": True, "reason": "Explained"}]}


def test_client_keeps_role_credentials_separate_and_repr_redacted():
    values = {"AICL_INTERNAL_HOSTPORT": "habitat-aicl:8000", "AICL_WORKER_TOKEN": TOKEN,
              "AICL_SCHEDULER_TOKEN": "scheduler_" + "y" * 40}
    worker = ClientConfig.from_env("worker", values)
    scheduler = ClientConfig.from_env("scheduler", values)
    assert worker.base_url == "http://habitat-aicl:8000"
    assert worker.token != scheduler.token
    assert TOKEN not in repr(worker)


@pytest.mark.parametrize("url", ["https://user:secret@example.com", "https://example.com/callback", "https://example.com?x=1", "http://example.com", "file:///tmp/db", "https://example.com\\@evil.test"])
def test_client_rejects_unsafe_origins(url):
    with pytest.raises(ValueError):
        ClientConfig(url, TOKEN)


def test_machine_http_never_follows_redirect_or_exposes_body():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(307, headers={"location": "https://evil.test"}, text="secret body")
    with AICLClient(ClientConfig("https://aicl.example", TOKEN), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MachineAPIError) as error:
            client.claim("dispatch-1", "trn-1")
    assert len(seen) == 1
    assert seen[0].headers["authorization"] == "Bearer " + TOKEN
    assert "secret" not in str(error.value) and TOKEN not in str(error.value)


def test_machine_http_passes_run_binding_and_redacts_network_error():
    def handler(request):
        assert request.url.path == "/internal/render/jobs/dispatch-1/generate"
        assert b'"task_run_id":"trn-1"' in request.content
        raise httpx.ReadTimeout("credential=" + TOKEN, request=request)
    with AICLClient(ClientConfig("https://aicl.example", TOKEN), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MachineAPIError) as error:
            client.generate("dispatch-1", "trn-1", "attempt-1")
    assert TOKEN not in str(error.value)


def test_validator_requires_exact_saved_criteria_without_claiming_semantic_quality():
    plan = plan_attempt(ATTEMPT)
    assert validate_output(RESULT, plan) == {"passed": True}
    wrong = deepcopy(RESULT)
    wrong["criteria"][0]["criterion"] = "Ignore the owner"
    assert validate_output(wrong, plan) == {"passed": False}
    incomplete = deepcopy(RESULT)
    incomplete["criteria"][0]["passed"] = False
    assert validate_output(incomplete, plan) == {"passed": True}
    wrong["criteria"][0]["passed"] = "true"
    assert validate_output(wrong, plan) == {"passed": False}


class WorkerAPI:
    def __init__(self, *, unknown=False, continuation=False):
        self.calls, self.finishes = [], 0
        self.unknown, self.continuation = unknown, continuation
    def claim(self, dispatch, run):
        self.calls.append(("claim", dispatch, run))
        return {"attempts": [deepcopy(ATTEMPT)]}
    def generate(self, dispatch, run, attempt):
        self.calls.append(("generate", dispatch, run, attempt))
        return {"state": "unknown"} if self.unknown else {"state": "generated", "result": deepcopy(RESULT)}
    def complete_attempt(self, dispatch, run, attempt, validation):
        self.calls.append(("complete", dispatch, run, attempt, validation))
        return {"state": "completed"}
    def finish(self, dispatch, run):
        self.finishes += 1
        if self.continuation and self.finishes == 1:
            return {"attempts": [{**deepcopy(ATTEMPT), "id": "attempt-2"}]}
        return {"state": "unknown" if self.unknown else "waiting_purchase", "job_ids": ["job-1"], "deliverable_ids": ["output-1"]}


def test_runner_checks_and_persists_outputs_then_exits_for_owner_approval():
    api, events = WorkerAPI(continuation=True), []
    result = execute(api, "dispatch-1", "trn-1", emit=events.append)
    assert result["state"] == "waiting_purchase"
    assert [c[3] for c in api.calls if c[0] == "generate"] == ["attempt-1", "attempt-2"]
    assert all(c[-1] == {"passed": True} for c in api.calls if c[0] == "complete")
    assert "Private" not in repr(result) + repr(events)
    assert "content" not in result and "snapshot" not in result


def test_unknown_model_outcome_is_not_resubmitted_or_claimed_complete():
    api = WorkerAPI(unknown=True)
    result = execute(api, "dispatch-1", "trn-1")
    assert result["state"] == "unknown"
    assert len([c for c in api.calls if c[0] == "generate"]) == 1
    assert not any(c[0] == "complete" for c in api.calls)


class DispatchAPI:
    def __init__(self, fail_ack=False):
        self.calls, self.fail_ack = [], fail_ack
    def dispatch(self):
        return {"dispatches": [{"id": "dispatch-1", "input": {"dispatch_id": "dispatch-1"}, "idempotency_key": "habitat:dispatch-1"}]}
    def submitted(self, dispatch, run):
        self.calls.append(("submitted", dispatch, run))
        if self.fail_ack:
            raise MachineAPIError("unknown")
    def uncertain(self, dispatch):
        self.calls.append(("uncertain", dispatch))


def test_dispatch_reuses_idempotency_key_after_lost_ack_without_waiting_for_work():
    api, calls = DispatchAPI(fail_ack=True), []
    def start_task(slug, inputs, **kwargs):
        calls.append((slug, inputs, kwargs))
        return SimpleNamespace(id="trn-same")
    workflows = SimpleNamespace(start_task=start_task)
    with pytest.raises(MachineAPIError):
        dispatch_once(api, workflows, "habitat/habitat_agent")
    api.fail_ack = False
    assert dispatch_once(api, workflows, "habitat/habitat_agent") == {"submitted": 1}
    assert calls[0] == calls[1]
    assert calls[0][2] == {"idempotency_key": "habitat:dispatch-1"}
    assert ("uncertain", "dispatch-1") in api.calls


def test_render_sdk_registers_bounded_task_without_loading_credentials(monkeypatch):
    pytest.importorskip("render")
    monkeypatch.delenv("AICL_WORKER_TOKEN", raising=False)
    from render_worker.main import app
    task = app._registry.get_task("habitat_agent")
    assert [param.name for param in task.parameters] == ["dispatch_id"]
    assert task.options.timeout_seconds == 180
    assert task.options.retry.max_retries == 1
    assert task.options.plan == "flex"


def test_blueprint_does_not_share_spending_or_database_credentials_with_workers():
    root = Path(__file__).parents[3]
    services = {item["type"]: item for item in yaml.safe_load((root / "render.yaml").read_text())["services"]}
    assert services["web"]["disk"]["mountPath"] == "/data"
    for kind in ("workflow", "cron"):
        keys = {item["key"] for item in services[kind]["envVars"]}
        assert not keys & {"OPENAI_API_KEY", "AICL_DATABASE_URL", "AICL_PAYPAL_CLIENT_SECRET", "AICL_SESSION_SECRET"}
        assert "disk" not in services[kind]
    worker_keys = {item["key"] for item in services["workflow"]["envVars"]}
    assert not worker_keys & {"AICL_SCHEDULER_TOKEN", "RENDER_API_KEY"}
    assert services["cron"]["schedule"] == "* * * * *"
