"""Paid-turn claims, owner review, usage holds and authenticated HTTP boundaries."""
import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from aicl.app import create_app
from aicl.chat.assistant_meter import AssistantMeter, MAX_INPUT, MAX_OUTPUT, RESERVATION, allowance
from aicl.chat.assistant_service import AssistantService
from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError
from aicl.settings import Settings, SettingsError
from aicl.workflow.ad_scenario import pocketplan_preset


def setup(env, base_env, model=None, cap=1_000_000):
    settings = Settings.from_env({**base_env, "AICL_CHAT_MODEL_MODE": "openai", "OPENAI_API_KEY": "sk-test-not-a-real-key",
                                  "AICL_ASSISTANT_MAX_SPEND_MICRO_USD": str(cap)})
    ctx = SimpleNamespace(db=env.db, clock=env.clock, settings=settings)
    owner = str(uuid.uuid4())
    auth = AuthContext(owner, owner, str(uuid.uuid4()), env.clock.now().replace(year=2099))
    service = AssistantService(ctx, model=model)
    return service, auth, service.new_session(auth)


def proposal():
    preset = pocketplan_preset()
    return {"name": "App campaign planner", **{k: preset[k] for k in ("goal", "inputs", "cadence", "timezone")},
            "budget_notes": "Owner will review funding and limits.",
            "deliverables": [{k: d[k] for k in ("key", "name", "description", "criteria")} for d in preset["deliverables"]]}


class ToolModel:
    def __init__(self):
        self.calls = 0

    async def run(self, history, *, tools, invoke, meter):
        self.calls += 1
        attempt = meter.reserve()
        meter.settle(attempt, "resp_test", "gpt-6-sol", 100, 50)
        assert invoke("confirm", {})["error"] == "denied"
        invoke("get_supported_capabilities", {})
        invoke("save_agent_proposal", proposal())
        return "Here is your proposed agent. Review its goals and criteria before creating it."


def test_model_proposal_is_not_approval_and_paid_turn_replay_is_free(build_env, base_env):
    model = ToolModel()
    service, auth, session = setup(build_env(), base_env, model)
    request_id = str(uuid.uuid4())
    first = asyncio.run(service.message(auth, session, request_id, "Help market PocketPlan"))
    second = asyncio.run(service.message(auth, session, request_id, "Help market PocketPlan"))
    assert first["text"] == second["text"] and second["replayed"] and model.calls == 1
    with service.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_instance").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM assistant_inference_attempt").fetchone()[0] == 1
    view = service.view(auth, session)
    assert view["usage"]["spent_micro_usd"] == 700 and view["usage"]["held_micro_usd"] == 0
    draft = view["proposal"]
    created = service.confirm(auth, session, draft["id"], draft["version"])
    assert service.confirm(auth, session, draft["id"], draft["version"]) == created
    assert service.view(auth, session)["proposal"]["state"] == "committed"
    with service.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_instance").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM assistant_message WHERE role='assistant'").fetchone()[0] == 2
    with pytest.raises(AiclError, match="conflict"):
        asyncio.run(service.message(auth, session, request_id, "changed payload"))


def test_concurrent_message_is_claimed_before_model_dispatch(build_env, base_env):
    async def scenario():
        entered, finish = asyncio.Event(), asyncio.Event()
        class Blocking:
            calls = 0
            async def run(self, history, *, tools, invoke, meter):
                self.calls += 1
                attempt = meter.reserve()
                entered.set()
                await finish.wait()
                meter.settle(attempt, "resp_test", "gpt-6-sol", 10, 10)
                return "Who is the app for?"
        model = Blocking()
        service, auth, session = setup(build_env(), base_env, model)
        key = str(uuid.uuid4())
        original = asyncio.create_task(service.message(auth, session, key, "Help me market my app"))
        await entered.wait()
        for duplicate in (key, str(uuid.uuid4())):
            with pytest.raises(AiclError, match="conflict"):
                await service.message(auth, session, duplicate, "Help me market my app")
        finish.set()
        await original
        assert model.calls == 1
    asyncio.run(scenario())


def test_unknown_charge_is_held_and_never_retried_or_funded_by_agent_credit(build_env, base_env):
    class LostReply:
        async def run(self, history, *, tools, invoke, meter):
            meter.reserve()
            raise RuntimeError("provider exception may include credentials and must not escape")
    service, auth, session = setup(build_env(), base_env, LostReply())
    key = str(uuid.uuid4())
    with pytest.raises(AiclError) as failure:
        asyncio.run(service.message(auth, session, key, "help"))
    assert "credentials" not in failure.value.message
    usage = allowance(service.db, 1_000_000)
    assert usage["held_micro_usd"] == RESERVATION and usage["unknown"]
    with pytest.raises(AiclError):
        asyncio.run(service.message(auth, session, key, "help"))
    service.model = ToolModel()
    with pytest.raises(AiclError):
        asyncio.run(service.message(auth, session, str(uuid.uuid4()), "try another"))
    with service.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM assistant_inference_attempt").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM budget_hold").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM mock_commerce_ledger").fetchone()[0] == 0


def test_allowance_and_usage_bound_stop_before_another_dispatch(build_env, base_env):
    service, auth, session = setup(build_env(), base_env, ToolModel(), cap=RESERVATION - 1)
    with pytest.raises(AiclError):
        asyncio.run(service.message(auth, session, str(uuid.uuid4()), "help"))
    assert allowance(service.db, RESERVATION - 1)["spent_micro_usd"] == 0
    service.ctx.settings = service.ctx.settings.model_copy(update={"assistant_max_spend_micro_usd": 1_000_000})
    turn, _ = service._claim(auth, session, str(uuid.uuid4()), "bounded usage")
    meter = AssistantMeter(service.ctx, auth, turn)
    attempt = meter.reserve()
    with pytest.raises(AiclError):
        meter.settle(attempt, "resp_over", "gpt-6-sol", MAX_INPUT + 1, MAX_OUTPUT)
    assert allowance(service.db, 1_000_000)["spent_micro_usd"] == RESERVATION + 2
    with pytest.raises(AiclError):
        meter.reserve()


def test_session_isolation_and_confirmation_during_running_turn(build_env, base_env):
    service, auth, session = setup(build_env(), base_env, ToolModel())
    other = AuthContext(str(uuid.uuid4()), auth.tenant_id, "different", auth.expires_at)
    with pytest.raises(AiclError, match="not_found"):
        service.view(other, session)
    with pytest.raises(AiclError, match="not_found"):
        asyncio.run(service.message(other, session, str(uuid.uuid4()), "help"))
    asyncio.run(service.message(auth, session, str(uuid.uuid4()), "help"))
    pending = service.view(auth, session)["proposal"]
    service._claim(auth, session, str(uuid.uuid4()), "change its goal")
    with pytest.raises(AiclError, match="conflict"):
        service.confirm(auth, session, pending["id"], pending["version"])


def test_http_assistant_auth_csrf_proposal_review_and_no_model_on_get(base_env, monkeypatch):
    from aicl.chat import assistant_routes
    model = ToolModel()
    monkeypatch.setattr(assistant_routes, "AssistantService", lambda ctx: AssistantService(ctx, model=model))
    settings = Settings.from_env({**base_env, "AICL_ENVIRONMENT": "test", "AICL_TEST_MODE": "1",
                                  "AICL_CHAT_MODEL_MODE": "openai", "OPENAI_API_KEY": "sk-test-not-a-real-key"})
    with TestClient(create_app(settings), base_url="http://127.0.0.1:4173") as client:
        assert client.get("/chat", follow_redirects=False).status_code == 303
        seeded = client.post("/__test__/seed-session", json={"fixture": "owner-a"}).json()
        page = client.get("/chat")
        session = str(page.url).split("session=")[1]
        assert "What would you like to achieve?" in page.text and model.calls == 0
        assert str(client.get("/chat").url).endswith("session=" + session)
        fresh = str(client.get("/chat?new=1").url).split("session=")[1]
        assert fresh != session and model.calls == 0
        body = {"chat_session_id": session, "request_id": str(uuid.uuid4()), "text": "Help me market my app"}
        assert client.post("/chat/messages", json=body).status_code == 403
        headers = {"X-CSRF-Token": seeded["csrf_token"], "Origin": "http://127.0.0.1:4173"}
        result = client.post("/chat/messages", json=body, headers=headers)
        assert result.status_code == 200, result.text
        draft = result.json()["proposal"]
        url = f"/chat/proposals/{draft['id']}/confirm"
        assert client.post(url, json={"chat_session_id": session, "version": draft["version"]}).status_code == 403
        applied = client.post(url, headers=headers, json={"chat_session_id": session, "version": draft["version"]})
        assert applied.status_code == 200
        assert client.get("/chat?session=" + session).status_code == 200 and model.calls == 1
        # A different authenticated owner cannot confirm or read this conversation.
        client.post("/__test__/seed-session", json={"fixture": "owner-b"})
        assert client.post(url, headers=headers, json={"chat_session_id": session, "version": draft["version"]}).status_code == 404


def test_live_chat_requires_valid_key_and_workflow_profile(base_env):
    with pytest.raises(SettingsError):
        Settings.from_env({**base_env, "AICL_CHAT_MODEL_MODE": "openai"})
    settings = Settings.from_env({**base_env, "AICL_CHAT_MODEL_MODE": "openai", "OPENAI_API_KEY": "sk-test-not-a-real-key"})
    assert settings.chat_model_mode == "openai" and settings.inference_mode == "mock"
    with pytest.raises(SettingsError):
        Settings.model_validate({**settings.model_dump(), "chat_model_mode": "unrecognized"})
