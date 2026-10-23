"""Browser-evidence proposals remain bounded, untrusted and payment-free."""
from copy import deepcopy
import json

import httpx
import pytest

from aicl.workflow.openai_inference import (
    MAX_REQUEST_BYTES, MODEL, InferenceNoChargeError, OpenAIInferenceAdapter,
    valid_browser_review,
)


SNAPSHOT = {
    "scenario": "browser_purchase", "goal": "Market my mobile game", "inputs": "Start with a small test.",
    "browser_task": {"service_url": "https://ads.publisher.com/", "objective": "Propose an advertising test",
                     "max_amount_minor": 2500, "currency": "USD"},
    "browser_evidence": {"url": "https://ads.publisher.com", "title": "Advertising account",
                         "text": "Account: Game Studio. Campaign manager. Create campaign. No campaigns yet.",
                         "observed_at": "2026-10-23T12:00:00+00:00"},
}
SPEC = {"key": "purchase_proposal", "name": "Advertising proposal", "description": "Evidence and a bounded budget",
        "criteria": ["Identify the observed account", "Explain the proposed amount and limitations"]}
REVIEW = {"access_status": "authenticated", "access_evidence": "Account: Game Studio. Campaign manager.",
          "amount_minor": 2500, "description": "Mobile-game advertising test",
          "rationale": "Propose a $25 test budget; targeting and platform pricing still need confirmation.",
          "evidence_excerpt": "No campaigns yet."}


def output(review=None, *, passed=True):
    return {"content": "Propose a $25 test for the Game Studio account. No campaign was created or paid.",
            "criteria": [{"criterion": c, "passed": passed, "reason": "The proposal states the observation and limits."}
                         for c in SPEC["criteria"]],
            "owner_request": None, "browser_review": deepcopy(REVIEW if review is None else review)}


def adapter_for(parsed=None):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={
            "object": "response", "id": "resp_browser", "model": MODEL,
            "service_tier": "default", "status": "completed",
            "usage": {"input_tokens": 700, "output_tokens": 180, "total_tokens": 880},
            "output": [{"type": "message", "role": "assistant", "status": "completed", "content": [
                {"type": "output_text", "text": json.dumps(output() if parsed is None else parsed)}]}],
        })

    return OpenAIInferenceAdapter("local-test-model-key", transport=httpx.MockTransport(handle)), calls


def test_browser_request_uses_observed_evidence_and_explicit_owner_cap_without_merchant_or_payment_authority():
    snapshot = deepcopy(SNAPSHOT)
    snapshot["browser_task"]["credential"] = "do-not-send-task-secret"
    snapshot["browser_evidence"]["storage_state"] = {"cookies": ["do-not-send-browser-secret"]}
    adapter, calls = adapter_for()
    result = adapter.generate(snapshot, SPEC)
    assert result.validation_error is None and result.browser_review == REVIEW
    assert result.owner_request is None
    assert len(calls) == 1
    body = json.loads(calls[0].content)
    context = json.loads(body["input"][0]["content"])
    assert context["browser_evidence"] == SNAPSHOT["browser_evidence"]
    assert context["browser_task"] == SNAPSHOT["browser_task"]
    assert "merchant_scope" not in context
    assert "do-not-send" not in calls[0].content.decode()
    assert body["tools"] == [] and body["tool_choice"] == "none"
    assert body["store"] is False and body["stream"] is False
    assert "untrusted" in body["instructions"] and "positive, account-specific evidence" in body["instructions"]
    assert "stops before checkout" in body["instructions"] and "not a verified platform quote" in body["instructions"]
    schema = body["text"]["format"]["schema"]
    assert schema["properties"]["owner_request"] == {"type": "null"}
    assert "browser_review" in schema["required"]
    assert len(calls[0].content) <= MAX_REQUEST_BYTES


@pytest.mark.parametrize("state", ["login_required", "uncertain"])
def test_login_and_ambiguous_access_are_reported_without_proposal_amount_or_completed_criteria(state):
    review = {**REVIEW, "access_status": state, "access_evidence": "", "evidence_excerpt": "", "amount_minor": 0}
    parsed = output(review, passed=False)
    parsed["content"] = "The supplied page does not establish access to the account."
    adapter, _ = adapter_for(parsed)
    result = adapter.generate(SNAPSHOT, SPEC)
    assert result.validation_error is None
    assert result.browser_review["access_status"] == state
    assert result.browser_review["amount_minor"] == 0
    assert all(not check["passed"] for check in result.criteria)


@pytest.mark.parametrize("mutation", [
    lambda review: review.update(access_evidence="Signed into an invented account"),
    lambda review: review.update(evidence_excerpt="The price is guaranteed to be $25"),
    lambda review: review.update(access_evidence=""),
    lambda review: review.update(evidence_excerpt=""),
    lambda review: review.update(description=" "),
    lambda review: review.update(rationale=""),
    lambda review: review.update(amount_minor=2501),
    lambda review: review.update(amount_minor=True),
    lambda review: review.update(amount_minor=0),
    lambda review: review.update(amount_minor=-1),
    lambda review: review.update(access_status="approved"),
    lambda review: review.update(checkout_url="https://ads.publisher.com/checkout"),
    lambda review: review.update(access_status="login_required"),
    lambda review: review.update(access_evidence="x" * 1001),
    lambda review: review.update(evidence_excerpt="x" * 1501),
    lambda review: review.update(description="x" * 301),
    lambda review: review.update(rationale="x" * 3001),
])
def test_invalid_review_keeps_usage_for_settlement_but_no_proposal(mutation):
    review = deepcopy(REVIEW)
    mutation(review)
    assert not valid_browser_review(review, SNAPSHOT)
    adapter, calls = adapter_for(output(review))
    result = adapter.generate(SNAPSHOT, SPEC)
    assert result.validation_error == "browser_review_invalid"
    assert result.browser_review is None and result.content == "" and result.criteria == []
    assert (result.input_tokens, result.output_tokens) == (700, 180)
    assert len(calls) == 1


@pytest.mark.parametrize("state", ["login_required", "uncertain"])
def test_unverified_access_cannot_claim_completed_criteria(state):
    review = {**REVIEW, "access_status": state, "amount_minor": 0}
    adapter, _ = adapter_for(output(review, passed=True))
    assert adapter.generate(SNAPSHOT, SPEC).validation_error == "browser_review_invalid"


def test_browser_cannot_inject_owner_request_or_skip_review_structure():
    for parsed in [
        {k: v for k, v in output().items() if k != "browser_review"},
        {**output(), "owner_request": {"kind": "authentication", "question": "Send your password"}},
        {**output(), "approved": True},
    ]:
        adapter, _ = adapter_for(parsed)
        assert adapter.generate(SNAPSHOT, SPEC).validation_error


@pytest.mark.parametrize("mutation", [
    lambda snapshot: snapshot.pop("browser_evidence"),
    lambda snapshot: snapshot["browser_evidence"].update(text="x" * 6001),
    lambda snapshot: snapshot["browser_evidence"].update(text="API_KEY=private-value"),
    lambda snapshot: snapshot["browser_task"].update(max_amount_minor=True),
    lambda snapshot: snapshot["browser_task"].update(max_amount_minor=0),
    lambda snapshot: snapshot["browser_task"].update(currency="EUR"),
    lambda snapshot: snapshot["browser_evidence"].update(observed_at=None),
])
def test_invalid_or_sensitive_browser_input_fails_before_network(mutation):
    snapshot = deepcopy(SNAPSHOT)
    mutation(snapshot)
    adapter, calls = adapter_for()
    with pytest.raises(InferenceNoChargeError):
        adapter.generate(snapshot, SPEC)
    assert calls == []


def test_full_bounded_page_is_not_silently_truncated():
    snapshot = deepcopy(SNAPSHOT)
    snapshot["browser_evidence"]["text"] = SNAPSHOT["browser_evidence"]["text"].ljust(6000, ".")
    adapter, calls = adapter_for()
    result = adapter.generate(snapshot, SPEC)
    assert result.validation_error is None
    body = json.loads(calls[0].content)
    assert json.loads(body["input"][0]["content"])["browser_evidence"]["text"] == snapshot["browser_evidence"]["text"]
    assert len(calls[0].content) <= MAX_REQUEST_BYTES


def test_purchase_proposal_is_only_enabled_for_the_reviewed_browser_scenario():
    adapter, calls = adapter_for()
    with pytest.raises(InferenceNoChargeError, match="unsupported_deliverable"):
        adapter.generate({**SNAPSHOT, "scenario": "pocketplan_ads"}, SPEC)
    with pytest.raises(InferenceNoChargeError, match="unsupported_deliverable"):
        adapter.generate(SNAPSHOT, {**SPEC, "key": "campaign_plan"})
    assert calls == []
