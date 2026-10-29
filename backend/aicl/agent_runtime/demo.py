"""Run a disposable, network-free durable-session demonstration.

PYTHONPATH=backend .venv/bin/python -m aicl.agent_runtime.demo
"""
from __future__ import annotations

import json
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aicl.agent_runtime.adapters import ScriptedModel, ScriptedTool, ToolRegistry
from aicl.agent_runtime.contracts import RunDefinition
from aicl.agent_runtime.coordinator import AgentRuntime
from aicl.clock import FakeClock
from aicl.control.auth import AuthContext
from aicl.control.instances import AgentInstance, CapabilityGrant, Limits, SqliteInstanceRepository
from aicl.control.price_table import import_price_table
from aicl.db import Database


def demonstrate(directory):
    clock = FakeClock(datetime(2026, 10, 26, 12, tzinfo=timezone.utc))
    db = Database(f"sqlite:///{Path(directory) / 'session.db'}")
    db.migrate()
    owner, instance_id = str(uuid.uuid4()), str(uuid.uuid4())
    auth = AuthContext(owner, owner, "local-demo", clock.now() + timedelta(days=1))
    instance = AgentInstance(instance_id, owner, owner, "default", "Session proof",
                             "Compare synthetic documents", "draft", None, None, 1,
                             Limits(1000000, 1000000, 1000000, 1000000), (), clock.now(), clock.now())
    with db.transaction() as conn:
        import_price_table(conn, Path(__file__).resolve().parents[1] / "price_table.example.json")
        SqliteInstanceRepository().insert_draft(conn, auth, instance, (CapabilityGrant(instance_id, "inference", True),))
        conn.execute("UPDATE agent_instance SET lifecycle='active' WHERE id=?", (instance_id,))
    tools = ToolRegistry([ScriptedTool("fixture.read", {"first": {"text": "A retains revisions"},
                                                       "second": {"text": "B retains revisions and history"}})])
    definition = RunDefinition(objective="Compare the supplied documents for an engineering audience",
                               requirements=[{"id": "compare", "text": "Produce a comparison and a short summary"}],
                               allowed_tools=["fixture.read"])
    initial_model = ScriptedModel([{
        "schema_version": 1,
        "plan_patch": {"upsert": [{"id": "inspect", "title": "Inspect supplied documents",
                                    "requirement_ids": ["compare"], "criteria": ["Use both documents"], "state": "active"}], "remove": []},
        "actions": [{"name": "fixture.read", "arguments": {"key": key}, "plan_item_id": "inspect"}
                    for key in ("first", "second")], "control": {"next": "continue"}}])
    runtime = AgentRuntime(db, clock, initial_model, tools)
    run = runtime.create_run(auth, instance_id, "local-demonstration", definition)
    runtime.advance_slice(auth, run["id"], max_operations=2)

    def finish(context):
        refs = [item["ref"] for item in context["observations"]]
        return {"schema_version": 1,
                "output": {"message": "The comparison and summary are ready.", "artifacts": [
                    {"local_ref": "comparison", "content": "Both retain revisions. B also retains history.", "evidence_refs": refs},
                    {"local_ref": "summary", "content": "B includes history retention.", "evidence_refs": refs}]},
                "memory_updates": [{"op": "upsert", "key": "difference", "kind": "observation",
                                    "text": "B retains history as well as revisions.", "evidence_refs": refs}],
                "plan_patch": {"upsert": [{**context["plan"]["inspect"], "state": "completed", "evidence_refs": refs}], "remove": []},
                "control": {"next": "complete", "artifact_refs": ["comparison", "summary"], "criterion_assessments": [
                    {"requirement_id": "compare", "status": "met", "explanation": "Both outputs use the supplied evidence", "evidence_refs": refs}]}}

    # Fresh service/database objects use only saved state, with no initial decision.
    reopened = Database(db.database_url)
    resumed_model = ScriptedModel([{"schema_version": 1, "control": {"next": "wait_owner",
                                    "question": "Keep the summary brief?", "options": ["Yes", "No"]}}, finish])
    resumed = AgentRuntime(reopened, clock, resumed_model, tools)
    waiting = resumed.advance_slice(auth, run["id"])
    resumed.answer(auth, run["id"], waiting["checkpoint"]["question"]["id"], "Yes", "answer-1")
    completed = resumed.advance_slice(auth, run["id"])
    with reopened.reader() as conn:
        outputs = {key: resumed.repo.get_content(conn, auth, run["id"], value["ref"])["content"]
                   for key, value in completed["checkpoint"]["artifacts"].items()}
    return {"mode": "scripted; no network or paid inference", "status": completed["status"],
            "model_calls": len(initial_model.calls) + len(resumed_model.calls),
            "tool_calls": len(tools.get("fixture.read").calls), "outputs": outputs}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="habitat-session-") as directory:
        print(json.dumps(demonstrate(directory), indent=2))
