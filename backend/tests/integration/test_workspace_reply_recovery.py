"""A saved draft always leaves a visible receipt within the existing paid bound."""
import asyncio
import json
import re
import uuid

import httpx2
import pytest

from aicl.agent_workspace.assistant import INSTRUCTIONS, WorkspaceAssistantService
from aicl.agent_workspace.service import WorkspaceService
from aicl.chat.assistant_meter import AssistantMeter, RESERVATION
from aicl.chat.sdk_agent import SDKInterviewModel
from aicl.control.errors import AiclError
from aicl.db import to_iso
from test_workspace_assistant import patch_arguments
from test_workspace_execution import setup


def response(index, output):
    return httpx2.Response(200, json={
        "id": "resp_reply_recovery_" + str(index), "object": "response", "created_at": 1760000000,
        "status": "completed", "model": "gpt-6-sol", "service_tier": "default",
        "parallel_tool_calls": False, "error": None, "incomplete_details": None, "output": output,
        "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
                  "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 0}},
    })


def tool_call(index, name, arguments):
    return [{"type": "function_call", "id": "fc_" + str(index), "call_id": "call_" + str(index),
             "name": name, "arguments": json.dumps(arguments), "status": "completed"}]


def scenario(build_env, base_env, *, final_behavior="reply"):
    env, ctx, auth, instance, workspace_id, worker, _ = setup(build_env, base_env)
    state = WorkspaceService(ctx).view(auth, workspace_id)
    requests = []
    actions = [
        ("read_workspace", {"section": "overview", "offset": 0}),
        ("read_workspace", {"section": "deliverables", "offset": 0}),
        ("read_workspace", {"section": "inputs", "offset": 0}),
        ("update_draft", patch_arguments(state["version"], {"name": "Saved with a visible reply"})),
    ]

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        index = len(requests)
        assert index <= 5, "The assistant must not dispatch a sixth provider request"
        if index <= len(actions):
            name, arguments = actions[index - 1]
            return response(index, tool_call(index, name, arguments))
        if final_behavior == "unknown":
            raise httpx2.ReadError("test transport lost the final receipt", request=request)
        # A realistic model would otherwise navigate to the next setup section,
        # consuming its final turn after the update had already committed.
        if payload.get("tool_choice") != "none" or final_behavior == "ignores_choice":
            return response(index, tool_call(index, "show_section", {"section": "funding"}))
        return response(index, [{"type": "message", "id": "msg_final", "role": "assistant", "status": "completed",
                                 "content": [{"type": "output_text", "text": "Your draft is saved. Review the visible settings.", "annotations": []}]}])

    model = SDKInterviewModel("test-key-never-real", transport=httpx2.MockTransport(respond), instructions=INSTRUCTIONS)
    service = WorkspaceAssistantService(ctx, workspace_id, state["version"], model=model)
    return env, ctx, auth, state, worker, service, requests


def assert_saved_once(env, ctx, auth, before):
    state = WorkspaceService(ctx).view(auth, before["id"])
    assert state["draft"]["name"] == "Saved with a visible reply"
    assert state["version"] == before["version"] + 1
    assert state["published"] == before["published"] and state["dirty"]
    with env.db.reader() as conn:
        events = conn.execute("SELECT name,state FROM assistant_tool_event WHERE session_id=? ORDER BY id", (before["session_id"],)).fetchall()
        assert [(row["name"], row["state"]) for row in events] == [
            ("read_workspace", "completed"), ("read_workspace", "completed"),
            ("read_workspace", "completed"), ("update_draft", "completed")]
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 0


def test_final_request_is_reserved_for_reply_after_saved_update(build_env, base_env):
    env, ctx, auth, state, worker, service, requests = scenario(build_env, base_env)
    identity, user_text = str(uuid.uuid4()), "Update this draft and show me the next step"
    result = asyncio.run(service.message(auth, state["session_id"], identity, user_text))
    assert result["text"] == "Your draft is saved. Review the visible settings."
    assert len(requests) == 5 and requests[-1]["tool_choice"] == "none"
    assert_saved_once(env, ctx, auth, state)
    replay = asyncio.run(service.message(auth, state["session_id"], identity, user_text))
    assert replay["text"] == result["text"] and len(requests) == 5
    view = service.view(auth, state["session_id"])
    assert [(item["role"], item["text"]) for item in view["messages"]] == [("user", user_text), ("assistant", result["text"])]
    assert view["usage"]["spent_micro_usd"] == 2000 and view["usage"]["held_micro_usd"] == 0
    with env.db.reader() as conn:
        attempts = conn.execute("SELECT state FROM assistant_inference_attempt").fetchall()
        assert len(attempts) == 5 and all(row[0] == "settled" for row in attempts)
        assert conn.execute("SELECT state FROM assistant_turn").fetchone()[0] == "completed"
    assert worker.calls == []


@pytest.mark.parametrize("final_behavior", ["ignores_choice", "unknown"])
def test_interrupted_final_reply_recovers_saved_changes_without_extra_dispatch_or_released_holds(build_env, base_env, final_behavior):
    env, ctx, auth, state, worker, service, requests = scenario(build_env, base_env, final_behavior=final_behavior)
    identity, user_text = str(uuid.uuid4()), "Update the shared draft"
    result = asyncio.run(service.message(auth, state["session_id"], identity, user_text))
    assert result["accepted"] is True and result["status"] in {"failed", "unknown"}
    assert result["text"] and len(requests) == 5
    assert requests[-1]["tool_choice"] == "none"
    assert_saved_once(env, ctx, auth, state)
    replay = asyncio.run(service.message(auth, state["session_id"], identity, user_text))
    assert replay["text"] == result["text"] and len(requests) == 5
    view = service.view(auth, state["session_id"])
    assert len(view["messages"]) == 2
    receipt = view["messages"][-1]
    assert receipt["role"] == "assistant" and receipt["kind"] == "recovery"
    assert receipt["text"] == result["text"]
    assert re.fullmatch(r"[a-z][a-z0-9_]{0,63}", receipt["failure_reason"])
    assert "draft" in receipt["text"].lower()
    assert "saved" in receipt["text"].lower() or "updated" in receipt["text"].lower()
    with env.db.reader() as conn:
        attempts = conn.execute("SELECT state FROM assistant_inference_attempt ORDER BY rowid").fetchall()
        assert len(attempts) == 5
        assert [row[0] for row in attempts[:4]] == ["settled"] * 4
        assert attempts[-1][0] == ("unknown" if final_behavior == "unknown" else "settled")
        assert conn.execute("SELECT COUNT(*) FROM assistant_message WHERE role='assistant'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM assistant_turn").fetchone()[0] == 1
    assert view["usage"]["held_micro_usd"] == (RESERVATION if final_behavior == "unknown" else 0)
    assert view["usage"]["spent_micro_usd"] == (1600 if final_behavior == "unknown" else 2000)
    assert view["usage"]["unknown"] is (final_behavior == "unknown")
    assert worker.calls == []


def test_historical_saved_turn_projects_receipt_without_writing_and_replays_before_version_validation(build_env, base_env):
    env, ctx, auth, state, worker, service, requests = scenario(build_env, base_env)
    identity, user_text = str(uuid.uuid4()), "A previously interrupted request"
    turn_id, replay = service._claim(auth, state["session_id"], identity, user_text)
    assert replay is None
    meter = AssistantMeter(ctx, auth, turn_id)
    attempt = meter.reserve()
    meter.fail(attempt, no_charge=False, reason="provider_unknown")
    with env.db.transaction() as conn:
        saved = WorkspaceService(ctx).update_draft(auth, state["id"], state["version"], {"name": "Historic saved title"}, actor="assistant")
        conn.execute("INSERT INTO assistant_tool_event(session_id,turn_id,name,state,result_json,created_at) VALUES (?,?,'update_draft','completed',?,?)",
                     (state["session_id"], turn_id, json.dumps({"version": saved["version"], "changed_fields": ["name"]}), to_iso(env.clock.now())))
        conn.execute("UPDATE assistant_turn SET state='unknown',error='Historical interruption' WHERE id=?", (turn_id,))
    with env.db.transaction() as conn:
        changes = conn.total_changes
        first = service.view(auth, state["session_id"])
        second = service.view(auth, state["session_id"])
        assert conn.total_changes == changes
        assert first == second
        assert conn.execute("SELECT COUNT(*) FROM assistant_message").fetchone()[0] == 1
        assert conn.execute("SELECT state FROM assistant_inference_attempt WHERE id=?", (attempt,)).fetchone()[0] == "unknown"
    assert first["messages"][-1]["kind"] == "recovery"
    assert "draft changes were saved" in first["messages"][-1]["text"]
    assert first["usage"]["held_micro_usd"] == RESERVATION
    result = asyncio.run(service.message(auth, state["session_id"], identity, user_text))
    assert result["accepted"] and result["replayed"] and result["status"] == "unknown"
    assert result["text"] == first["messages"][-1]["text"]
    # A retry may carry the stale original version, but cannot change the body;
    # a new request with that stale version remains an ordinary 409.
    with pytest.raises(AiclError, match="conflict"):
        asyncio.run(service.message(auth, state["session_id"], identity, "Different request body"))
    with pytest.raises(AiclError, match="conflict"):
        asyncio.run(service.message(auth, state["session_id"], str(uuid.uuid4()), "New request with a stale version"))
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM assistant_turn").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM assistant_message").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM assistant_inference_attempt").fetchone()[0] == 1
        assert conn.execute("SELECT state FROM assistant_inference_attempt WHERE id=?", (attempt,)).fetchone()[0] == "unknown"
    assert requests == [] and worker.calls == []
