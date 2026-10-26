"""Owner confirmations, isolation and no-dispatch boundaries for assistant tools."""

import json
import uuid
from types import SimpleNamespace

import pytest

from aicl.chat.assistant_tools import AssistantTools
from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError
from aicl.creation.service import read_instance_snapshot
from aicl.creation.operations import SqliteInstanceOperations
from aicl.db import to_iso
from aicl.settings import Settings
from aicl.workflow.ad_scenario import pocketplan_preset


def setup(env, base_env, auth=None):
    if auth is None:
        owner = str(uuid.uuid4())
        auth = AuthContext(owner, owner, str(uuid.uuid4()), env.clock.now().replace(year=2099))
    session = str(uuid.uuid4())
    with env.db.transaction() as conn:
        conn.execute("INSERT INTO assistant_session VALUES (?,?,?,?,?)", (session, auth.tenant_id, auth.owner_id,
                     to_iso(env.clock.now()), to_iso(env.clock.now())))
    ctx = SimpleNamespace(db=env.db, clock=env.clock, settings=Settings.from_env(base_env))
    return AssistantTools(ctx, auth, session)


def data():
    preset = pocketplan_preset()
    return {"scenario": "pocketplan_ads", "name": "PocketPlan marketer", "goal": preset["goal"], "inputs": preset["inputs"],
            "cadence": preset["cadence"], "timezone": preset["timezone"], "budget_notes": "$30 is a proposed ad budget, not approval.",
            "deliverables": [{key: item[key] for key in ("key", "name", "description", "criteria")} for item in preset["deliverables"]]}


def count(tools, table):
    with tools.db.reader() as conn:
        return conn.execute("SELECT count(*) FROM " + table).fetchone()[0]


def test_custom_proposal_keeps_owner_goal_tools_and_creates_general_draft(build_env, base_env):
    tools = setup(build_env(), base_env)
    request = {"name": "Trail maintenance planner", "goal": "Prepare trail maintenance recommendations, prioritizing drainage and visitor accessibility.",
               "inputs": "For volunteer coordinators. Cite public guidance and distinguish findings from assumptions.",
               "cadence": "daily", "timezone": "America/New_York", "budget_notes": "Review limits before running.",
               "tools": ["web_search"],
               "deliverables": [{"key": "maintenance_plan", "name": "Maintenance plan", "description": "A concise plan supported by relevant public guidance.",
                                 "criteria": ["Link the sources", "Prioritize drainage", "Address visitor accessibility"]}]}
    proposal = tools.invoke("save_agent_proposal", request)["proposal"]
    assert tools.invoke("validate_agent_proposal", {})["valid"]
    assert count(tools, "agent_instance") == 0
    result = tools.confirm(proposal["id"], proposal["version"])
    config = tools.workflow.config(tools.auth, result["instance_id"])
    assert config["scenario"] == "general" and config["goal"] == request["goal"]
    assert config["tools"] == request["tools"]
    assert [s["key"] for s in config["deliverables"]] == ["maintenance_plan"]
    assert not config["enabled"] and count(tools, "workflow_inference_attempt") == 0
    capabilities = tools.invoke("get_supported_capabilities", {})
    assert capabilities["worker"]["id"] == "general"
    assert capabilities["worker"]["inference_mode"] == "unavailable"
    assert {s["id"] for s in capabilities["tools"]} >= {"web_search"}
    for invalid in (["shell"], ["web_search", "web_search"]):
        with pytest.raises(AiclError, match="validation_failed"):
            tools.invoke("save_agent_proposal", request | {"tools": invalid})
    supplied_only = {key: value for key, value in request.items() if key != "tools"}
    pending = tools.invoke("save_agent_proposal", supplied_only)["proposal"]
    assert pending["tools"] == [] and tools.proposal()["data"]["tools"] == []
    assert count(tools, "agent_instance") == 1


def test_saved_legacy_marketing_proposal_preserves_its_workflow(build_env, base_env):
    tools = setup(build_env(), base_env)
    proposal = tools.invoke("save_agent_proposal", data())["proposal"]
    # A persisted pre-upgrade proposal has no scenario/tool fields.
    with tools.db.transaction() as conn:
        saved = json.loads(conn.execute("SELECT data_json FROM assistant_proposal WHERE id=?", (proposal["id"],)).fetchone()[0])
        saved.pop("scenario", None)
        saved.pop("tools", None)
        conn.execute("UPDATE assistant_proposal SET data_json=? WHERE id=?", (json.dumps(saved), proposal["id"]))
    assert tools.invoke("validate_agent_proposal", {})["valid"]
    result = tools.confirm(proposal["id"], proposal["version"])
    assert tools.workflow.config(tools.auth, result["instance_id"])["scenario"] == "pocketplan_ads"


def test_only_explicit_current_confirmation_creates_atomic_zero_budget_draft(build_env, base_env):
    tools = setup(build_env(), base_env)
    assert "confirm" not in {item["name"] for item in tools.schemas()}
    with pytest.raises(AiclError, match="denied"):
        tools.invoke("confirm", {})
    with pytest.raises(AiclError, match="validation_failed"):
        tools.invoke("save_agent_proposal", data() | {"tenant_id": "foreign", "budget": 1000})
    first = tools.invoke("save_agent_proposal", data())["proposal"]
    current = tools.invoke("save_agent_proposal", data() | {"name": "PocketPlan campaign assistant"})["proposal"]
    assert current["id"] == first["id"] and current["version"] == first["version"] + 1
    validation = tools.invoke("validate_agent_proposal", {})
    assert validation["valid"] and "data" not in validation["proposal"] and "data" not in current
    assert len(json.dumps(validation)) < 2000
    with pytest.raises(AiclError, match="validation_failed") as oversized:
        tools.invoke("save_agent_proposal", data() | {"inputs": "𝒶" * 4000})
    assert "4,500" in oversized.value.message
    assert tools.proposal()["version"] == current["version"]
    assert count(tools, "agent_instance") == 0
    with pytest.raises(AiclError) as stale:
        tools.confirm(first["id"], first["version"])
    assert stale.value.error == "conflict"
    result = tools.confirm(current["id"], current["version"])
    assert tools.confirm(current["id"], current["version"]) == result
    snapshot = read_instance_snapshot(tools.auth, result["instance_id"], clock=tools.clock)
    assert snapshot.name == "PocketPlan campaign assistant" and snapshot.lifecycle == "draft"
    assert snapshot.limits.inference_daily_micro_usd == snapshot.limits.compute_monthly_micro_usd == 0
    assert [key for key, enabled in snapshot.capabilities.items() if enabled] == ["inference"]
    config = tools.workflow.config(tools.auth, snapshot.id)
    assert config["saved"] and not config["enabled"] and config["scenario"] == "pocketplan_ads"
    assert {item["key"] for item in config["deliverables"]} == {"campaign_plan", "ad_creative", "performance_report"}
    assert count(tools, "agent_instance") == 1 and tools.proposal() is None
    for table in ("budget_hold", "budget_usage", "mock_workflow_run", "mock_commerce_order", "mock_commerce_ledger"):
        assert count(tools, table) == 0


def test_failed_config_rolls_back_instance_and_preserves_proposal(build_env, base_env, monkeypatch):
    tools = setup(build_env(), base_env)
    proposal = tools.invoke("save_agent_proposal", data())["proposal"]
    def unavailable(*args, **kwargs):
        raise AiclError("unavailable", "Save failed")
    monkeypatch.setattr(tools.workflow, "save_config", unavailable)
    with pytest.raises(AiclError, match="unavailable"):
        tools.confirm(proposal["id"], proposal["version"])
    assert count(tools, "agent_instance") == count(tools, "create_request") == 0
    assert tools.proposal()["state"] == "pending"


def test_schedule_confirmation_rechecks_versions_and_controls_and_never_dispatches(build_env, base_env):
    tools = setup(build_env(), base_env)
    proposal = tools.invoke("save_agent_proposal", data())["proposal"]
    iid = tools.confirm(proposal["id"], proposal["version"])["instance_id"]
    SqliteInstanceOperations(tools.db, tools.clock).set_capability(tools.auth, iid, 1, "inference", False)
    proposal = tools.invoke("propose_schedule_change", {"instance_id": iid, "enabled": True})["proposal"]
    with pytest.raises(AiclError):
        tools.confirm(proposal["id"], proposal["version"])
    assert not tools.workflow.config(tools.auth, iid)["enabled"]
    assert read_instance_snapshot(tools.auth, iid, clock=tools.clock).lifecycle == "draft"
    # A direct owner policy edit makes the old review stale even without an instance-version change.
    with tools.db.transaction() as conn:
        tools.workflow.commerce._account(conn, iid)
        conn.execute("UPDATE mock_commerce_account SET version=version+1 WHERE instance_id=?", (iid,))
    with pytest.raises(AiclError) as changed:
        tools.confirm(proposal["id"], proposal["version"])
    assert changed.value.error == "conflict"
    # Pausing is reviewable independently of funding; confirm alone changes the schedule.
    with tools.db.transaction() as conn:
        conn.execute("UPDATE mock_workflow_config SET enabled=1,version=version+1 WHERE instance_id=?", (iid,))
    pause = tools.invoke("propose_schedule_change", {"instance_id": iid, "enabled": False})["proposal"]
    assert tools.workflow.config(tools.auth, iid)["enabled"]
    result = tools.confirm(pause["id"], pause["version"])
    assert "paused" in result["message"] and not tools.workflow.config(tools.auth, iid)["enabled"]
    assert count(tools, "mock_workflow_occurrence") == count(tools, "workflow_inference_attempt") == 0


def test_monitoring_and_proposals_are_owner_and_session_scoped_and_reads_do_not_mutate(build_env, base_env):
    env = build_env()
    tools = setup(env, base_env)
    proposal = tools.invoke("save_agent_proposal", data())["proposal"]
    iid = tools.confirm(proposal["id"], proposal["version"])["instance_id"]
    # Same tenant with a different owner is still foreign.
    other_auth = AuthContext(str(uuid.uuid4()), tools.auth.tenant_id, str(uuid.uuid4()), tools.auth.expires_at)
    foreign = setup(env, base_env, other_auth)
    sibling = setup(env, base_env, tools.auth)
    assert foreign.invoke("list_agents", {})["agents"] == []
    for caller in (foreign, sibling):
        with pytest.raises(AiclError) as no_confirm:
            caller.confirm(proposal["id"], proposal["version"])
        assert no_confirm.value.error == "not_found"
    with pytest.raises(AiclError):
        foreign.invoke("inspect_agent", {"instance_id": iid})
    with pytest.raises(AiclError):
        AssistantTools(tools.ctx, foreign.auth, tools.session_id)
    with tools.db.reader() as conn:
        before = conn.execute("SELECT count(*) FROM audit_event").fetchone()[0]
    inspected = tools.invoke("inspect_agent", {"instance_id": iid})
    assert inspected["status"] == "draft" and inspected["available_service_credit_micro_usd"] == 0
    assert inspected["recent_runs"] == inspected["recent_purchases"] == inspected["recent_deliverables"] == []
    assert len(json.dumps(inspected)) < 16000
    assert "tenant_id" not in inspected and "owner_id" not in inspected and "credential" not in inspected
    assert tools.invoke("get_supported_capabilities", {})["worker"]["inference_mode"] == "unavailable"
    with tools.db.reader() as conn:
        assert conn.execute("SELECT count(*) FROM audit_event").fetchone()[0] == before


def test_monitoring_links_real_fixture_work_to_outputs_and_pending_purchase_without_advancing(build_env, base_env):
    from test_pocketplan_workflow import prepared, tick
    env, workflow, _, auth, inst, _ = prepared(build_env)
    tick(workflow, auth, inst.id)
    tools = setup(env, base_env, auth)
    before = {table: count(tools, table) for table in ("audit_event", "mock_workflow_run", "mock_workflow_deliverable", "mock_commerce_ledger")}
    view = tools.invoke("inspect_agent", {"instance_id": inst.id})
    assert view["recent_runs"] and view["recent_deliverables"] and view["recent_purchases"]
    assert any(run["latest_deliverable"] for run in view["recent_runs"])
    assert view["recent_purchases"][0]["state"] == "awaiting_approval"
    assert view["recent_purchases"][0]["amount_minor"] == 3000
    assert all(output["url"].startswith("/audit/deliverables/") for output in view["recent_deliverables"])
    assert all(run["url"].startswith("/audit/jobs/") for run in view["recent_runs"])
    assert {table: count(tools, table) for table in before} == before
    # Monitoring stays within the model context budget even for maximum-size
    # existing generic configurations and Unicode content escaped in JSON.
    config = {"scenario": "generic", "goal": "𝒶" * 2000, "inputs": "𝒶" * 4000,
              "cadence": "daily", "timezone": "UTC", "deliverables": [
                  {"key": "x" + str(index), "name": "𝒶" * 120, "description": "𝒶" * 2000,
                   "criteria": ["𝒶" * 500] * 12} for index in range(6)]}
    workflow.save_config(auth, inst.id, config, workflow.config(auth, inst.id)["version"])
    bounded = tools.invoke("inspect_agent", {"instance_id": inst.id})
    assert len(json.dumps(bounded).encode()) < 5000
    assert bounded["workflow"]["deliverable_count"] == 6
    assert bounded["total_counts"]["purchases"] == 1
