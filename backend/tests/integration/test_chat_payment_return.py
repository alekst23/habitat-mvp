"""Funding checkout returns to its owned conversation without starting work."""

import uuid

import pytest

from aicl.agent_runtime.adapters import ScriptedModel, ToolRegistry
from aicl.agent_runtime.coordinator import AgentRuntime
from aicl.chat.assistant_service import AssistantService
from aicl.db import to_iso
from test_owner_journey_pages import _create, _post


def _order(web, *, session=None, request_id=None):
    instance_id, commerce = _create(web)
    session = session or AssistantService(web.app.state.ctx).new_session(web.auth_a)
    order = commerce.create_topup(web.auth_a, instance_id, 500,
                                  request_id or f"chat:{session}:{uuid.uuid4()}")
    return instance_id, commerce, session, f"/commerce/orders/{order['id']}"


def _link_run(web, session, instance_id):
    ctx = web.app.state.ctx
    model = ScriptedModel([])
    runtime = AgentRuntime(ctx.db, ctx.clock, model, ToolRegistry())
    run = runtime.create_run(web.auth_a, instance_id, "payment-return-test", {
        "objective": "Explain the supplied information",
        "requirements": [{"id": "report", "text": "A clear explanation"}],
    })
    runtime.pause(web.auth_a, run["id"])
    with ctx.db.transaction() as conn:
        conn.execute("INSERT INTO agent_chat_run VALUES (?,?,?)", (session, run["id"], to_iso(ctx.clock.now())))
    return runtime, run, model


def test_completed_chat_funding_returns_to_same_session_without_resuming(web):
    instance_id, commerce, session, path = _order(web)
    runtime, run, model = _link_run(web, session, instance_id)
    checkout = web.owner_a.get(path)
    assert f'href="/chat?session={session}&amp;instance={instance_id}"' in checkout.text
    assert "Return to conversation" in checkout.text

    for _ in range(2):
        paid = _post(web, path + "/checkout", outcome="complete", buyer_id="demo-buyer")
        assert paid.headers["location"] == f"/chat?session={session}&instance={instance_id}&notice=funded"
    assert commerce.dashboard(web.auth_a, instance_id)["balance_micro_usd"] == 5_000_000
    assert runtime.read(web.auth_a, run["id"])["status"] == "paused"
    assert model.calls == []
    receipt = web.owner_a.get(path)
    assert f'href="/chat?session={session}&amp;instance={instance_id}"' in receipt.text
    assert "Return to conversation" in receipt.text


@pytest.mark.parametrize("outcome", ["pending", "cancel"])
def test_unfinished_chat_funding_keeps_checkout_and_conversation_link(web, outcome):
    instance_id, commerce, session, path = _order(web)
    response = _post(web, path + "/checkout", outcome=outcome, buyer_id="demo-buyer")
    assert response.headers["location"] == path
    page = web.owner_a.get(path)
    assert f'href="/chat?session={session}&amp;instance={instance_id}"' in page.text
    assert "Return to conversation" in page.text
    assert commerce.dashboard(web.auth_a, instance_id)["balance_micro_usd"] == 0
    with web.app.state.ctx.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 0


@pytest.mark.parametrize("invalid", ["foreign-session", "missing-session", "malformed-key", "mismatched-run"])
def test_funding_return_rejects_unowned_or_mismatched_conversations(web, invalid):
    ctx = web.app.state.ctx
    assistant = AssistantService(ctx)
    session = assistant.new_session(web.auth_b if invalid == "foreign-session" else web.auth_a)
    if invalid == "missing-session":
        session = str(uuid.uuid4())
    key = f"chat:{session}:{uuid.uuid4()}" if invalid != "malformed-key" else f"chat:{session}:invalid"
    instance_id, _, _, path = _order(web, session=session, request_id=key)
    if invalid == "mismatched-run":
        response = web.tool(web.owner_a, "create_instance", {
            "idempotency_key": "wiz_" + "a" * 32, "template_id": "default",
            "name": "Different agent", "instructions": "Separate work", "enabled_capabilities": [],
        })
        _link_run(web, session, response.json()["instance"]["id"])
    assert "Return to conversation" not in web.owner_a.get(path).text
    assert web.owner_b.get(path).status_code == 404
    paid = _post(web, path + "/checkout", outcome="complete", buyer_id="demo-buyer")
    assert paid.headers["location"].startswith(f"/instances/{instance_id}?")
    assert paid.headers["location"].endswith("#setup")


def test_existing_owned_agent_can_return_before_a_run_is_created(web):
    instance_id, commerce, session, path = _order(web)
    paid = _post(web, path + "/checkout", outcome="complete", buyer_id="demo-buyer")
    assert paid.headers["location"] == f"/chat?session={session}&instance={instance_id}&notice=funded"
    assert commerce.dashboard(web.auth_a, instance_id)["balance_micro_usd"] == 5_000_000
    with web.app.state.ctx.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 0
