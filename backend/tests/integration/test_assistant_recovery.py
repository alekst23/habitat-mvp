"""Regression coverage for restart recovery and bounded SDK conversation history."""

import asyncio
import json
import uuid
from datetime import timedelta

import httpx2
import pytest

from aicl.chat.assistant_meter import AssistantMeter, RESERVATION
from aicl.chat.assistant_service import AssistantService
from aicl.chat.assistant_tools import AssistantTools
from aicl.chat.sdk_agent import SDKInterviewModel
from aicl.control.errors import AiclError
from aicl.db import to_iso
from test_assistant_service import proposal, setup


def _offline_reply(requests):
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json={
            "id": "resp_recovery", "object": "response", "created_at": 1760000000,
            "status": "completed", "model": "gpt-6-sol", "service_tier": "default",
            "parallel_tool_calls": False, "error": None, "incomplete_details": None,
            "output": [{"type": "message", "id": "msg_recovery", "role": "assistant",
                        "status": "completed", "content": [{"type": "output_text",
                        "text": "Your proposal is still available for review.", "annotations": []}]}],
            "usage": {"input_tokens": 140, "output_tokens": 25, "total_tokens": 165,
                      "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                      "output_tokens_details": {"reasoning_tokens": 0}},
        })
    return SDKInterviewModel("test-key-never-real", transport=httpx2.MockTransport(respond))


def _interrupted_turn(service, auth, session):
    request_id = str(uuid.uuid4())
    turn_id, _ = service._claim(auth, session, request_id, "Continue preparing the proposal")
    attempt_id = AssistantMeter(service.ctx, auth, turn_id).reserve()
    service.clock.advance(timedelta(minutes=6))
    return request_id, turn_id, attempt_id


def test_expired_demo_blocks_stale_auth_context_before_provider_request(build_env, base_env):
    requests = []
    service, auth, session = setup(build_env(), base_env, _offline_reply(requests))
    now = to_iso(service.clock.now())
    assert auth.expires_at > service.clock.now()
    with service.db.transaction() as conn:
        conn.execute("INSERT INTO owner(id,email_hash,created_at) VALUES (?,?,?)",
                     (auth.owner_id, auth.owner_id, now))
        conn.execute("INSERT INTO judge_demo_workspace(owner_id,entry_nonce_hash,created_at,expires_at) VALUES (?,?,?,?)",
                     (auth.owner_id, str(uuid.uuid4()), now, now))
    with pytest.raises(AiclError) as failure:
        asyncio.run(service.message(auth, session, str(uuid.uuid4()), "Continue the setup"))
    assert "expired" in failure.value.message
    assert requests == []
    with service.db.reader() as conn:
        assert conn.execute("SELECT count(*) FROM assistant_inference_attempt").fetchone()[0] == 0


def test_stale_turn_does_not_block_owner_confirmation_or_release_unknown_charge(build_env, base_env):
    requests = []
    service, auth, session = setup(build_env(), base_env, _offline_reply(requests))
    tools = AssistantTools(service.ctx, auth, session)
    draft = tools.invoke("save_agent_proposal", proposal())["proposal"]
    request_id, turn_id, attempt_id = _interrupted_turn(service, auth, session)
    restarted = AssistantService(service.ctx, model=_offline_reply(requests))

    created = restarted.confirm(auth, session, draft["id"], draft["version"])
    assert restarted.confirm(auth, session, draft["id"], draft["version"]) == created
    with pytest.raises(AiclError) as replay:
        asyncio.run(restarted.message(auth, session, request_id, "Continue preparing the proposal"))
    assert replay.value.error == "unavailable"
    usage = restarted.view(auth, session)["usage"]
    assert usage["unknown"] and usage["held_micro_usd"] == RESERVATION
    assert usage["spent_micro_usd"] == 0 and not requests
    with service.db.reader() as conn:
        assert conn.execute("SELECT state FROM assistant_turn WHERE id=?", (turn_id,)).fetchone()[0] == "unknown"
        assert conn.execute("SELECT state FROM assistant_inference_attempt WHERE id=?", (attempt_id,)).fetchone()[0] == "unknown"
        assert conn.execute("SELECT count(*) FROM agent_instance").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM assistant_inference_attempt").fetchone()[0] == 1


def test_stale_hold_recovery_persists_when_another_conversation_is_denied(build_env, base_env):
    requests = []
    service, auth, session = setup(build_env(), base_env, _offline_reply(requests))
    _, _, attempt_id = _interrupted_turn(service, auth, session)
    restarted = AssistantService(service.ctx, model=_offline_reply(requests))
    other_session = restarted.new_session(auth)

    with pytest.raises(AiclError) as failure:
        asyncio.run(restarted.message(auth, other_session, str(uuid.uuid4()), "Which agents need attention?"))
    assert "unresolved charge" in failure.value.message
    usage = restarted.view(auth, other_session)["usage"]
    assert usage["unknown"] and usage["held_micro_usd"] == RESERVATION
    assert usage["spent_micro_usd"] == 0 and not requests
    with service.db.reader() as conn:
        assert conn.execute("SELECT state FROM assistant_inference_attempt WHERE id=?", (attempt_id,)).fetchone()[0] == "unknown"
        assert conn.execute("SELECT count(*) FROM assistant_inference_attempt").fetchone()[0] == 1


@pytest.mark.parametrize("with_proposal", [False, True])
def test_long_conversation_of_short_messages_can_continue_through_sdk(build_env, base_env, with_proposal):
    requests = []
    service, auth, session = setup(build_env(), base_env, _offline_reply(requests))
    if with_proposal:
        AssistantTools(service.ctx, auth, session).invoke("save_agent_proposal", proposal())
    with service.db.transaction() as conn:
        for index in range(60):
            conn.execute("INSERT INTO assistant_message(session_id,role,text,created_at) VALUES (?,?,?,?)",
                         (session, "user" if index % 2 == 0 else "assistant", "OK", to_iso(service.clock.now())))

    result = asyncio.run(service.message(auth, session, str(uuid.uuid4()), "What should I review next?"))

    assert result["text"] == "Your proposal is still available for review."
    assert len(requests) == 1 and len(requests[0]["input"]) <= 40
    assert requests[0]["input"][-1]["content"] == "What should I review next?"
    if with_proposal:
        assert "saved proposal" in requests[0]["input"][0]["content"].lower()
        # Older turns are omitted, but the agreed criteria remain available for
        # accurate edits rather than just the deliverable names/counts.
        saved = json.loads(requests[0]["input"][0]["content"].split(": ", 1)[1])
        assert [item["criteria"] for item in saved["data"]["deliverables"]] == [item["criteria"] for item in proposal()["deliverables"]]
    usage = service.view(auth, session)["usage"]
    assert usage["spent_micro_usd"] == 530 and usage["held_micro_usd"] == 0
