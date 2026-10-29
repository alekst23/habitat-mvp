"""The first management model call already sees the current shared workspace."""
import asyncio
import json
import uuid

import httpx2
import pytest

from aicl.agent_workspace.assistant import (
    INSTRUCTIONS, MAX_WORKSPACE_CONTEXT_BYTES, WORKSPACE_CONTEXT_PREFIX,
    WorkspaceAssistantService, WorkspaceAssistantTools,
)
from aicl.agent_workspace.execution import WorkspaceExecution
from aicl.agent_workspace.service import WorkspaceService
from aicl.chat.sdk_agent import MAX_REQUEST_BYTES, MAX_TOOL_RESULT_BYTES, SDKInterviewModel
from aicl.control.errors import AiclError
from test_workspace_assistant import patch_arguments
from test_workspace_execution import setup


def context(history):
    assert history[0]["role"] == "assistant"
    assert history[0]["content"].startswith(WORKSPACE_CONTEXT_PREFIX)
    return json.loads(history[0]["content"][len(WORKSPACE_CONTEXT_PREFIX):])


def test_first_model_call_has_complete_ordinary_context_and_edits_without_reads(build_env, base_env):
    env, ctx, auth, _, workspace_id, worker, _ = setup(build_env, base_env)
    core = WorkspaceService(ctx)
    run = WorkspaceExecution(ctx).start(auth, workspace_id, "existing")
    state = core.view(auth, workspace_id)
    state = core.update_draft(auth, workspace_id, state["version"], {
        "inputs": "Use these two supplied articles; keep their publication dates.", "tools": [], "network_domains": []})

    class ImmediateEdit:
        async def run(self, history, *, tools, invoke, meter):
            current = context(history)
            assert current["version"] == state["version"]
            assert current["draft"] == state["draft"]
            assert current["draft"]["tools"] == current["draft"]["network_domains"] == []
            assert current["omitted_fields"] == []
            assert current["capabilities"][0]["name"] == "fixture.read"
            assert current["readiness"] == WorkspaceExecution(ctx).view(auth, workspace_id)["readiness"]
            assert current["run"]["id"] == run["id"] and current["schedule"]["enabled"] is False
            assert current["run"]["allowed_tools"] == ["fixture.read"]
            assert current["run"]["settings_changed"] is False
            assert current["run"]["can_restart"] is False
            assert history[-1] == {"role": "user", "content": "Name it Morning brief"}
            assert not env.db._local.conn  # No database lock spans a provider call.
            saved = invoke("update_draft", patch_arguments(current["version"], {"name": "Morning brief"}))
            assert saved["version"] == current["version"] + 1
            return "The name is updated on screen."

    service = WorkspaceAssistantService(ctx, workspace_id, state["version"], model=ImmediateEdit())
    asyncio.run(service.message(auth, state["session_id"], str(uuid.uuid4()), "Name it Morning brief"))
    assert core.view(auth, workspace_id)["draft"]["name"] == "Morning brief"
    assert "Always read_workspace first" not in INSTRUCTIONS and worker.calls == []
    with env.db.reader() as conn:
        assert [row[0] for row in conn.execute("SELECT name FROM assistant_tool_event ORDER BY rowid")] == ["update_draft"]


def test_large_unicode_draft_is_bounded_with_lossless_section_recovery(build_env, base_env):
    env, ctx, auth, _, workspace_id, _, _ = setup(build_env, base_env)
    core = WorkspaceService(ctx)
    state = core.view(auth, workspace_id)
    state = core.update_draft(auth, workspace_id, state["version"], {
        "goal": "🙂" * 2000, "inputs": "🙂\\" * 2000, "tools": [], "network_domains": [],
        "deliverables": [{"key": f"result_{i}", "name": "Result", "description": "🙂" * 2000,
                           "criteria": ["🙂" * 500 for _ in range(12)]} for i in range(6)]})
    service = WorkspaceAssistantService(ctx, workspace_id, state["version"])
    with env.db.transaction() as conn:
        before = conn.total_changes
        history = service._history(auth, state["session_id"])
        assert conn.total_changes == before
    current = context(history)
    assert len(json.dumps(history[0], ensure_ascii=False, separators=(",", ":")).encode()) <= MAX_WORKSPACE_CONTEXT_BYTES
    request = {"input": history, "instructions": INSTRUCTIONS, "tools": WorkspaceAssistantTools.schemas()}
    assert len(json.dumps(request, ensure_ascii=False).encode()) < MAX_REQUEST_BYTES
    assert current["version"] == state["version"]
    assert current["draft"]["tools"] == current["draft"]["network_domains"] == []
    omitted = {item["path"]: item for item in current["omitted_fields"]}
    assert "draft.deliverables" in omitted and "draft.inputs" in omitted
    assert "inputs" not in current["draft"] and "deliverables" not in current["draft"]
    recovery = omitted["draft.inputs"]["read_workspace"]
    assert recovery == {"section": "inputs", "offset": 0}
    tools = WorkspaceAssistantTools(ctx, auth, workspace_id, state["version"])
    offset, chunks = 0, []
    while offset is not None:
        result = tools.invoke("read_workspace", {**recovery, "offset": offset})
        assert result["version"] == current["version"]
        chunks.append(result["json_text"])
        offset = result["next_offset"]
    assert json.loads("".join(chunks)) == state["draft"]["inputs"]
    requests = []

    def respond(request):
        assert len(request.content) <= MAX_REQUEST_BYTES
        payload = json.loads(request.content)
        requests.append(payload)
        assert WORKSPACE_CONTEXT_PREFIX in json.dumps(payload, ensure_ascii=False).replace("\\n", "\n")
        return httpx2.Response(200, json={
            "id": "resp_context", "object": "response", "created_at": 1760000000,
            "status": "completed", "model": "gpt-6-sol", "service_tier": "default",
            "parallel_tool_calls": False, "error": None, "incomplete_details": None,
            "output": [{"type": "message", "id": "msg_context", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": "The saved draft is available for review.", "annotations": []}]}],
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
                      "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                      "output_tokens_details": {"reasoning_tokens": 0}},
        })

    model = SDKInterviewModel("test-key-never-real", transport=httpx2.MockTransport(respond), instructions=INSTRUCTIONS)
    service = WorkspaceAssistantService(ctx, workspace_id, state["version"], model=model)
    result = asyncio.run(service.message(auth, state["session_id"], str(uuid.uuid4()), "x" * 4000))
    assert result["text"] == "The saved draft is available for review." and len(requests) == 1


def test_automatic_context_preserves_version_guard_before_and_during_model_call(build_env, base_env):
    _, ctx, auth, _, workspace_id, _, _ = setup(build_env, base_env)
    core = WorkspaceService(ctx)
    initial = core.view(auth, workspace_id)
    stale = WorkspaceAssistantService(ctx, workspace_id, initial["version"])
    state = core.update_draft(auth, workspace_id, initial["version"], {"inputs": "Owner context"})
    with pytest.raises(AiclError, match="conflict"):
        stale._history(auth, state["session_id"])

    class ConcurrentEdit:
        async def run(self, history, *, tools, invoke, meter):
            snapshot = context(history)
            assert snapshot["version"] == state["version"] and snapshot["draft"]["inputs"] == "Owner context"
            core.update_draft(auth, workspace_id, snapshot["version"], {"name": "Owner's newer name"})
            result = invoke("update_draft", patch_arguments(snapshot["version"], {"name": "Stale overwrite"}))
            assert result["error"] == "conflict"
            return "The owner changed the draft while I was replying; that change is preserved."

    fresh = WorkspaceAssistantService(ctx, workspace_id, state["version"], model=ConcurrentEdit())
    asyncio.run(fresh.message(auth, state["session_id"], str(uuid.uuid4()), "Change the name"))
    assert core.view(auth, workspace_id)["draft"]["name"] == "Owner's newer name"


def test_omitted_run_and_operational_context_have_complete_bounded_read_paths(build_env, base_env, monkeypatch):
    _, ctx, auth, _, workspace_id, _, _ = setup(build_env, base_env)
    state = WorkspaceService(ctx).view(auth, workspace_id)
    execution = WorkspaceExecution(ctx).view(auth, workspace_id)
    question = {"id": "owner-question", "text": "🙂" * 4000, "options": ["Yes", "No"]}
    allowed_tools = [f"tool{i:03d}_" + "x" * 120 for i in range(64)]
    run = {"id": "current-run", "version": 3, "status": "waiting_owner", "question": question, "reason": "🙂" * 1000,
           "allowed_tools": allowed_tools, "settings_changed": True, "can_restart": True}
    readiness = {**execution["readiness"], "blockers": [{"reason": "context", "message": "🙂" * 4000}]}
    schedule = {"enabled": True, "next_due": None, "last_outcome": "🙂" * 4000}
    catalog = [{"name": "web.read", "description": "🙂" * 4000, "capability": "network.fetch"}]
    monkeypatch.setattr(WorkspaceService, "capabilities", lambda self: catalog)
    monkeypatch.setattr(WorkspaceExecution, "view", lambda self, *args: {
        **execution, "run": run, "readiness": readiness, "schedule": schedule})
    service = WorkspaceAssistantService(ctx, workspace_id, state["version"])
    history = service._history(auth, state["session_id"])
    snapshot = context(history)
    assert len(json.dumps(history[0], ensure_ascii=False, separators=(",", ":")).encode()) <= MAX_WORKSPACE_CONTEXT_BYTES
    assert snapshot["run"]["settings_changed"] is True and snapshot["run"]["can_restart"] is True
    omitted = {item["path"]: item for item in snapshot["omitted_fields"]}
    expected = {"capabilities": ("capabilities", catalog), "readiness": ("readiness", readiness),
                "schedule": ("schedule_status", schedule), "run.question": ("run_question", question),
                "run.allowed_tools": ("run_allowed_tools", allowed_tools)}
    tools = WorkspaceAssistantTools(ctx, auth, workspace_id, state["version"])
    schema = WorkspaceAssistantTools.schemas()[0]["parameters"]["properties"]["section"]["enum"]
    for path, (section, value) in expected.items():
        recovery = omitted[path]["read_workspace"]
        assert recovery == {"section": section, "offset": 0} and section in schema
        offset, chunks = 0, []
        while offset is not None:
            result = tools.invoke("read_workspace", {**recovery, "offset": offset})
            assert result["version"] == snapshot["version"]
            if section.startswith("run_"):
                assert result["run_id"] == run["id"] and result["run_version"] == run["version"]
            assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()) <= MAX_TOOL_RESULT_BYTES
            chunks.append(result["json_text"])
            offset = result["next_offset"]
        assert json.loads("".join(chunks)) == value
