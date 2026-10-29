"""A general session's meaningful inference, crash and owner-control boundaries."""
from datetime import timedelta
import json
import os
import subprocess
import sys

import pytest

from aicl.agent_runtime.coordinator import AgentRuntime
from aicl.agent_runtime.contracts import RunDefinition
from aicl.agent_runtime.contracts import canonical_json
from aicl.agent_runtime.adapters import AdapterResult, ScriptedModel, ScriptedTool, ToolRegistry
from aicl.agent_runtime.worker import LocalRuntimeWorker
from aicl.control.budget import Estimate, MeasuredUsage
from aicl.control.errors import AiclError
from aicl.db import Database, to_iso


def envelope(*, actions=(), artifacts=(), memory=(), control=None, plan=None):
    return {"schema_version": 1, "output": {"message": None, "artifacts": list(artifacts)},
            "memory_updates": list(memory), "plan_patch": plan, "actions": list(actions),
            "control": control or {"next": "continue"}}


def setup_runtime(env, responses, tools=None):
    model = ScriptedModel(responses)
    tool = ScriptedTool("fixture.read", {"one": {"text": "First source"}, "two": {"text": "Second source"}})
    registry = tools or ToolRegistry([tool])
    return AgentRuntime(env.db, env.clock, model, registry), model, tool


def active(env):
    auth, inst = env.new_instance(capabilities=("inference",))
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_instance SET lifecycle='active' WHERE id=?", (inst.id,))
    return auth, inst


def definition():
    return RunDefinition(objective="Compare supplied material and produce two views",
                         requirements=[{"id": "r1", "text": "Provide a comparison"},
                                       {"id": "r2", "text": "Provide a short summary"}],
                         allowed_tools=["fixture.read"])


def batch():
    return envelope(actions=[{"name": "fixture.read", "arguments": {"key": key}, "plan_item_id": "p1"}
                             for key in ("one", "two")],
                    plan={"upsert": [{"id": "p1", "title": "Read supplied material", "requirement_ids": ["r1", "r2"],
                                      "criteria": ["Read both sources"], "dependency_ids": [], "state": "active",
                                      "evidence_refs": [], "summary": None}], "remove": []})


def finish(context):
    refs = [x["ref"] for x in context["observations"]]
    return envelope(artifacts=[{"local_ref": name, "content": text, "evidence_refs": refs}
                               for name, text in (("comparison", "Compared both sources"), ("summary", "Two sources reviewed"))],
                    plan={"upsert": [{**item, "state": "completed", "evidence_refs": refs}
                                     for item in context["plan"].values()], "remove": []},
                    control={"next": "complete", "artifact_refs": ["comparison", "summary"],
                             "criterion_assessments": [{"requirement_id": key, "status": "met",
                                                        "explanation": "Output supplied", "evidence_refs": refs}
                                                       for key in ("r1", "r2")]})


def expire_workspace(env, auth):
    with env.db.transaction() as conn:
        conn.execute("INSERT INTO owner(id,email_hash,created_at) VALUES (?,?,?)",
                     (auth.owner_id, auth.owner_id, to_iso(env.clock.now())))
        conn.execute("INSERT INTO judge_demo_workspace(owner_id,entry_nonce_hash,created_at,expires_at) VALUES (?,?,?,?)",
                     (auth.owner_id, auth.owner_id, to_iso(env.clock.now() - timedelta(minutes=1)),
                      to_iso(env.clock.now())))


@pytest.mark.parametrize("boundary", ["model", "tool", "cached_read"])
def test_expired_workspace_blocks_fresh_worker_dispatch_and_cache(build_env, boundary):
    env = build_env()
    auth, inst = active(env)
    first = batch()
    first["actions"] = first["actions"][:1]
    runtime, model, tool = setup_runtime(env, [first, first, finish])
    run = runtime.create_run(auth, inst.id, "workspace-expiry", definition())
    if boundary != "model":
        runtime.advance_slice(auth, run["id"], max_operations=1 if boundary == "tool" else 3)
    before = len(model.calls), len(tool.calls)
    with env.db.reader() as conn:
        holds = conn.execute("SELECT COUNT(*) FROM budget_hold").fetchone()[0]
    expire_workspace(env, auth)

    # tick constructs a fresh, unexpired server auth context from the saved run.
    assert LocalRuntimeWorker(runtime).tick() == 1
    result = runtime.read(auth, run["id"])
    assert result["status"] == "blocked" and result["reason"] == "judge_demo_expired"
    assert (len(model.calls), len(tool.calls)) == before
    assert not any(event["kind"] == "read_reused" for event in result["events"])
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM budget_hold").fetchone()[0] == holds


def test_workspace_expiring_after_intent_releases_without_dispatch(build_env):
    env = build_env()
    auth, inst = active(env)
    runtime, model, tool = setup_runtime(env, [batch()])
    run = runtime.create_run(auth, inst.id, "expiry-after-intent", definition())

    def expire_after_intent(stage, _step):
        if stage == "after_dispatch_intent":
            expire_workspace(env, auth)

    result = runtime.advance_slice(auth, run["id"], max_operations=1, fault=expire_after_intent)
    assert result["status"] == "blocked" and result["reason"] == "judge_demo_expired"
    assert model.calls == tool.calls == []
    with env.db.reader() as conn:
        assert [row[0] for row in conn.execute("SELECT state FROM budget_hold")] == ["released"]
        assert conn.execute("SELECT COUNT(*) FROM budget_usage").fetchone()[0] == 0


def test_known_receipt_settles_after_workspace_expiry_without_new_work(build_env):
    from test_mock_commerce import ready

    env, _, auth, inst, _ = ready(build_env)
    runtime, model, tool = setup_runtime(env, [])
    model.estimate = Estimate(100, 100, 0)
    run = runtime.create_run(auth, inst.id, "expiry-known-receipt", definition())

    def interrupted(stage, _step):
        if stage == "after_dispatch_intent":
            raise RuntimeError("receipt pending after worker interruption")

    with pytest.raises(RuntimeError):
        runtime.advance_slice(auth, run["id"], fault=interrupted)
    expire_workspace(env, auth)
    with env.db.reader() as conn:
        step = conn.execute("SELECT id FROM agent_step WHERE run_id=?", (run["id"],)).fetchone()[0]
    receipt = AdapterResult(batch(), usage=MeasuredUsage(100, 100, 0))
    runtime.record_receipt(auth, run["id"], step, receipt)
    runtime.record_receipt(auth, run["id"], step, receipt)
    env.clock.advance(timedelta(seconds=31))  # Allow the interrupted worker's lease to expire.
    assert LocalRuntimeWorker(runtime).tick() == 1
    assert runtime.read(auth, run["id"])["reason"] == "judge_demo_expired"
    assert model.calls == tool.calls == []
    with env.db.reader() as conn:
        assert [row[0] for row in conn.execute("SELECT state FROM budget_hold")] == ["settled"]
        assert [row[0] for row in conn.execute("SELECT inference_micro_usd FROM budget_usage")] == [400]


def test_restart_continues_saved_batch_then_owner_answer_and_shared_outputs(build_env):
    env = build_env()
    auth, inst = active(env)
    runtime, first_model, tool = setup_runtime(env, [batch()])
    run = runtime.create_run(auth, inst.id, "request-1", definition())
    runtime.advance_slice(auth, run["id"], max_operations=2)  # one model + one read
    assert len(first_model.calls) == 1 and len(tool.calls) == 1

    # Continue the second saved read in a separate Python process, with no model responses.
    program = '''
import json, sys
from datetime import datetime
from aicl.agent_runtime.coordinator import AgentRuntime
from aicl.agent_runtime.adapters import ScriptedModel, ScriptedTool, ToolRegistry
from aicl.clock import FakeClock
from aicl.control.auth import AuthContext
from aicl.db import Database
db = Database(sys.argv[1]); db.migrate()
clock = FakeClock(datetime.fromisoformat(sys.argv[5]))
auth = AuthContext(sys.argv[2], sys.argv[2], 'replacement', datetime.fromisoformat(sys.argv[6]))
model = ScriptedModel([])
tool = ScriptedTool('fixture.read', {'one': {'text': 'First source'}, 'two': {'text': 'Second source'}})
runtime = AgentRuntime(db, clock, model, ToolRegistry([tool]))
runtime.advance_slice(auth, sys.argv[3], max_operations=1)
print(json.dumps({'decisions': len(model.calls), 'tools': len(tool.calls)}))
'''
    replaced = subprocess.run([sys.executable, "-c", program, env.db.database_url, auth.owner_id, run["id"],
                               inst.id, env.clock.now().isoformat(), auth.expires_at.isoformat()],
                              env={**os.environ, "PYTHONPATH": "backend"}, capture_output=True, text=True, check=True)
    assert json.loads(replaced.stdout) == {"decisions": 0, "tools": 1}

    # A fresh coordinator and database handle have no process-local continuation.
    reopened = Database(env.db.database_url)
    reopened.migrate()
    question = envelope(control={"next": "wait_owner", "question": "Which audience?", "options": ["Engineering", "General"]})
    next_model = ScriptedModel([question, finish])
    resumed = AgentRuntime(reopened, env.clock, next_model, runtime.tools)
    waiting = resumed.advance_slice(auth, run["id"], max_operations=10)
    assert waiting["status"] == "waiting_owner"
    assert len(tool.calls) == 1 and len(next_model.calls) == 1
    state = resumed.read(auth, run["id"])
    question_id = state["checkpoint"]["question"]["id"]
    resumed.answer(auth, run["id"], question_id, "Engineering", "answer-1")
    resumed.answer(auth, run["id"], question_id, "Engineering", "answer-1")
    completed = resumed.advance_slice(auth, run["id"], max_operations=10)
    assert completed["status"] == "completed"
    view = resumed.read(auth, run["id"])
    assert set(view["checkpoint"]["completed_artifacts"]) == {"comparison", "summary"}
    assert len(first_model.calls) + len(next_model.calls) == 3
    assert len(tool.calls) + json.loads(replaced.stdout)["tools"] == 2
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_step WHERE run_id=? AND state='applied'", (run["id"],)).fetchone()[0] == 5
        assert conn.execute("SELECT COUNT(*) FROM budget_usage").fetchone()[0] == 5


def test_saved_receipt_replays_without_inference_and_scope_is_enforced(build_env):
    env = build_env()
    auth, inst = active(env)
    runtime, model, tool = setup_runtime(env, [batch()])
    run = runtime.create_run(auth, inst.id, "request-1", definition())

    def crash(stage, _step):
        if stage == "after_receipt":
            raise RuntimeError("simulated process loss")

    with pytest.raises(RuntimeError):
        runtime.advance_slice(auth, run["id"], fault=crash)
    with env.db.reader() as conn:
        step_id = conn.execute("SELECT id FROM agent_step WHERE run_id=?", (run["id"],)).fetchone()[0]
    runtime.record_receipt(auth, run["id"], step_id, AdapterResult(batch()))
    conflicting = {**batch(), "schema_version": True}  # Python's True == 1 must not define JSON identity.
    with pytest.raises(AiclError) as conflict:
        runtime.record_receipt(auth, run["id"], step_id, AdapterResult(conflicting))
    assert conflict.value.error == "conflict"
    env.clock.advance(timedelta(seconds=31))
    replacement = AgentRuntime(env.db, env.clock, ScriptedModel([]), runtime.tools)
    replacement.advance_slice(auth, run["id"], max_operations=3)
    assert len(model.calls) == 1 and len(tool.calls) == 2
    foreign, _ = env.new_instance()
    with pytest.raises(AiclError) as error:
        replacement.read(foreign, run["id"])
    assert error.value.error == "not_found"


def test_unknown_dispatch_retains_reservation_and_does_not_retry(build_env):
    env = build_env()
    auth, inst = active(env)
    runtime, model, _ = setup_runtime(env, [batch()])
    run = runtime.create_run(auth, inst.id, "request-unknown", definition())

    def crash(stage, _step):
        if stage == "after_dispatch_intent":
            raise RuntimeError("lost acknowledgement")

    with pytest.raises(RuntimeError):
        runtime.advance_slice(auth, run["id"], fault=crash)
    env.clock.advance(timedelta(seconds=31))
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "blocked" and result["reason"] == "unknown_outcome"
    assert model.calls == []
    with env.db.reader() as conn:
        assert conn.execute("SELECT state FROM budget_hold").fetchone()[0] == "unknown"


def test_owner_steering_supersedes_remaining_actions_without_repeating_read(build_env):
    env = build_env()
    auth, inst = active(env)
    runtime, model, tool = setup_runtime(env, [batch(), finish])
    run = runtime.create_run(auth, inst.id, "request-steer", definition())
    runtime.advance_slice(auth, run["id"], max_operations=2)
    runtime.append_owner_message(auth, run["id"], "Use only the first source", "steering-1")
    runtime.pause(auth, run["id"])
    assert runtime.advance_slice(auth, run["id"])["status"] == "paused"
    runtime.resume(auth, run["id"])
    assert runtime.advance_slice(auth, run["id"])["status"] == "completed"
    assert len(tool.calls) == 1 and len(model.calls) == 2
    assert model.calls[-1]["owner_messages"][-1]["text"] == "Use only the first source"


def test_successful_read_reuse_and_tool_free_draft_do_not_add_dispatches(build_env):
    env = build_env()
    auth, inst = active(env)
    first = batch()
    first["actions"] = first["actions"][:1]
    runtime, model, tool = setup_runtime(env, [first, first, finish])
    run = runtime.create_run(auth, inst.id, "cached", definition())
    assert runtime.advance_slice(auth, run["id"])["status"] == "completed"
    assert len(tool.calls) == 1 and len(model.calls) == 3
    assert any(event["kind"] == "read_reused" for event in runtime.read(auth, run["id"])["events"])

    def draft_done(context):
        assert context["artifacts"]["draft"]["tail"] == "First draft"
        return envelope(artifacts=[{"local_ref": "draft", "content": "Finished draft", "evidence_refs": []}],
                        control={"next": "complete", "artifact_refs": ["draft"],
                                 "criterion_assessments": [{"requirement_id": "write", "status": "met",
                                                            "explanation": "Finished", "evidence_refs": []}]})

    draft = envelope(artifacts=[{"local_ref": "draft", "content": "First draft", "evidence_refs": []}],
                     control={"next": "continue_draft", "requirement_ids": ["write"], "reason": "Finish the next section"})
    writer, writing_model, _ = setup_runtime(env, [draft, draft_done])
    writing = writer.create_run(auth, inst.id, "writing", RunDefinition(objective="Write a short explanation",
                                requirements=[{"id": "write", "text": "Explain clearly"}], allowed_tools=[]))
    complete = writer.advance_slice(auth, writing["id"])
    assert complete["status"] == "completed" and complete["draft_count"] == 1
    assert complete["action_count"] == 0 and len(writing_model.calls) == 2
    assert complete["checkpoint"]["artifacts"]["draft"]["version"] == 2


def test_atomic_envelope_replay_and_owner_requirement_enforcement(build_env, monkeypatch):
    env = build_env()
    auth, inst = active(env)
    runtime, model, _ = setup_runtime(env, [finish])
    run = runtime.create_run(auth, inst.id, "atomic", definition())
    put = runtime.repo.put_content

    def fail_second(conn, identity_auth, run_id, kind, payload, identity=None):
        if kind == "artifact" and payload["local_ref"] == "summary":
            raise RuntimeError("storage interruption")
        return put(conn, identity_auth, run_id, kind, payload, identity)

    monkeypatch.setattr(runtime.repo, "put_content", fail_second)
    with pytest.raises(RuntimeError):
        runtime.advance_slice(auth, run["id"])
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_content WHERE kind='artifact'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM budget_usage").fetchone()[0] == 1
    monkeypatch.setattr(runtime.repo, "put_content", put)
    env.clock.advance(timedelta(seconds=31))
    assert runtime.advance_slice(auth, run["id"])["status"] == "completed"
    assert len(model.calls) == 1

    invalid = finish({"observations": [], "plan": {}})
    invalid["control"]["criterion_assessments"] = invalid["control"]["criterion_assessments"][:1]
    rejected, _, _ = setup_runtime(env, [invalid])
    other = rejected.create_run(auth, inst.id, "requirements", definition(), limits={"max_invalid_decisions": 0})
    stopped = rejected.advance_slice(auth, other["id"])
    assert stopped["status"] == "blocked" and stopped["reason"] == "invalid_decision"
    assert stopped["checkpoint"]["artifacts"] == {}


def test_known_usage_survives_invalid_payload_and_new_owner_direction(build_env):
    env = build_env()
    auth, inst = active(env)
    runtime, model, _ = setup_runtime(env, [{"invalid": {1, 2}}, finish])
    run = runtime.create_run(auth, inst.id, "bad-json", definition())
    assert runtime.advance_slice(auth, run["id"])["status"] == "completed"
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM budget_usage").fetchone()[0] == 2
    assert len(model.calls) == 2

    def racing(context):
        directed.append_owner_message(auth, target["id"], "Focus on accessibility", "race")
        return batch()

    directed, decision_model, tool = setup_runtime(env, [racing, finish])
    target = directed.create_run(auth, inst.id, "racing-owner", definition())
    assert directed.advance_slice(auth, target["id"])["status"] == "completed"
    assert not tool.calls and len(decision_model.calls) == 2
    assert decision_model.calls[-1]["owner_messages"][-1]["text"] == "Focus on accessibility"


def test_paged_evidence_keeps_text_and_offsets_and_rejects_foreign_refs(build_env):
    env = build_env()
    auth, inst = active(env)
    source = {"text": ('Quoted "material"\\n' * 1000)}
    tool = ScriptedTool("fixture.read", {"one": source})
    first = batch()
    first["actions"] = first["actions"][:1]

    def retrieve(context):
        ref = context["observations"][0]["ref"]
        return envelope(actions=[{"name": "artifact.read", "arguments": {"ref": ref, "offset": offset, "max_chars": 4000}}
                                 for offset in (0, 4000)])

    def checked_finish(context):
        chunks = [entry["result"] for entry in context["observations"] if entry["tool"] == "artifact.read"]
        assert [chunk["next_offset"] for chunk in chunks] == [4000, 8000]
        assert ''.join(chunk["text"] for chunk in chunks) == canonical_json({"error": None, "value": source})[:8000]
        return finish(context)

    runtime, _, _ = setup_runtime(env, [first, retrieve, checked_finish], ToolRegistry([tool]))
    run = runtime.create_run(auth, inst.id, "pagination", definition())
    assert runtime.advance_slice(auth, run["id"])["status"] == "completed"

    # An envelope with a valid draft/memory update and an invalid scoped action
    # must apply none of them, even though its provider receipt settles.
    bad = envelope(artifacts=[{"local_ref": "leak", "content": "Must not save", "evidence_refs": []}],
                   memory=[{"op": "upsert", "key": "note", "kind": "assumption", "text": "Must not save", "evidence_refs": []}],
                   actions=[{"name": "artifact.read", "arguments": {"ref": run["definition_ref"]}}])
    isolated, _, _ = setup_runtime(env, [bad])
    separate = isolated.create_run(auth, inst.id, "separate-run", definition(), limits={"max_invalid_decisions": 0})
    blocked = isolated.advance_slice(auth, separate["id"])
    assert blocked["reason"] == "invalid_decision"
    assert blocked["checkpoint"]["artifacts"] == blocked["checkpoint"]["memory"] == {}
    assert blocked["action_count"] == 0


def test_failed_reads_are_not_cached_and_repeated_work_stops(build_env):
    env = build_env()
    auth, inst = active(env)
    first = batch()
    first["actions"] = first["actions"][:1]
    huge = ScriptedTool("fixture.read", {"one": {"text": "x" * 140000}})
    stopped = envelope(control={"next": "blocked", "reason": "source_unusable", "partial_artifact_refs": []})
    runtime, _, _ = setup_runtime(env, [first, first, stopped], ToolRegistry([huge]))
    run = runtime.create_run(auth, inst.id, "oversized", definition())
    assert runtime.advance_slice(auth, run["id"])["reason"] == "source_unusable"
    assert len(huge.calls) == 2
    assert not any(event["kind"] == "read_reused" for event in runtime.read(auth, run["id"])["events"])

    repeated, model, tool = setup_runtime(env, [first] * 6)
    run = repeated.create_run(auth, inst.id, "repeated", definition())
    blocked = repeated.advance_slice(auth, run["id"])
    assert blocked["reason"] == "no_progress"
    assert len(tool.calls) == 1 and len(model.calls) == 4
    assert len(model.calls[-1]["observations"]) == 1
