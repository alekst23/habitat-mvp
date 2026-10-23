"""Scheduled browser work pauses durably and never performs checkout."""
from copy import deepcopy
import json

import httpx
import pytest

from render_worker.client import AICLClient, ClientConfig, MachineAPIError
from render_worker.runner import execute


ATTEMPT = {
    "id": "attempt-1",
    "snapshot": {"scenario": "browser_purchase", "goal": "Private campaign goal"},
    "spec": {"criteria": ["Explain the advertising purchase"]},
}
RESULT = {
    "content": "Private campaign proposal",
    "criteria": [{"criterion": "Explain the advertising purchase", "passed": True, "reason": "Explained"}],
}


class BrowserWorkAPI:
    """Strict machine API fake: browser preparation never grants payment tools."""

    def __init__(self, state="waiting_owner", *, repeat=False):
        self.state, self.repeat = state, repeat
        self.attempt = deepcopy(ATTEMPT)
        self.calls = []

    def claim(self, dispatch, run):
        self.calls.append(("claim", dispatch, run))
        return {"attempts": [deepcopy(self.attempt)]}

    def browser_prepare(self, dispatch, run, attempt):
        self.calls.append(("browser_prepare", dispatch, run, attempt))
        return {"state": self.state, "evidence": "Private browser page text", "request_id": "login-request-1"}

    def generate(self, dispatch, run, attempt):
        assert self.state == "ready", "inference cannot run before browser preparation"
        self.calls.append(("generate", dispatch, run, attempt))
        return {"state": "generated", "result": deepcopy(RESULT)}

    def complete_attempt(self, dispatch, run, attempt, validation):
        self.calls.append(("complete", dispatch, run, attempt, validation))
        return {"state": "completed"}

    def finish(self, dispatch, run):
        self.calls.append(("finish", dispatch, run))
        return {
            "state": "waiting_purchase" if self.state == "ready" else self.state,
            "attempts": [deepcopy(self.attempt)] if self.repeat else [],
            "job_ids": ["job-1"],
        }


@pytest.mark.parametrize("state", ["waiting_owner", "blocked"])
def test_browser_preflight_persists_pause_and_finishes_without_inference(state):
    api, events = BrowserWorkAPI(state), []
    result = execute(api, "dispatch-1", "trn-1", emit=events.append)
    assert result["state"] == state
    assert [call[0] for call in api.calls] == ["claim", "browser_prepare", "finish"]
    assert events == [{"stage": "browser_prepared", "dispatch_id": "dispatch-1",
                       "attempt_id": "attempt-1", "state": state}]
    assert "Private" not in repr(result) + repr(events)


def test_owner_sign_in_resumes_same_attempt_and_later_schedule_reuses_preflight():
    api, events = BrowserWorkAPI(), []
    assert execute(api, "dispatch-1", "trn-1")["state"] == "waiting_owner"

    # AICL has resolved the request and schedules the same durable work attempt.
    api.calls.clear()
    api.state = "ready"
    resumed = execute(api, "dispatch-2", "trn-2", emit=events.append)
    assert resumed["state"] == "waiting_purchase"
    assert [call[0] for call in api.calls] == ["claim", "browser_prepare", "generate", "complete", "finish"]
    assert api.calls[1][3] == api.calls[2][3] == "attempt-1"
    assert api.calls[3][-1] == {"passed": True}

    # A new scheduled job also uses the broker, which decides whether saved
    # authentication is still valid; the worker cannot skip that authorization.
    api.calls.clear()
    api.attempt["id"] = "attempt-2"
    scheduled = execute(api, "dispatch-3", "trn-3", emit=events.append)
    assert scheduled["state"] == "waiting_purchase"
    assert api.calls[1] == ("browser_prepare", "dispatch-3", "trn-3", "attempt-2")
    assert [call[0] for call in api.calls] == ["claim", "browser_prepare", "generate", "complete", "finish"]
    assert "Private" not in repr(events) + repr(resumed) + repr(scheduled)


@pytest.mark.parametrize("response", [{}, {"state": "unknown"}, {"state": "completed"}, [], None])
def test_unknown_browser_preparation_cannot_generate_or_retry(response):
    api = BrowserWorkAPI()
    calls = []

    def prepare(*args):
        calls.append(args)
        return response

    api.browser_prepare = prepare
    with pytest.raises(MachineAPIError, match="invalid browser preparation state"):
        execute(api, "dispatch-1", "trn-1")
    assert len(calls) == 1
    assert [call[0] for call in api.calls] == ["claim"]


def test_lost_browser_prepare_response_is_not_resent_within_worker_task():
    api, calls = BrowserWorkAPI(), []

    def prepare(*args):
        calls.append(args)
        raise MachineAPIError("AICL machine request outcome is unknown")

    api.browser_prepare = prepare
    with pytest.raises(MachineAPIError, match="outcome is unknown"):
        execute(api, "dispatch-1", "trn-1")
    assert len(calls) == 1
    assert [call[0] for call in api.calls] == ["claim"]


def test_repeated_waiting_attempt_is_bounded_instead_of_polling_owner():
    api = BrowserWorkAPI(repeat=True)
    with pytest.raises(MachineAPIError, match="repeated an unfinished attempt"):
        execute(api, "dispatch-1", "trn-1")
    assert [call[0] for call in api.calls] == ["claim", "browser_prepare", "finish"]


def test_browser_prepare_client_binds_dispatch_task_and_attempt_without_credentials():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"state": "waiting_owner"})

    config = ClientConfig("https://aicl.example", "worker_" + "x" * 40)
    with AICLClient(config, transport=httpx.MockTransport(handle)) as client:
        assert client.browser_prepare("dispatch-1", "trn-1", "attempt-1") == {"state": "waiting_owner"}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/internal/render/jobs/dispatch-1/browser/prepare"
    assert json.loads(request.content) == {"task_run_id": "trn-1", "attempt_id": "attempt-1"}
