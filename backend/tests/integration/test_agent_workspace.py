"""Shared workspace drafts, owner application, and migration preserve one state."""
from dataclasses import replace
from types import SimpleNamespace
import json
import uuid

import pytest

from aicl.agent_workspace.service import WorkspaceService
from aicl.agent_runtime.adapters import ScriptedTool, ToolRegistry
from aicl.agent_runtime.storage import Repository
from aicl.control.errors import AiclError
from aicl.control.budget import Estimate
from aicl.control.instances import Limits
from aicl.creation.operations import SqliteInstanceOperations
from aicl.db import to_iso
from aicl.workflow.service import MockWorkflowService
from aicl.network.research_policy import SearchProviderPolicy, research_binding


class ResearchFixture:
    """Metadata-only fixture; no broker/provider effect is available."""
    available_names = ("web.read",)

    def capabilities(self):
        return [{"name": name, "capability": "network.search" if name == "web.search" else "network.fetch",
                 "description": "Exact owner-released public research."} for name in self.available_names]

    def status(self, *, tools, mode="exact"):
        return {"available": True, "available_tools": ["web.search", "web.read"],
                "provider_binding": research_binding(SearchProviderPolicy("brave", "fixture-account", "fixture-key-reference", 5000, "fixture-v1"), mode=mode),
                "message": "Fixture research control configured.", "recipient_label": "Fixture search account and exact public page hosts."}


def apply(service, auth, state):
    return service.apply(auth, state["id"], state["version"],
                         approved_public_research_digest=state["public_research_release"]["draft_digest"])


def setup(build_env):
    env = build_env()
    auth, instance = env.new_instance(capabilities=("inference",))
    page = ScriptedTool("web.read", {})
    page.capability = "network.fetch"
    page.descriptor = {"name": "web.read", "description": "Read exact owner-released public pages through AICL."}
    runtime = SimpleNamespace(tools=ToolRegistry([page]))
    service = WorkspaceService(SimpleNamespace(db=env.db, clock=env.clock, agent_runtime=runtime,
                                               public_research=ResearchFixture()))
    return env, auth, instance, service


def draft():
    return {"name": "Daily brief", "goal": "Summarize supplied public articles", "inputs": "Owner provides article links.",
            "deliverables": [{"key": "brief", "name": "Brief", "description": "A concise report", "criteria": ["Link sources"]}],
            "tools": ["web.read"], "network_domains": ["example.com"],
            "public_research": {"purpose": "Summarize public AI reporting", "queries": ["AI research news"], "source_urls": ["https://example.com/news"]},
            "limits": {"inference_daily_micro_usd": 500_000, "inference_monthly_micro_usd": 5_000_000,
                       "compute_daily_micro_usd": 0, "compute_monthly_micro_usd": 0},
            "cadence": "daily", "timezone": "America/New_York", "time_of_day": "09:00"}


def with_search(service):
    search = ScriptedTool("web.search", {})
    search.capability = "network.search"
    search.descriptor = {"name": "web.search", "title": "Public web search", "description": "Discover public sources."}
    service.ctx.agent_runtime.tools = ToolRegistry([service.ctx.agent_runtime.tools.get("web.read"), search])
    service.ctx.public_research.available_names = ("web.read", "web.search")


def test_search_permission_needs_exact_release_but_no_page_domains(build_env):
    env, auth, instance, service = setup(build_env)
    with_search(service)
    state = service.open(auth, instance_id=instance.id)
    state = service.update_draft(auth, state["id"], state["version"],
                                 {**draft(), "inputs": "Discover useful public sources.",
                                  "tools": ["web.search"], "network_domains": []}, actor="assistant")
    with env.db.reader() as conn:
        assert not conn.execute("SELECT enabled FROM capability_grant WHERE instance_id=? AND capability='network.search'", (instance.id,)).fetchone()[0]
    state = apply(service, auth, state)
    assert state["published"]["tools"] == ["web.search"] and not state["published"]["network_domains"]
    with env.db.reader() as conn:
        grants = {row[0]: row[1] for row in conn.execute("SELECT capability,enabled FROM capability_grant WHERE instance_id=?", (instance.id,))}
        assert grants["network.search"] and grants["inference"] and not grants["network.fetch"]
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 0
    both = service.update_draft(auth, state["id"], state["version"], {"tools": ["web.search", "web.read"]})
    with pytest.raises(AiclError, match="validation_failed"):
        apply(service, auth, both)
    disabled = service.update_draft(auth, state["id"], both["version"], {"tools": []})
    apply(service, auth, disabled)
    with env.db.reader() as conn:
        assert not conn.execute("SELECT enabled FROM capability_grant WHERE instance_id=? AND capability='network.search'", (instance.id,)).fetchone()[0]


def test_legacy_search_import_is_a_reviewable_choice_without_implicit_grant(build_env):
    env, auth, instance, service = setup(build_env)
    with_search(service)
    MockWorkflowService(env.db, env.clock).save_config(auth, instance.id,
        {**draft(), "scenario": "general", "tools": ["web_search"]}, 1)
    state = service.open(auth, instance_id=instance.id)
    assert state["draft"]["tools"] == ["web.search"] and state["published"] is None
    with env.db.reader() as conn:
        assert not conn.execute("SELECT enabled FROM capability_grant WHERE instance_id=? AND capability='network.search'", (instance.id,)).fetchone()[0]


def test_removing_unavailable_search_still_revokes_its_existing_grant(build_env):
    env, auth, instance, service = setup(build_env)
    with_search(service)
    state = service.open(auth, instance_id=instance.id)
    state = service.update_draft(auth, state["id"], state["version"],
                                 {**draft(), "tools": ["web.search"], "network_domains": []})
    state = apply(service, auth, state)
    service.ctx.agent_runtime.tools = ToolRegistry([service.ctx.agent_runtime.tools.get("web.read")])
    service.ctx.public_research.available_names = ("web.read",)
    state = service.update_draft(auth, state["id"], state["version"], {"tools": []})
    state = apply(service, auth, state)
    assert state["published"]["tools"] == []
    with env.db.reader() as conn:
        assert not conn.execute("SELECT enabled FROM capability_grant WHERE instance_id=? AND capability='network.search'", (instance.id,)).fetchone()[0]


def test_open_imports_once_without_changing_agent_controls(build_env):
    env, auth, instance, service = setup(build_env)
    workflow = MockWorkflowService(env.db, env.clock)
    workflow.save_config(auth, instance.id, {**draft(), "scenario": "general", "tools": ["web_search"]}, 1)
    state = service.open(auth, instance_id=instance.id)
    assert service.open(auth, instance_id=instance.id)["id"] == state["id"]
    assert state["draft"]["tools"] == ["web_search"]
    assert state["published"] is None and state["dirty"]
    assert [item["name"] for item in state["capabilities"]] == ["web.read"]
    with env.db.transaction() as conn:
        before = conn.total_changes
        assert service.view(auth, state["id"])["version"] == 1
        assert conn.total_changes == before
        row = conn.execute("SELECT * FROM agent_instance WHERE id=?", (instance.id,)).fetchone()
        assert row["version"] == 1 and row["lifecycle"] == "draft"
        assert conn.execute("SELECT COUNT(*) FROM agent_workspace").fetchone()[0] == 1


def test_owner_and_assistant_edit_same_draft_with_stale_write_protection(build_env):
    env, auth, instance, service = setup(build_env)
    state = service.open(auth)
    edited = service.update_draft(auth, state["id"], state["version"], {"goal": "A partial idea"}, actor="assistant")
    assert edited["version"] == 2 and edited["draft"]["goal"] == "A partial idea"
    with pytest.raises(AiclError, match="conflict"):
        service.update_draft(auth, state["id"], state["version"], {"name": "Overwrite"})
    latest = service.update_draft(auth, state["id"], edited["version"], {"name": "Owner title"})
    assert latest["draft"]["goal"] == "A partial idea"
    assert latest["draft"]["name"] == "Owner title"
    assert service.open(auth, session_id=state["session_id"])["id"] == state["id"]
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_instance").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 0


def test_apply_creates_canonical_instance_atomically_without_running_or_payment(build_env):
    env, auth, instance, service = setup(build_env)
    state = service.open(auth)
    state = service.update_draft(auth, state["id"], state["version"], draft(), actor="assistant")
    applied = apply(service, auth, state)
    assert applied["instance_id"] != instance.id
    assert applied["published"] == applied["draft"] and not applied["dirty"]
    assert applied["draft"]["timezone"] == "America/New_York"
    assert not applied["external_conflict"]
    with env.db.reader() as conn:
        saved = conn.execute("SELECT * FROM agent_instance WHERE id=?", (applied["instance_id"],)).fetchone()
        assert saved["lifecycle"] == "draft"
        assert saved["inference_daily_micro_usd"] == 500_000
        grants = {row[0]: row[1] for row in conn.execute("SELECT capability,enabled FROM capability_grant WHERE instance_id=?", (saved["id"],))}
        assert grants["inference"] and grants["network.fetch"]
        assert not grants["gmail.send"]
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM mock_commerce_order").fetchone()[0] == 0
    assert service.open(auth, instance_id=applied["instance_id"])["id"] == state["id"]


def test_apply_rejects_incomplete_or_unavailable_tools_without_partial_creation(build_env):
    env, auth, instance, service = setup(build_env)
    state = service.open(auth)
    with pytest.raises(AiclError, match="validation_failed"):
        apply(service, auth, state)
    state = service.update_draft(auth, state["id"], state["version"], {**draft(), "tools": ["web_search"]})
    with pytest.raises(AiclError, match="validation_failed"):
        apply(service, auth, state)
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_instance").fetchone()[0] == 1
        assert conn.execute("SELECT instance_id FROM agent_workspace WHERE id=?", (state["id"],)).fetchone()[0] is None


def test_external_controls_conflict_in_view_and_apply(build_env):
    env, auth, instance, service = setup(build_env)
    state = service.open(auth, instance_id=instance.id)
    state = service.update_draft(auth, state["id"], state["version"], draft())
    SqliteInstanceOperations(env.db, env.clock).set_capability(auth, instance.id, 1, "network.fetch", True)
    assert service.view(auth, state["id"])["external_conflict"]
    with pytest.raises(AiclError, match="conflict"):
        apply(service, auth, state)
    assert service.view(auth, state["id"])["published"] is None


def test_workspace_scope_checks_owner_and_session(build_env):
    env, auth, instance, service = setup(build_env)
    state = service.open(auth, instance_id=instance.id)
    foreign = replace(auth, owner_id=str(uuid.uuid4()))
    for action in (lambda: service.view(foreign, state["id"]),
                   lambda: service.open(foreign, instance_id=instance.id),
                   lambda: service.open(foreign, session_id=state["session_id"]),
                   lambda: service.update_draft(foreign, state["id"], 1, {"goal": "bad"}),
                   lambda: service.apply(foreign, state["id"], 1)):
        with pytest.raises(AiclError, match="not_found"):
            action()


def test_legacy_pending_proposal_and_conversation_survive_import(build_env):
    env, auth, instance, service = setup(build_env)
    session = str(uuid.uuid4())
    proposal = {**draft(), "scenario": "general", "budget_notes": "Review before paying"}
    with env.db.transaction() as conn:
        now = to_iso(env.clock.now())
        conn.execute("INSERT INTO assistant_session VALUES (?,?,?,?,?)", (session, auth.tenant_id, auth.owner_id, now, now))
        conn.execute("INSERT INTO assistant_message(session_id,role,text,created_at) VALUES (?,'user',?,?)",
                     (session, "A daily brief at 9 Eastern", now))
        conn.execute("INSERT INTO assistant_proposal(id,session_id,tenant_id,owner_id,version,kind,data_json,state,created_at,updated_at) "
                     "VALUES (?,?,?,?,1,'create',?,'pending',?,?)",
                     (str(uuid.uuid4()), session, auth.tenant_id, auth.owner_id, json.dumps(proposal), now, now))
    state = service.open(auth, session_id=session)
    assert state["instance_id"] is None and state["session_id"] == session
    assert state["draft"]["goal"] == proposal["goal"]
    assert state["draft"]["timezone"] == "America/New_York"
    assert state["draft"]["deliverables"] == proposal["deliverables"]
    with env.db.reader() as conn:
        assert conn.execute("SELECT text FROM assistant_message WHERE session_id=?", (session,)).fetchone()[0] == "A daily brief at 9 Eastern"
        assert conn.execute("SELECT state FROM assistant_proposal WHERE session_id=?", (session,)).fetchone()[0] == "pending"


def test_apply_keeps_unknown_reservation_and_active_run_definition(build_env):
    env, auth, instance, service = setup(build_env)
    repo = Repository(env.db, env.clock)
    original = {"objective": "The original request", "requirements": [{"id": "one", "text": "Original criterion"}], "allowed_tools": []}
    run = repo.create_run(auth, instance.id, "existing-run", original, {})
    with env.db.transaction() as conn:
        hold = env.budget.reserve(conn, instance.id, "unresolved-operation", Estimate(100, 100, 0))
        env.budget.mark_unknown(conn, hold.id)
        held_before = dict(conn.execute("SELECT * FROM budget_hold WHERE id=?", (hold.id,)).fetchone())
    state = service.open(auth, instance_id=instance.id)
    state = service.update_draft(auth, state["id"], state["version"], draft())
    apply(service, auth, state)
    with env.db.reader() as conn:
        assert dict(conn.execute("SELECT * FROM budget_hold WHERE id=?", (hold.id,)).fetchone()) == held_before
        assert repo.get_content(conn, auth, run["id"], run["definition_ref"]) == original
        assert conn.execute("SELECT run_id FROM agent_workspace_run WHERE workspace_id=?", (state["id"],)).fetchone()[0] == run["id"]


def test_external_workflow_edit_is_stale_and_failed_apply_rolls_back(build_env, monkeypatch):
    env, auth, instance, service = setup(build_env)
    state = service.open(auth, instance_id=instance.id)
    state = service.update_draft(auth, state["id"], state["version"], draft())
    MockWorkflowService(env.db, env.clock).save_config(auth, instance.id, {**draft(), "tools": [], "scenario": "general"}, 1)
    assert service.view(auth, state["id"])["external_conflict"]
    with pytest.raises(AiclError, match="conflict"):
        apply(service, auth, state)
    new = service.open(auth)
    new = service.update_draft(auth, new["id"], new["version"], draft())
    def fail(*args, **kwargs):
        raise AiclError("unavailable", "Injected write failure")
    monkeypatch.setattr(service.workflow, "save_config", fail)
    with pytest.raises(AiclError, match="unavailable"):
        apply(service, auth, new)
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_instance").fetchone()[0] == 1
        assert conn.execute("SELECT instance_id FROM agent_workspace WHERE id=?", (new["id"],)).fetchone()[0] is None


def test_explicit_reload_recovers_external_controls_without_losing_canonical_schedule(build_env):
    env, auth, instance, service = setup(build_env)
    state = service.open(auth, instance_id=instance.id)
    state = service.update_draft(auth, state["id"], state["version"], {**draft(), "cadence": "manual", "time_of_day": "10:15"})
    state = apply(service, auth, state)
    published = state["published"]
    with env.db.reader() as conn:
        version = conn.execute("SELECT version FROM agent_instance WHERE id=?", (instance.id,)).fetchone()[0]
    SqliteInstanceOperations(env.db, env.clock).set_limits(auth, instance.id, version, Limits(100_000, 1_000_000, 0, 0))
    state = service.update_draft(auth, state["id"], state["version"], {"name": "Unsaved title"})
    assert state["external_conflict"]
    replaced = service.reload(auth, state["id"], state["version"])
    assert not replaced["external_conflict"] and replaced["dirty"]
    assert replaced["session_id"] == state["session_id"]
    assert replaced["draft"]["name"] == "Daily brief"
    assert replaced["draft"]["limits"]["inference_daily_micro_usd"] == 100_000
    assert replaced["draft"]["cadence"] == "manual" and replaced["draft"]["time_of_day"] == "10:15"
    assert replaced["draft"]["tools"] == ["web.read"] and replaced["published"] == published
    with pytest.raises(AiclError, match="conflict"):
        service.reload(auth, state["id"], state["version"])
    applied = apply(service, auth, replaced)
    assert not applied["dirty"] and not applied["external_conflict"]
