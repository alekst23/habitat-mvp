"""Interactive runtime admission, owner replies and background restart behavior."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
import uuid

import pytest
from fastapi.testclient import TestClient

from aicl.agent_runtime.adapters import ScriptedModel, ScriptedTool, ToolRegistry
from aicl.agent_runtime.chat_service import RuntimeChatService
from aicl.agent_runtime.coordinator import AgentRuntime
from aicl.agent_runtime.contracts import RunDefinition
from aicl.agent_runtime.worker import LocalRuntimeWorker
from aicl.app import create_app, FIXTURE_CSRF_TOKEN
from aicl.chat.assistant_service import AssistantService
from aicl.control.errors import AiclError
from aicl.control.budget import Estimate, MeasuredUsage
from aicl.db import to_iso
from aicl.settings import Settings, SettingsError
from aicl.workflow.service import MockWorkflowService
from test_mock_commerce import ready


def config():
    return {"scenario": "general", "goal": "Explain the supplied design", "inputs": "A single queue keeps work ordered.",
            "cadence": "daily", "timezone": "UTC", "tools": [], "deliverables": [
                {"key": "explanation", "name": "Explanation", "description": "A clear short explanation",
                 "criteria": ["Explain ordering"]}]}


def finish(context):
    assert context["owner_messages"][-1]["text"] == "Engineering"
    return {"schema_version": 1, "output": {"artifacts": [{"local_ref": "explanation", "content": "A queue preserves order."}]},
            "control": {"next": "complete", "artifact_refs": ["explanation"], "criterion_assessments": [
                {"requirement_id": "explanation", "status": "met", "explanation": "Explains ordering"}]}}


def setup(build_env, base_env, *, funded=True):
    env, _, auth, inst, _ = ready(build_env, funded=funded)
    workflow = MockWorkflowService(env.db, env.clock)
    workflow.save_config(auth, inst.id, config(), 1)
    settings = Settings.from_env({**base_env, "AICL_AGENT_RUNTIME_MODE": "openai", "AICL_CHAT_MODEL_MODE": "openai",
                                  "OPENAI_API_KEY": "sk-test-no-network"})
    model = ScriptedModel([{"schema_version": 1, "control": {"next": "wait_owner", "question": "Which audience?",
                                                           "options": ["Engineering", "General"]}}, finish])
    runtime = AgentRuntime(env.db, env.clock, model, ToolRegistry())
    ctx = SimpleNamespace(settings=settings, db=env.db, clock=env.clock, agent_runtime=runtime)
    assistant = AssistantService(ctx)
    session = assistant.new_session(auth)
    return env, ctx, assistant, RuntimeChatService(ctx), workflow, auth, inst, session, model


def test_chat_run_owner_answer_bypasses_setup_and_worker_restarts(build_env, base_env):
    env, ctx, assistant, chat, workflow, auth, inst, session, model = setup(build_env, base_env)
    request_id = str(uuid.uuid4())
    run = chat.start(auth, session, inst.id, request_id, [])
    assert chat.start(auth, session, inst.id, request_id, [])["id"] == run["id"]
    assert model.calls == []
    other_session = assistant.new_session(auth)
    with pytest.raises(AiclError, match="conflict"):
        chat.start(auth, other_session, inst.id, str(uuid.uuid4()), [])
    with pytest.raises(AiclError, match="conflict"):
        workflow.schedule(auth, inst.id, True)
    # Editing the configuration must not change the active engine's ownership.
    current = workflow.config(auth, inst.id)
    workflow.save_config(auth, inst.id, {**config(), "scenario": "generic"}, current["version"])
    with pytest.raises(AiclError, match="conflict"):
        workflow.schedule(auth, inst.id, True)
    first_worker = LocalRuntimeWorker(ctx.agent_runtime)
    assert first_worker.tick() == 1
    waiting = assistant.view(auth, session)["runtime_run"]
    assert waiting["status"] == "waiting_owner" and first_worker.tick() == 0
    chat.control(auth, session, run["id"], "pause")
    answer_key = str(uuid.uuid4())
    for _ in range(2):
        asyncio.run(assistant.message(auth, session, answer_key, "Engineering", run_id=run["id"], question_id=waiting["question"]["id"]))
    assert assistant.view(auth, session)["runtime_run"]["status"] == "paused"
    assert first_worker.tick() == 0
    chat.control(auth, session, run["id"], "resume")
    restarted = AgentRuntime(env.db, env.clock, ScriptedModel([finish]), ToolRegistry())
    assert LocalRuntimeWorker(restarted).tick() == 1
    completed = assistant.view(auth, session)
    assert completed["runtime_run"]["status"] == "completed"
    assert completed["runtime_run"]["artifacts"][0]["content"] == "A queue preserves order."
    assert len(model.calls) == 1
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM assistant_turn").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM assistant_inference_attempt").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM agent_event WHERE kind='owner_answer'").fetchone()[0] == 1


def test_runtime_http_scope_csrf_and_gets_do_not_dispatch(build_env, base_env, monkeypatch):
    env, ctx, _, _, _, auth, inst, _, model = setup(build_env, base_env)
    from aicl.agent_runtime import factory
    monkeypatch.setattr(factory, "build_runtime", lambda _ctx: AgentRuntime(_ctx.db, _ctx.clock, model, ToolRegistry()))
    settings = ctx.settings.model_copy(update={"environment": "test", "test_mode": True, "database_url": env.db.database_url})
    app = create_app(settings)
    app.state.ctx.auth_provider.contexts["runtime-test-cookie"] = auth
    app.state.ctx.csrf_verifier.fixture_session_ids |= {auth.session_id}
    client = TestClient(app, base_url="http://127.0.0.1:4173")
    client.cookies.set("aicl_session", "runtime-test-cookie")
    session = AssistantService(app.state.ctx).new_session(auth)
    # Untouched legacy sessions retain API compatibility until opened in the
    # canonical workspace; the new HTTP journey is covered in workspace_routes.
    body = {"chat_session_id": session, "instance_id": inst.id, "request_id": str(uuid.uuid4()), "tools": []}
    assert client.post("/chat/runs/start", json=body).status_code == 403
    headers = {"X-CSRF-Token": FIXTURE_CSRF_TOKEN, "Origin": "http://127.0.0.1:4173"}
    response = client.post("/chat/runs/start", json=body, headers=headers)
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    assert client.get("/chat/runs/status", params={"session_id": session}).json()["runtime_run"]["status"] == "queued"
    assert model.calls == []
    foreign = replace(auth, owner_id=str(uuid.uuid4()))
    app.state.ctx.auth_provider.contexts["runtime-test-cookie"] = foreign
    assert client.get("/chat/runs/status", params={"session_id": session}).status_code == 404
    assert client.post(f"/chat/runs/{run_id}/cancel", json={"chat_session_id": session}, headers=headers).status_code == 404
    app.state.ctx.auth_provider.contexts["runtime-test-cookie"] = auth
    assert client.post(f"/chat/runs/{run_id}/cancel", json={"chat_session_id": session}, headers=headers).status_code == 200
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 0 and model.calls == []


def test_runtime_requires_explicit_local_enablement(base_env):
    assert Settings.from_env(base_env).agent_runtime_mode == "off"
    with pytest.raises(SettingsError):
        Settings.from_env({**base_env, "AICL_AGENT_RUNTIME_MODE": "openai"})
    settings = Settings.from_env({**base_env, "AICL_AGENT_RUNTIME_MODE": "openai", "AICL_CHAT_MODEL_MODE": "openai",
                                  "OPENAI_API_KEY": "sk-test-no-network"})
    with pytest.raises(SettingsError):
        Settings.model_validate(settings.model_copy(update={"environment": "production"}).model_dump())


def spend_fixture_credit(env, instance_id, amount):
    """A settled earlier operation consumes credit without changing ledger history."""
    with env.db.transaction() as conn:
        identity = str(uuid.uuid4())
        hold = env.budget.reserve(conn, instance_id, identity, Estimate(0, 0, 0))
        env.budget.settle(conn, hold.id, MeasuredUsage(0, 0, 0))
        conn.execute("INSERT INTO mock_commerce_ledger "
                     "(id,instance_id,kind,delta_micro_usd,reference,hold_id,created_at) "
                     "VALUES (?,?,'inference_usage',?,?,?,?)",
                     (identity, instance_id, -amount, 'inference:' + identity, hold.id, hold.created_at.isoformat()))


@pytest.mark.parametrize("balance", [0, 399])
def test_chat_funding_preflight_prevents_unfunded_draft_activation_and_run(build_env, base_env, balance):
    env, ctx, _, chat, _, auth, inst, session, model = setup(build_env, base_env, funded=bool(balance))
    model.estimate = Estimate(100, 100, 0)  # The fixture price table bounds this decision at 400 microUSD.
    if balance:
        spend_fixture_credit(env, inst.id, 5_000_000 - balance)
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_instance SET lifecycle='draft' WHERE id=?", (inst.id,))
        before = conn.total_changes
        readiness = chat.view(auth, session)["runtime_candidates"][0]["readiness"]
        assert conn.total_changes == before
    assert readiness == {"ready": False, "balance_micro_usd": balance, "required_micro_usd": 400, "funding_order_id": None,
                         "blockers": [{"reason": "credit_insufficient", "message":
                                       "Add service credit to cover the next step before starting or resuming work."}]}
    with pytest.raises(AiclError) as caught:
        chat.start(auth, session, inst.id, str(uuid.uuid4()), [])
    assert caught.value.extra["reason"] == "credit_insufficient"
    with env.db.reader() as conn:
        assert conn.execute("SELECT lifecycle FROM agent_instance WHERE id=?", (inst.id,)).fetchone()[0] == "draft"
        for table in ("agent_run", "agent_chat_run", "agent_wakeup", "agent_runtime_hold"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 0 and model.calls == []
    commerce = ctx.agent_runtime.accounting.commerce
    order = commerce.create_topup(auth, inst.id, 500, "fund-chat")
    commerce.select_payment_buyer(auth, order["id"], "demo-buyer")
    commerce.checkout(auth, order["id"], "complete")
    assert chat.view(auth, session)["runtime_candidates"][0]["readiness"]["ready"]
    run = chat.start(auth, session, inst.id, str(uuid.uuid4()), [])
    assert run["status"] == "queued" and model.calls == []
    with env.db.reader() as conn:
        assert conn.execute("SELECT lifecycle FROM agent_instance WHERE id=?", (inst.id,)).fetchone()[0] == "active"
        assert conn.execute("SELECT COUNT(*) FROM agent_runtime_hold").fetchone()[0] == 0


@pytest.mark.parametrize("status", ["paused", "blocked"])
def test_chat_resume_prices_next_pending_tool_and_preserves_state_until_funded(build_env, base_env, status):
    env, ctx, _, chat, _, auth, inst, session, model = setup(build_env, base_env)
    model.estimate = Estimate(100, 100, 0)
    model.responses = [{"schema_version": 1, "actions": [{"name": "fixture.read", "arguments": {"key": "page"}}],
                        "control": {"next": "continue"}}]
    tool = ScriptedTool("fixture.read", {"page": "source text"})
    tool.estimate = Estimate(0, 0, 1)
    tool.descriptor = {"name": "fixture.read"}
    ctx.agent_runtime.tools = ToolRegistry([tool]).with_artifact_reader(ctx.agent_runtime.repo)
    request_id = str(uuid.uuid4())
    # This is a local compute-priced fixture, not an authorization to run web
    # requests from private context. Web work has its own approved prelude.
    definition = RunDefinition(objective="Read the supplied fixture", requirements=[{"id": "r", "text": "Read"}],
                               allowed_tools=["fixture.read"])
    run = ctx.agent_runtime.create_run(auth, inst.id, request_id, definition)
    with env.db.transaction() as conn:
        conn.execute("INSERT INTO agent_chat_run(session_id,run_id,created_at) VALUES (?,?,?)",
                     (session, run["id"], to_iso(env.clock.now())))
    ctx.agent_runtime.advance_slice(auth, run["id"], max_operations=1)
    chat.control(auth, session, run["id"], "pause")
    if status == "blocked":
        with env.db.transaction() as conn:
            current = ctx.agent_runtime.repo.owned_run(conn, auth, run["id"])
            ctx.agent_runtime._save(conn, auth, current, ctx.agent_runtime._checkpoint(conn, auth, current),
                                    status="blocked", reason="credit_insufficient")
    spend_fixture_credit(env, inst.id, 5_000_000 - 1000)
    with env.db.transaction() as conn:
        before = conn.total_changes
        view = chat.view(auth, session)["runtime_run"]
        assert conn.total_changes == before
    assert view["instance_id"] == inst.id
    assert view["readiness"]["required_micro_usd"] == 5000
    assert view["readiness"]["balance_micro_usd"] == 1000
    assert not view["can_resume"]
    with pytest.raises(AiclError) as caught:
        chat.control(auth, session, run["id"], "resume")
    assert caught.value.extra["reason"] == "credit_insufficient"
    assert chat.view(auth, session)["runtime_run"]["version"] == view["version"]
    # Admission replay must remain successful even after the account becomes unfunded.
    assert ctx.agent_runtime.create_run(auth, inst.id, request_id, definition)["id"] == run["id"]
    assert not tool.calls
    # New owner context supersedes a prepared tool; the next dispatch is the model.
    chat.message(auth, session, str(uuid.uuid4()), "Use the supplied context instead.", run_id=run["id"])
    assert chat.view(auth, session)["runtime_run"]["readiness"]["required_micro_usd"] == 400
    assert chat.control(auth, session, run["id"], "resume")["status"] == "queued"


def test_chat_readiness_uses_held_credit_limits_and_adapter_price_version(build_env, base_env):
    env, ctx, _, chat, _, auth, inst, session, model = setup(build_env, base_env)
    model.estimate = Estimate(100, 100, 0)
    spend_fixture_credit(env, inst.id, 5_000_000 - 600)
    with env.db.transaction() as conn:
        hold = ctx.agent_runtime.accounting.reserve(conn, auth, inst.id, "other-paid-operation", Estimate(100, 100, 0), 1000000, 0)
    view = chat.view(auth, session)["runtime_candidates"][0]["readiness"]
    assert view["balance_micro_usd"] == 200 and not view["ready"]
    with env.db.transaction() as conn:
        ctx.agent_runtime.accounting.release(conn, hold.id)
        conn.execute("UPDATE agent_instance SET inference_daily_micro_usd=399 WHERE id=?", (inst.id,))
    view = chat.view(auth, session)["runtime_candidates"][0]["readiness"]
    assert [item["reason"] for item in view["blockers"]] == ["budget_exhausted"]
    model.price_version = "missing-adapter-price"
    view = chat.view(auth, session)["runtime_candidates"][0]["readiness"]
    assert view["required_micro_usd"] is None
    assert "price_unavailable" in [item["reason"] for item in view["blockers"]]


def test_chat_readiness_recovers_only_unfinished_owned_topups(build_env, base_env):
    env, ctx, _, chat, _, auth, inst, session, _ = setup(build_env, base_env, funded=False)
    commerce = ctx.agent_runtime.accounting.commerce
    first = commerce.create_topup(auth, inst.id, 500, "fund-first")
    assert chat.view(auth, session)["runtime_candidates"][0]["readiness"]["funding_order_id"] == first["id"]
    commerce.select_payment_buyer(auth, first["id"], "demo-buyer")
    commerce.checkout(auth, first["id"], "pending")
    with env.db.transaction() as conn:
        before = conn.total_changes
        assert chat.view(auth, session)["runtime_candidates"][0]["readiness"]["funding_order_id"] == first["id"]
        assert conn.total_changes == before
    commerce.checkout(auth, first["id"], "complete")
    assert chat.view(auth, session)["runtime_candidates"][0]["readiness"]["funding_order_id"] is None
    second = commerce.create_topup(auth, inst.id, 500, "fund-second")
    commerce.select_payment_buyer(auth, second["id"], "demo-buyer")
    assert chat.view(auth, session)["runtime_candidates"][0]["readiness"]["funding_order_id"] == second["id"]
    commerce.checkout(auth, second["id"], "cancel")
    other_auth, other_inst = env.new_instance(capabilities=("inference",))
    commerce.create_topup(other_auth, other_inst.id, 500, "other-owner-fund")
    assert chat.view(auth, session)["runtime_candidates"][0]["readiness"]["funding_order_id"] is None
