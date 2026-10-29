"""Real adapter/coordinator integration using deterministic provider transport."""
from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest

from aicl.agent_runtime.adapters import ScriptedModel, ToolRegistry
from aicl.agent_runtime.contracts import DecisionEnvelope, RunDefinition
from aicl.agent_runtime.coordinator import AgentRuntime
from aicl.agent_runtime.openai_model import OpenAIDecisionModel
from aicl.agent_runtime.storage import Repository
from aicl.control.errors import AiclError
from aicl.workflow.openai_inference import InferenceNoChargeError
from test_mock_commerce import ready


def test_live_decision_pin_receipts_no_charge_rejection_and_unknown_hold(build_env):
    env, _, auth, inst, _ = ready(lambda: build_env(start=datetime(2026, 10, 26, tzinfo=timezone.utc)))
    tools = ToolRegistry().with_artifact_reader(Repository(env.db, env.clock))
    complete = DecisionEnvelope.model_validate({"schema_version": 1,
        "output": {"artifacts": [{"local_ref": "note", "content": "A useful answer."}]},
        "control": {"next": "complete", "artifact_refs": ["note"], "criterion_assessments": [
            {"requirement_id": "answer", "status": "met", "explanation": "Answered"}]}}).model_dump(mode="json")
    calls, mode = [], ["success"]

    def transport(request):
        calls.append(json.loads(request.content))
        if mode[0] == "reject":
            return httpx.Response(400)
        if mode[0] == "unknown":
            raise httpx.ReadTimeout("sensitive provider text must not be logged")
        return httpx.Response(200, json={"id": "resp_integration", "object": "response", "model": "gpt-6-sol",
            "service_tier": "default", "status": "completed", "error": None,
            "usage": {"input_tokens": 500, "output_tokens": 100, "total_tokens": 600,
                      "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}},
            "output": [{"type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": json.dumps({"decision": complete})}]}]})

    model = OpenAIDecisionModel("sk-test-local-only", tool_specs=tools.specs(), transport=httpx.MockTransport(transport))
    with pytest.raises(AiclError):
        AgentRuntime(env.db, env.clock, model, tools)
    runtime = AgentRuntime(env.db, env.clock, model, tools, allow_live=True)
    definition = RunDefinition(objective="Answer clearly", requirements=[{"id": "answer", "text": "Give a useful answer"}])
    run = runtime.create_run(auth, inst.id, "live-shaped", definition)
    assert runtime.advance_slice(auth, run["id"])["status"] == "completed"
    assert len(calls) == 1 and calls[0]["tools"] == [] and calls[0]["store"] is False
    with env.db.reader() as conn:
        hold = conn.execute("SELECT * FROM budget_hold WHERE work_id LIKE 'runtime:%'").fetchone()
        assert hold["price_table_version"] == model.price_version and hold["state"] == "settled"
        step = conn.execute("SELECT * FROM agent_step WHERE run_id=?", (run["id"],)).fetchone()
        assert json.loads(step["receipt_metadata_json"]) == {"response_id": "resp_integration", "model": "gpt-6-sol"}
        assert conn.execute("SELECT inference_micro_usd FROM budget_usage WHERE hold_id=?", (hold["id"],)).fetchone()[0] == 2000

    mode[0] = "reject"
    rejected = runtime.create_run(auth, inst.id, "rejected", definition)
    state = runtime.advance_slice(auth, rejected["id"])
    assert state["status"] == "blocked" and state["reason"] == "http_400"
    with env.db.reader() as conn:
        assert conn.execute("SELECT h.state FROM budget_hold h JOIN agent_step s ON s.hold_id=h.id WHERE s.run_id=?",
                            (rejected["id"],)).fetchone()[0] == "released"
    mode[0] = "unknown"
    uncertain = runtime.create_run(auth, inst.id, "uncertain", definition)
    state = runtime.advance_slice(auth, uncertain["id"])
    assert state["status"] == "blocked" and state["reason"] == "unknown_outcome"
    runtime.advance_slice(auth, uncertain["id"])
    assert len(calls) == 3
    with env.db.reader() as conn:
        assert conn.execute("SELECT h.state FROM budget_hold h JOIN agent_step s ON s.hold_id=h.id WHERE s.run_id=?",
                            (uncertain["id"],)).fetchone()[0] == "unknown"


def test_late_verified_rejection_reconciles_unknown_without_redispatch(build_env):
    env, _, auth, inst, _ = ready(build_env)
    saved = []
    replacement = AgentRuntime(env.db, env.clock, ScriptedModel([]), ToolRegistry())

    class LateRejection(ScriptedModel):
        def decide(self, context, invocation_id):
            env.clock.advance(timedelta(seconds=31))
            assert replacement.advance_slice(auth, run["id"])["reason"] == "unknown_outcome"
            raise InferenceNoChargeError("http_400")

    runtime = AgentRuntime(env.db, env.clock, LateRejection([]), ToolRegistry())
    run = runtime.create_run(auth, inst.id, "late-rejection", RunDefinition(objective="Answer",
                             requirements=[{"id": "answer", "text": "Answer clearly"}]))
    with pytest.raises(AiclError, match="conflict"):
        runtime.advance_slice(auth, run["id"], fault=lambda stage, step: saved.append(step) if stage == "after_dispatch_intent" else None)
    with env.db.reader() as conn:
        assert conn.execute("SELECT state FROM budget_hold WHERE id=?", (saved[0]["hold_id"],)).fetchone()[0] == "released"
        assert conn.execute("SELECT state FROM agent_step WHERE id=?", (saved[0]["id"],)).fetchone()[0] == "applied"
    runtime._record_no_charge(auth, run["id"], saved[0], "http_400")
    with pytest.raises(AiclError, match="conflict"):
        runtime._record_no_charge(auth, run["id"], saved[0], "http_401")
    assert runtime.read(auth, run["id"])["reason"] == "http_400"
    assert replacement.model.calls == []
