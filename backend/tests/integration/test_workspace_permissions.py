"""Intrinsic inference stays inside the canonical AICL controls."""
import json

import pytest

import aicl.db as db_module
from aicl.agent_runtime.storage import Repository
from aicl.agent_workspace.models import empty_draft
from aicl.control.budget import Estimate
from aicl.control.errors import AiclError
from aicl.creation.operations import SqliteInstanceOperations
from test_agent_workspace import apply, draft, setup


def grant(env, instance_id, capability="inference"):
    with env.db.reader() as conn:
        row = conn.execute("SELECT enabled FROM capability_grant WHERE instance_id=? AND capability=?",
                           (instance_id, capability)).fetchone()
        return bool(row and row[0])


def set_grant(env, auth, instance_id, enabled, capability="inference"):
    with env.db.reader() as conn:
        version = conn.execute("SELECT version FROM agent_instance WHERE id=?", (instance_id,)).fetchone()[0]
    SqliteInstanceOperations(env.db, env.clock).set_capability(auth, instance_id, version, capability, enabled)


def snapshot(db):
    with db.reader() as conn:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {table: [dict(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
                for table in tables}


@pytest.mark.parametrize("actor", ["owner", "assistant"])
@pytest.mark.parametrize("enabled", [False, True])
def test_retired_inference_choice_cannot_be_edited(build_env, actor, enabled):
    env, auth, instance, service = setup(build_env)
    state = service.open(auth, instance_id=instance.id)
    assert "inference_enabled" not in empty_draft()
    assert "inference_enabled" not in state["draft"]
    before = snapshot(env.db)
    with pytest.raises(AiclError, match="validation_failed"):
        service.update_draft(auth, state["id"], state["version"], {"inference_enabled": enabled}, actor=actor)
    assert snapshot(env.db) == before


def test_owner_apply_always_enables_inference_and_preserves_other_app_grants(build_env):
    env, auth, instance, service = setup(build_env)
    # Existing simulated app grants are preserved, never promoted to live tools.
    set_grant(env, auth, instance.id, True, "gmail.read")
    set_grant(env, auth, instance.id, False)
    state = service.open(auth, instance_id=instance.id)
    state = service.update_draft(auth, state["id"], state["version"], draft(), actor="assistant")
    assert not grant(env, instance.id)  # A proposal cannot authorize execution.
    state = apply(service, auth, state)
    assert grant(env, instance.id) and grant(env, instance.id, "gmail.read")
    assert "inference_enabled" not in state["draft"] and "inference_enabled" not in state["published"]
    assert "inference_revocation_only" not in state
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 0


def test_new_agent_always_has_intrinsic_inference_without_starting_work(build_env):
    env, auth, _, service = setup(build_env)
    state = service.open(auth)
    state = service.update_draft(auth, state["id"], state["version"], draft())
    state = apply(service, auth, state)
    assert grant(env, state["instance_id"])
    with env.db.reader() as conn:
        assert conn.execute("SELECT lifecycle FROM agent_instance WHERE id=?", (state["instance_id"],)).fetchone()[0] == "draft"
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM mock_commerce_order").fetchone()[0] == 0


@pytest.mark.parametrize("stored_choice", [False, True])
def test_old_saved_choice_is_normalized_without_read_side_writes(build_env, stored_choice):
    env, auth, instance, service = setup(build_env)
    state = service.open(auth, instance_id=instance.id)
    state = service.update_draft(auth, state["id"], state["version"], draft())
    state = apply(service, auth, state)
    # Compatibility is a view projection only, even if a later external revoke
    # means that the real AICL grant does not agree with the old JSON field.
    set_grant(env, auth, instance.id, False)
    with env.db.transaction() as conn:
        legacy = {**state["draft"], "inference_enabled": stored_choice}
        conn.execute("UPDATE agent_workspace SET draft_json=?,published_json=? WHERE id=?",
                     (json.dumps(legacy), json.dumps(legacy), state["id"]))
    before = snapshot(env.db)
    viewed = service.view(auth, state["id"])
    assert "inference_enabled" not in viewed["draft"] and "inference_enabled" not in viewed["published"]
    assert not viewed["dirty"] and viewed["external_conflict"]
    assert not grant(env, instance.id) and snapshot(env.db) == before
    reloaded = service.reload(auth, state["id"], state["version"])
    assert "inference_enabled" not in reloaded["draft"]
    assert "inference_enabled" not in reloaded["published"]


def test_external_inference_revocation_requires_reload_before_owner_apply_repairs_it(build_env):
    env, auth, instance, service = setup(build_env)
    state = service.open(auth, instance_id=instance.id)
    state = service.update_draft(auth, state["id"], state["version"], draft())
    state = apply(service, auth, state)
    set_grant(env, auth, instance.id, False)
    with pytest.raises(AiclError, match="conflict"):
        apply(service, auth, state)
    assert not grant(env, instance.id)
    state = service.reload(auth, state["id"], state["version"])
    assert not state["dirty"]  # Apply must not take its usual unchanged fast path.
    assert state["inference_grant_missing"]
    state = apply(service, auth, state)
    assert not state["inference_grant_missing"]
    assert grant(env, instance.id) and not state["dirty"] and not state["external_conflict"]


def test_intrinsic_inference_migration_preserves_other_controls_and_conflicts(build_env, monkeypatch, tmp_path):
    old = tmp_path / "before-intrinsic-inference"
    old.mkdir()
    for source in db_module.MIGRATIONS_DIR.glob("*.sql"):
        if source.name < "0039_workspace_intrinsic_inference.sql":
            (old / source.name).write_text(source.read_text())
    with monkeypatch.context() as patch:
        patch.setattr(db_module, "MIGRATIONS_DIR", old)
        env, auth, instance, service = setup(build_env)
    repo = Repository(env.db, env.clock)
    run = repo.create_run(auth, instance.id, "existing-run", {"objective": "Keep this private task"}, {})
    with env.db.transaction() as conn:
        hold = env.budget.reserve(conn, instance.id, "unresolved-operation", Estimate(100, 100, 0))
        env.budget.mark_unknown(conn, hold.id)
    state = service.open(auth, instance_id=instance.id)
    state = service.update_draft(auth, state["id"], state["version"], draft())
    state = apply(service, auth, state)
    set_grant(env, auth, instance.id, False)
    state = service.reload(auth, state["id"], state["version"])
    with env.db.transaction() as conn:
        old_json = json.dumps({**state["draft"], "inference_enabled": False})
        conn.execute("UPDATE agent_workspace SET draft_json=?,published_json=? WHERE id=?", (old_json, old_json, state["id"]))
        conn.execute("UPDATE agent_workspace_schedule SET enabled=1,next_due='2026-12-01T09:00:00.000000Z' WHERE workspace_id=?", (state["id"],))
        conn.execute("UPDATE agent_instance SET lifecycle='paused' WHERE id=?", (instance.id,))
    # A second workspace has an unresolved external control change. A third has
    # no inference row. Terminal and non-workspace instances must be untouched.
    identities = {}
    for label in ("conflict", "missing", "archived", "legacy", "enabled"):
        other_auth, other = env.new_instance(capabilities=("inference",) if label == "enabled" else ())
        other_state = service.open(other_auth, instance_id=other.id) if label != "legacy" else None
        identities[label] = (other_auth, other, other_state)
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_instance SET name='Changed elsewhere',version=version+1 WHERE id=?", (identities["conflict"][1].id,))
        conn.execute("DELETE FROM capability_grant WHERE instance_id=? AND capability='inference'", (identities["missing"][1].id,))
        conn.execute("UPDATE agent_instance SET lifecycle='archived' WHERE id=?", (identities["archived"][1].id,))
    before = snapshot(env.db)
    env.db.migrate()
    after = snapshot(env.db)
    changed_tables = {"schema_migration", "agent_instance", "capability_grant", "agent_workspace", "audit_event", "sqlite_sequence"}
    for table in before.keys() - changed_tables:
        assert after[table] == before[table], table
    for table in ("budget_hold", "workspace_public_research_release", "agent_run", "agent_content", "agent_workspace_schedule"):
        assert before[table], table  # Preserve actual rows, not just empty tables.
    upgraded = {instance.id, identities["conflict"][1].id, identities["missing"][1].id}
    before_instances = {row["id"]: row for row in before["agent_instance"]}
    before_workspaces = {row["instance_id"]: row for row in before["agent_workspace"]}
    for saved in after["agent_instance"]:
        expected = dict(before_instances[saved["id"]])
        if saved["id"] in upgraded:
            expected.update(version=expected["version"] + 1, updated_at=saved["updated_at"])
        assert saved == expected
    for saved in after["agent_workspace"]:
        expected = dict(before_workspaces[saved["instance_id"]])
        if saved["instance_id"] in upgraded:
            if expected["source_instance_version"] == before_instances[saved["instance_id"]]["version"]:
                expected["source_instance_version"] += 1
            expected.update(version=expected["version"] + 1, updated_at=saved["updated_at"])
        assert saved == expected
    expected_grants = {(row["instance_id"], row["capability"]): dict(row) for row in before["capability_grant"]}
    for instance_id in upgraded:
        expected_grants[(instance_id, "inference")] = {"instance_id": instance_id, "capability": "inference", "enabled": 1}
    assert {(row["instance_id"], row["capability"]): row for row in after["capability_grant"]} == expected_grants
    assert after["audit_event"][:len(before["audit_event"])] == before["audit_event"]
    events = after["audit_event"][len(before["audit_event"]):]
    assert {event["instance_id"] for event in events} == upgraded and len(events) == len(upgraded)
    for event in events:
        assert event["event_type"] == "instance.capability_changed" and event["actor_kind"] == "system"
        assert event["outcome"] == "committed" and event["reason"] == "workspace_intrinsic_inference"
        assert json.loads(event["details"]) == {"action": "workspace_intrinsic_inference", "capability": "inference",
            "enabled": True, "version": before_instances[event["instance_id"]]["version"] + 1}
    assert not service.view(auth, state["id"])["external_conflict"]
    conflict_auth, _, conflict_state = identities["conflict"]
    assert service.view(conflict_auth, conflict_state["id"])["external_conflict"]
    with env.db.reader() as conn:
        assert conn.execute("SELECT id FROM agent_run WHERE id=?", (run["id"],)).fetchone()
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    env.db.migrate()
    assert snapshot(env.db) == after
