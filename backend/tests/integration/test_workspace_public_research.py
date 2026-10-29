"""Owner releases bind exact disclosures; assistant proposals never authorize egress."""
from dataclasses import replace
import json
import sqlite3
import uuid

import pytest

from aicl.agent_workspace.assistant import WorkspaceAssistantTools
from aicl.control.errors import AiclError
from aicl.network.research_policy import release_digest
from test_agent_workspace import ResearchFixture, apply, draft, setup, with_search


def configured(build_env):
    env, auth, instance, service = setup(build_env)
    with_search(service)
    state = service.open(auth, instance_id=instance.id)
    patch = {**draft(), "goal": "Private project: PRIVATE-CANARY-7482", "inputs": "Diagnostic file: PRIVATE-CANARY-7482",
             "tools": ["web.search", "web.read"]}
    state = service.update_draft(auth, state["id"], state["version"], patch, actor="assistant")
    return env, auth, instance, service, state


def releases(env, workspace_id):
    with env.db.reader() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM workspace_public_research_release WHERE workspace_id=? ORDER BY version", (workspace_id,))]


def test_assistant_can_propose_but_cannot_approve_or_copy_private_context(build_env):
    env, auth, instance, service, state = configured(build_env)
    assert state["public_research_release"]["approval_required"]
    assert "Search account: fixture-account" in state["public_research_release"]["recipient_label"]
    assert "$0.005000" in state["public_research_release"]["recipient_label"]
    assert "fixture-key-reference" not in state["public_research_release"]["recipient_label"]
    with pytest.raises(AiclError) as denied:
        service.apply(auth, state["id"], state["version"])
    assert denied.value.error == "denied" and denied.value.extra["reason"] == "confirmation_required"
    assert releases(env, state["id"]) == []
    tools = WorkspaceAssistantTools(service.ctx, auth, state["id"], state["version"])
    assert {item["name"] for item in tools.schemas()} == {"read_workspace", "update_draft", "show_section"}
    with pytest.raises(AiclError, match="denied"):
        tools.invoke("apply", {"approved_public_research_digest": state["public_research_release"]["draft_digest"]})
    with pytest.raises(AiclError, match="validation_failed"):
        service.update_draft(auth, state["id"], state["version"], {"approved_public_research_digest": state["public_research_release"]["draft_digest"]}, actor="assistant")
    applied = apply(service, auth, state)
    saved = releases(env, state["id"])
    assert len(saved) == 1 and saved[0]["revoked_at"] is None
    assert "PRIVATE-CANARY" not in saved[0]["payload_json"]
    assert json.loads(saved[0]["payload_json"]) == draft()["public_research"]
    assert applied["public_research_release"]["enabled"]
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM budget_hold").fetchone()[0] == 0


def test_exact_changed_query_requires_new_owner_release_and_preserves_history(build_env):
    env, auth, _, service, state = configured(build_env)
    initial_digest = state["public_research_release"]["draft_digest"]
    state = apply(service, auth, state)
    first = releases(env, state["id"])[0]
    proposed = {**state["draft"]["public_research"], "queries": ["news PRIVATE-CANARY-7482"]}
    state = service.update_draft(auth, state["id"], state["version"], {"public_research": proposed}, actor="assistant")
    with pytest.raises(AiclError, match="denied"):
        service.apply(auth, state["id"], state["version"], approved_public_research_digest=initial_digest)
    assert releases(env, state["id"]) == [first]
    assert state["public_research_release"]["draft_digest"] != initial_digest
    state = apply(service, auth, state)
    saved = releases(env, state["id"])
    assert len(saved) == 2 and saved[0]["revoked_at"] and saved[1]["revoked_at"] is None
    assert saved[1]["version"] == 2
    assert saved[0]["payload_json"] == first["payload_json"]


def test_private_changes_and_recurring_unchanged_release_do_not_need_reapproval(build_env):
    env, auth, _, service, state = configured(build_env)
    state = apply(service, auth, state)
    first = releases(env, state["id"])[0]
    state = service.update_draft(auth, state["id"], state["version"], {"inputs": "Different private diagnostics", "time_of_day": "10:00"})
    assert not state["public_research_release"]["approval_required"]
    state = service.apply(auth, state["id"], state["version"])
    state = service.apply(auth, state["id"], state["version"])
    assert releases(env, state["id"]) == [first]
    assert state["public_research_release"]["version"] == 1


def test_recipient_or_price_contract_change_invalidates_existing_approval(build_env):
    env, auth, _, service, state = configured(build_env)
    state = apply(service, auth, state)
    old = releases(env, state["id"])[0]
    class ChangedRecipient(ResearchFixture):
        available_names = ("web.read", "web.search")
        def status(self, *, tools):
            status = super().status(tools=tools)
            status["provider_binding"]["search"]["account_id"] = "different-account"
            return status
    service.ctx.public_research = ChangedRecipient()
    state = service.view(auth, state["id"])
    assert not state["dirty"] and state["public_research_release"]["approval_required"]
    with pytest.raises(AiclError, match="denied"):
        service.apply(auth, state["id"], state["version"])
    assert releases(env, state["id"]) == [old]
    state = apply(service, auth, state)
    assert state["public_research_release"]["version"] == 2


def test_unavailable_containment_cannot_be_overridden_by_owner_payload(build_env):
    env, auth, _, service, state = configured(build_env)
    old_digest = state["public_research_release"]["draft_digest"]
    service.ctx.public_research = None
    state = service.view(auth, state["id"])
    assert not state["public_research_release"]["available"]
    assert state["public_research_release"]["draft_digest"] is None
    with pytest.raises(AiclError, match="validation_failed"):
        service.apply(auth, state["id"], state["version"], approved_public_research_digest=old_digest)
    assert releases(env, state["id"]) == []
    assert state["published"] is None


def test_revocation_and_reenable_require_new_release_with_filtered_operations(build_env):
    env, auth, _, service, state = configured(build_env)
    state = apply(service, auth, state)
    state = service.update_draft(auth, state["id"], state["version"], {"tools": ["web.read"]})
    assert state["draft"]["public_research"]["queries"]
    state = apply(service, auth, state)
    assert json.loads(releases(env, state["id"])[-1]["payload_json"])["queries"] == []
    state = service.update_draft(auth, state["id"], state["version"], {"tools": []})
    state = service.apply(auth, state["id"], state["version"])
    assert all(item["revoked_at"] for item in releases(env, state["id"]))
    state = service.update_draft(auth, state["id"], state["version"], {"tools": ["web.search"]})
    with pytest.raises(AiclError, match="denied"):
        service.apply(auth, state["id"], state["version"])
    state = apply(service, auth, state)
    assert json.loads(releases(env, state["id"])[-1]["payload_json"])["source_urls"] == []
    assert state["public_research_release"]["version"] == 3


def test_stale_or_foreign_owner_cannot_release_and_rows_are_immutable(build_env):
    env, auth, _, service, old = configured(build_env)
    state = service.update_draft(auth, old["id"], old["version"], {"name": "Changed"})
    with pytest.raises(AiclError, match="conflict"):
        apply(service, auth, old)
    with pytest.raises(AiclError, match="not_found"):
        apply(service, replace(auth, owner_id=str(uuid.uuid4())), state)
    state = apply(service, auth, state)
    row = releases(env, state["id"])[0]
    for statement in ("UPDATE workspace_public_research_release SET payload_json='{}' WHERE id=?",
                      "UPDATE workspace_public_research_release SET disclosure_digest='replacement' WHERE id=?",
                      "DELETE FROM workspace_public_research_release WHERE id=?"):
        with pytest.raises(sqlite3.IntegrityError):
            with env.db.transaction() as conn:
                conn.execute(statement, (row["id"],))
    assert releases(env, state["id"]) == [row]


@pytest.mark.parametrize("field,value", [
    ("source_urls", ["https://example.com/news#PRIVATE-CANARY"]),
    ("source_urls", ["https://owner:secret@example.com/news"]),
    ("source_urls", ["http://127.0.0.1/admin"]),
    ("queries", ["news\r\nX-Tenant: PRIVATE-CANARY"]),
])
def test_malformed_disclosure_draft_does_not_mutate_released_authority(build_env, field, value):
    env, auth, _, service, state = configured(build_env)
    state = apply(service, auth, state)
    before = releases(env, state["id"])
    with pytest.raises(AiclError, match="validation_failed"):
        service.update_draft(auth, state["id"], state["version"],
                             {"public_research": {**state["draft"]["public_research"], field: value}}, actor="assistant")
    assert releases(env, state["id"]) == before


@pytest.mark.parametrize("rotate_recipient", [False, True])
def test_real_workspace_admission_binds_release_and_rejects_provider_rotation(build_env, monkeypatch, rotate_recipient):
    """Use the actual service/gate/runtime with only isolated availability mocked.

    The broker itself remains an explicitly offline FixtureResearchWorker plus
    MockTransport. This does not claim real containment or provider verification.
    """
    from aicl.agent_workspace.execution import WorkspaceExecution
    from aicl.agent_workspace.service import WorkspaceService
    from test_runtime_research_prelude import setup as research_setup

    env, auth, instance, runtime, model, research, old_run, outbound, dns, ctx = research_setup(build_env)
    runtime.cancel(auth, old_run["id"])
    monkeypatch.setattr(research, "_status_observation", {
        "page_available": True, "search_available": True, "reason": None, "search_reason": None})
    core = WorkspaceService(ctx)
    state = core.open(auth, instance_id=instance.id)
    proposed = {**draft(), "inputs": "PRIVATE-CANARY remains private", "tools": ["web.search", "web.read"],
                "network_domains": ["news.example"],
                "limits": {"inference_daily_micro_usd": 1_000_000, "inference_monthly_micro_usd": 10_000_000,
                           "compute_daily_micro_usd": 1_000_000, "compute_monthly_micro_usd": 10_000_000},
                "public_research": {"purpose": "Owner-reviewed daily public reporting", "queries": ["Public AI news"],
                                    "source_urls": ["https://news.example/article"]}}
    state = core.update_draft(auth, state["id"], state["version"], proposed, actor="assistant")
    assert outbound == dns == []
    state = apply(core, auth, state)
    approved = state["public_research_release"]["approved_release_id"]
    if rotate_recipient:
        research.broker.provider_policy = replace(research.broker.provider_policy, account_id="different-recipient")
    execution = WorkspaceExecution(ctx)
    before = execution.view(auth, state["id"])
    assert outbound == dns == [] and model.calls == []
    if rotate_recipient:
        assert not before["readiness"]["ready"]
        assert "disclosure_approval_required" in {item["reason"] for item in before["readiness"]["blockers"]}
        with pytest.raises(AiclError, match="denied"):
            execution.start(auth, state["id"], "changed-provider")
        assert outbound == dns == []
        with env.db.reader() as conn:
            assert conn.execute("SELECT COUNT(*) FROM public_research_dispatch").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM budget_hold").fetchone()[0] == 0
    else:
        assert before["readiness"]["ready"], before["readiness"]
        run = execution.start(auth, state["id"], "approved-research")
        with env.db.reader() as conn:
            definition = runtime.repo.get_content(conn, auth, run["id"], run["definition_ref"])
            assert definition["public_research_release_id"] == approved
        runtime.advance_slice(auth, run["id"], max_operations=1)
        assert len(outbound) == 2 and model.calls == []
        assert "PRIVATE-CANARY" not in repr([(str(request.url), dict(request.headers), request.content) for request in outbound])
        saved_status = execution.view(auth, state["id"])["run"]["public_research"]
        assert saved_status["status"] == "completed"
        assert saved_status["successful_searches"] == saved_status["successful_page_reads"] == 1
        assert saved_status["unavailable_page_reads"] == 0
        assert saved_status["additional_web_requests_available"] is False
        # Historical receipts remain readable after the provider changes. This
        # projection cannot authorize a fresh request under the old release.
        research.broker.provider_policy = replace(research.broker.provider_policy, account_id="different-recipient")
        assert execution.view(auth, state["id"])["run"]["public_research"] == saved_status
        assert len(outbound) == 2 and model.calls == []
