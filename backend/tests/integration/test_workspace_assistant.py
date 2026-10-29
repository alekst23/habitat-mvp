"""The management assistant edits the visible draft without becoming its worker."""
import asyncio
import json
import uuid

import httpx2
import pytest
from fastapi.testclient import TestClient

from aicl.agent_runtime.adapters import ToolRegistry
from aicl.agent_runtime.coordinator import AgentRuntime
from aicl.agent_workspace.assistant import INSTRUCTIONS, WorkspaceAssistantService, WorkspaceAssistantTools
from aicl.agent_workspace.execution import WorkspaceExecution
from aicl.agent_workspace.service import WorkspaceService
from aicl.chat.sdk_agent import MAX_TOOL_RESULT_BYTES, SDKInterviewModel
from aicl.chat.assistant_tools import AssistantTools
from aicl.app import FIXTURE_CSRF_TOKEN, create_app
from aicl.control.errors import AiclError
from aicl.db import to_iso
from test_workspace_execution import setup


def patch_arguments(version, values):
    schema = next(item for item in WorkspaceAssistantTools.schemas() if item["name"] == "update_draft")
    patch = {key: None for key in schema["parameters"]["properties"]["patch"]["properties"]}
    return {"expected_version": version, "patch": {**patch, **values}}


def test_management_stays_available_after_start_and_draft_tools_cannot_apply_authority(build_env, base_env):
    env, ctx, auth, instance, workspace_id, worker, published = setup(build_env, base_env)
    core = WorkspaceService(ctx)
    state = core.view(auth, workspace_id)
    run = WorkspaceExecution(ctx).start(auth, workspace_id, "existing-work")
    with env.db.transaction() as conn:
        # Also cover the old chat link that previously switched every message
        # into worker guidance after launch.
        conn.execute("INSERT INTO agent_chat_run(session_id,run_id,created_at) VALUES (?,?,?)",
                     (state["session_id"], run["id"], to_iso(env.clock.now())))
        original = dict(conn.execute("SELECT * FROM agent_instance WHERE id=?", (instance.id,)).fetchone())

    class EditModel:
        calls = 0

        async def run(self, history, *, tools, invoke, meter):
            self.calls += 1
            assert {item["name"] for item in tools} == {"read_workspace", "update_draft", "show_section"}
            attempt = meter.reserve()
            meter.settle(attempt, "resp_workspace", "gpt-6-sol", 100, 50)
            current = invoke("read_workspace", {"section": "overview", "offset": 0})
            assert current["run"]["id"] == run["id"]
            for name in ("apply", "fund", "start", "resume", "schedule", "lifecycle", "confirm"):
                assert invoke(name, {})["error"] == "denied"
            result = invoke("update_draft", patch_arguments(current["version"], {
                "inputs": "Use the customer support audience on the next run.",
                "limits": {"inference_daily_micro_usd": 9_000_000}}))
            assert result["dirty"]
            invoke("show_section", {"section": "limits"})
            return "The next-run audience and proposed limit are updated on screen for review."

    model = EditModel()
    service = WorkspaceAssistantService(ctx, workspace_id, state["version"], model=model)
    request_id = str(uuid.uuid4())
    result = asyncio.run(service.message(auth, state["session_id"], request_id, "Adjust the next run"))
    replay = asyncio.run(service.message(auth, state["session_id"], request_id, "Adjust the next run"))
    assert replay["replayed"] and replay["text"] == result["text"] and model.calls == 1
    assert service.tools_instance.focus_section == "limits"
    after = core.view(auth, workspace_id)
    assert after["draft"]["inputs"].startswith("Use the customer")
    assert after["published"] == {**published, "web_search": None} and after["dirty"]
    assert after["draft"]["limits"]["inference_daily_micro_usd"] == 9_000_000
    assert worker.calls == []
    with env.db.reader() as conn:
        assert dict(conn.execute("SELECT * FROM agent_instance WHERE id=?", (instance.id,)).fetchone()) == original
        assert conn.execute("SELECT COUNT(*) FROM agent_event WHERE run_id=? AND kind='owner_message'", (run["id"],)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM assistant_turn WHERE state='completed'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM assistant_inference_attempt WHERE state='settled'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 1
    messages = service.view(auth, state["session_id"])
    assert messages["messages"][-1]["text"] == result["text"]
    assert messages["usage"]["spent_micro_usd"] == 700 and messages["usage"]["held_micro_usd"] == 0


def test_concurrent_form_edit_prevents_assistant_overwrite_and_next_turn_reads_shared_state(build_env, base_env):
    env, ctx, auth, instance, workspace_id, worker, _ = setup(build_env, base_env)
    core = WorkspaceService(ctx)
    before = core.view(auth, workspace_id)
    tools = WorkspaceAssistantTools(ctx, auth, workspace_id, before["version"])
    owner = core.update_draft(auth, workspace_id, before["version"], {"name": "Owner's current title"})
    for version in (before["version"], owner["version"]):
        with pytest.raises(AiclError, match="conflict"):
            tools.invoke("update_draft", patch_arguments(version, {"name": "Assistant overwrite"}))
    fresh = WorkspaceAssistantTools(ctx, auth, workspace_id, owner["version"])
    overview = fresh.invoke("read_workspace", {"section": "overview", "offset": 0})
    assert overview["draft"]["name"] == "Owner's current title"
    saved = fresh.invoke("update_draft", patch_arguments(owner["version"], {"time_of_day": "10:30"}))
    assert core.view(auth, workspace_id)["draft"]["time_of_day"] == "10:30"
    assert core.view(auth, workspace_id)["draft"]["name"] == "Owner's current title"
    assert saved["version"] == owner["version"] + 1


def test_management_cannot_reintroduce_optional_ai_processing(build_env, base_env):
    env, ctx, auth, instance, workspace_id, worker, _ = setup(build_env, base_env)
    core = WorkspaceService(ctx)
    state = core.view(auth, workspace_id)

    class CheckPermission:
        async def run(self, history, *, tools, invoke, meter):
            update = next(item for item in tools if item["name"] == "update_draft")
            assert "inference_enabled" not in update["parameters"]["properties"]["patch"]["properties"]
            snapshot = json.loads(history[0]["content"].split("\n", 1)[1])
            assert "inference_enabled" not in snapshot["draft"]
            overview = invoke("read_workspace", {"section": "overview", "offset": 0})
            assert "inference_enabled" not in overview["draft"]
            attempt = meter.reserve()
            meter.settle(attempt, "resp_permission", "gpt-6-sol", 100, 20)
            result = invoke("update_draft", patch_arguments(state["version"], {"inference_enabled": False}))
            assert result["error"] == "validation_failed"
            assert invoke("apply", {})["error"] == "denied"
            return "AI processing is included. Spending limits still apply."

    service = WorkspaceAssistantService(ctx, workspace_id, state["version"], model=CheckPermission())
    result = asyncio.run(service.message(auth, state["session_id"], str(uuid.uuid4()), "Is AI processing optional?"))
    assert result["text"].startswith("AI processing is included")
    after = core.view(auth, workspace_id)
    assert after["draft"] == state["draft"] and after["published"] == state["published"]
    with env.db.reader() as conn:
        assert conn.execute("SELECT enabled FROM capability_grant WHERE instance_id=? AND capability='inference'",
                            (instance.id,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM assistant_inference_attempt WHERE state='settled'").fetchone()[0] == 1
    assert worker.calls == []


def test_all_valid_workspace_read_results_fit_sdk_budget_and_paginate_losslessly(build_env, base_env):
    env, ctx, auth, instance, workspace_id, worker, _ = setup(build_env, base_env)
    core = WorkspaceService(ctx)
    state = core.view(auth, workspace_id)
    domains = [".".join(["a" * 60, "b" * 60, "c" * 60, "d" * 55]) + str(index) + ".com" for index in range(20)]
    state = core.update_draft(auth, workspace_id, state["version"], {
        "goal": "🙂" * 500, "inputs": "\\" * 2000, "network_domains": domains,
        "deliverables": [{"key": "d" + str(index), "name": "🙂" * 120, "description": "A description", "criteria": ["Explain"]}
                         for index in range(6)]})
    tools = WorkspaceAssistantTools(ctx, auth, workspace_id, state["version"])
    overview = tools.invoke("read_workspace", {"section": "overview", "offset": 0})
    assert len(json.dumps(overview, ensure_ascii=False, separators=(",", ":")).encode()) <= MAX_TOOL_RESULT_BYTES
    for field in ("network_domains", "deliverables", "inputs"):
        offset, chunks = 0, []
        while offset is not None:
            result = tools.invoke("read_workspace", {"section": field, "offset": offset})
            assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()) <= MAX_TOOL_RESULT_BYTES
            chunks.append(result["json_text"])
            offset = result["next_offset"]
        assert json.loads("".join(chunks)) == state["draft"][field]


def test_real_sdk_accepts_workspace_schema_and_completes_metered_tool_loop(build_env, base_env):
    env, ctx, auth, instance, workspace_id, worker, _ = setup(build_env, base_env)
    state = WorkspaceService(ctx).view(auth, workspace_id)
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        index = len(requests)
        assert "ONE editable draft" in payload["instructions"]
        if index == 1:
            output = [{"type": "function_call", "id": "fc_read", "call_id": "call_read", "name": "read_workspace",
                       "arguments": json.dumps({"section": "overview", "offset": 0}), "status": "completed"}]
        elif index == 2:
            output = [{"type": "function_call", "id": "fc_edit", "call_id": "call_edit", "name": "update_draft",
                       "arguments": json.dumps(patch_arguments(state["version"], {"name": "The shared title"})), "status": "completed"}]
        else:
            output = [{"type": "message", "id": "msg_done", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": "The title is updated on screen.", "annotations": []}]}]
        return httpx2.Response(200, json={"id": "resp_workspace_" + str(index), "object": "response", "created_at": 1760000000,
            "status": "completed", "model": "gpt-6-sol", "service_tier": "default", "parallel_tool_calls": False,
            "error": None, "incomplete_details": None, "output": output,
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
                      "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}})

    model = SDKInterviewModel("test-key-never-real", transport=httpx2.MockTransport(respond), instructions=INSTRUCTIONS)
    service = WorkspaceAssistantService(ctx, workspace_id, state["version"], model=model)
    result = asyncio.run(service.message(auth, state["session_id"], str(uuid.uuid4()), "Change the title"))
    assert result["text"] == "The title is updated on screen."
    assert len(requests) == 3 and worker.calls == []
    assert WorkspaceService(ctx).view(auth, workspace_id)["draft"]["name"] == "The shared title"
    assert service.view(auth, state["session_id"])["usage"]["spent_micro_usd"] == 1200


def test_cached_legacy_proposal_cannot_create_duplicate_agent_after_workspace_apply(build_env, base_env, monkeypatch):
    env, ctx, auth, instance, workspace_id, worker, draft = setup(build_env, base_env)
    state = WorkspaceService(ctx).view(auth, workspace_id)
    # The old confirmation card may remain open in a second browser tab after
    # its proposal is imported and reviewed in the canonical workspace.
    payload = {key: draft[key] for key in ("name", "goal", "inputs", "deliverables", "cadence", "timezone")}
    payload.update(scenario="general", tools=[], budget_notes="Owner reviews spending limits")
    pending = AssistantTools(ctx, auth, state["session_id"]).invoke("save_agent_proposal", payload)["proposal"]
    from aicl.agent_runtime import factory
    monkeypatch.setattr(factory, "build_runtime", lambda c: AgentRuntime(c.db, c.clock, worker, ToolRegistry()))
    app = create_app(ctx.settings.model_copy(update={"environment": "test", "test_mode": True, "database_url": env.db.database_url}))
    app.state.ctx.auth_provider.contexts["workspace-cookie"] = auth
    app.state.ctx.csrf_verifier.fixture_session_ids |= {auth.session_id}
    client = TestClient(app, base_url="http://127.0.0.1:4173")
    client.cookies.set("aicl_session", "workspace-cookie")
    response = client.post(f"/chat/proposals/{pending['id']}/confirm",
                           headers={"X-CSRF-Token": FIXTURE_CSRF_TOKEN, "Origin": "http://127.0.0.1:4173"},
                           json={"chat_session_id": state["session_id"], "version": pending["version"]})
    assert response.status_code == 409, response.text
    assert response.json()["workspace_url"] == "/agent-workspaces/" + workspace_id
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_instance").fetchone()[0] == 1
        assert conn.execute("SELECT state FROM assistant_proposal WHERE id=?", (pending["id"],)).fetchone()[0] == "pending"
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 0
    assert worker.calls == []
