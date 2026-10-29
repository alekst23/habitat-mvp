"""Durable scoped storage preserves replay identity and fences stale workers."""
from dataclasses import replace
from datetime import timedelta
import sqlite3

import pytest

from aicl.control.errors import AiclError
from aicl.db import Database


def setup(build_env):
    from aicl.agent_runtime.storage import Repository
    env = build_env()
    auth, instance = env.new_instance()
    return env, auth, instance, Repository(env.db, env.clock)


def test_storage_restart_replays_admission_and_denies_foreign_content(build_env):
    from aicl.agent_runtime.storage import Repository
    env, auth, instance, repo = setup(build_env)
    definition, limits = {"goal": "Compare public transport options"}, {"decisions": 6}
    run = repo.create_run(auth, instance.id, "request-1", definition, limits)
    restarted = Repository(Database(env.db.database_url), env.clock)
    assert restarted.create_run(auth, instance.id, "request-1", definition, limits)["id"] == run["id"]
    with pytest.raises(AiclError) as error:
        restarted.create_run(auth, instance.id, "request-1", {"goal": "Changed"}, limits)
    assert error.value.error == "conflict"
    assert "different" in error.value.message
    other_run = repo.create_run(auth, instance.id, "request-2", definition, limits)
    foreign_auth, _ = env.new_instance()
    same_tenant_wrong_owner = replace(auth, owner_id=foreign_auth.owner_id)
    with env.db.reader() as conn:
        assert restarted.get_content(conn, auth, run["id"], run["definition_ref"]) == definition
        assert restarted.get_content(conn, auth, run["id"], run["checkpoint_ref"]) == {
            "plan": {}, "memory": {}, "artifacts": {}, "question": None, "completed_artifacts": []}
        for caller in (foreign_auth, same_tenant_wrong_owner):
            with pytest.raises(AiclError) as error:
                restarted.owned_run(conn, caller, run["id"])
            assert error.value.error == "not_found"
        with pytest.raises(AiclError) as error:
            restarted.get_content(conn, auth, other_run["id"], run["definition_ref"])
        assert error.value.error == "not_found"
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 2
    with pytest.raises(AiclError) as error:
        repo.create_run(same_tenant_wrong_owner, instance.id, "forged", definition, limits)
    assert error.value.error == "not_found"


def test_storage_lease_takeover_checkpoint_cas_and_atomic_rollback(build_env):
    env, auth, instance, repo = setup(build_env)
    run = repo.create_run(auth, instance.id, "lease", {"goal": "Research"}, {})
    first = repo.claim(auth, run["id"], "worker-1", lease_seconds=10)
    assert first["version"] == run["version"] and first["fence"] == 1
    with pytest.raises(AiclError):
        repo.claim(auth, run["id"], "worker-2")
    env.clock.advance(timedelta(seconds=11))
    with env.db.reader() as conn, pytest.raises(AiclError):
        repo.check_fence(conn, auth, run["id"], "worker-1", first["fence"])
    second = repo.claim(auth, run["id"], "worker-2")
    assert second["version"] == first["version"] and second["fence"] == 2
    with env.db.transaction() as conn:
        with pytest.raises(AiclError):
            repo.save_checkpoint(conn, auth, first, {"stale": True}, {})
        repo.check_fence(conn, auth, run["id"], "worker-2", second["fence"])
        updated = repo.save_checkpoint(conn, auth, second, {"memory": {"saved": "observation"}}, {"action_count": 1})
    assert updated["version"] == 2
    with env.db.transaction() as conn, pytest.raises(AiclError):
        repo.save_checkpoint(conn, auth, second, {"stale": True}, {})
    with pytest.raises(RuntimeError, match="rollback"):
        with env.db.transaction() as conn:
            repo.save_checkpoint(conn, auth, updated, {"memory": {"lost": True}}, {"status": "completed"})
            raise RuntimeError("rollback")
    with env.db.reader() as conn:
        persisted = repo.owned_run(conn, auth, run["id"])
        assert persisted["version"] == updated["version"]
        assert repo.get_content(conn, auth, run["id"], persisted["checkpoint_ref"]) == {"memory": {"saved": "observation"}}
        assert conn.execute("SELECT COUNT(*) FROM agent_wakeup WHERE run_id=?", (run["id"],)).fetchone()[0] == 1
    released = repo.release(auth, run["id"], "worker-2", second["fence"])
    assert released["status"] == "queued" and released["lease_owner"] is None
    assert released["version"] == updated["version"]
    with pytest.raises(AiclError):
        repo.release(auth, run["id"], "worker-1", first["fence"])


def test_storage_event_replay_immutability_and_owner_pause(build_env):
    env, auth, instance, repo = setup(build_env)
    run = repo.create_run(auth, instance.id, "events", {"goal": "Research"}, {})
    running = repo.claim(auth, run["id"], "worker")
    with env.db.transaction() as conn:
        first = repo.append_event(conn, auth, run["id"], "owner_message", {"text": "Focus on cost"}, "message-1")
        replay = repo.append_event(conn, auth, run["id"], "owner_message", {"text": "Focus on cost"}, "message-1")
        assert first["id"] == replay["id"]
        with pytest.raises(AiclError):
            repo.append_event(conn, auth, run["id"], "owner_message", {"text": "Changed"}, "message-1")
        assert repo.owned_run(conn, auth, run["id"])["version"] == running["version"]
        paused = repo.save_checkpoint(conn, auth, running, {}, {"status": "paused", "owner_cursor": first["sequence"]})
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE agent_content SET payload_json='{}' WHERE id=?", (first["payload_ref"],))
    released = repo.release(auth, run["id"], "worker", running["fence"])
    assert released["status"] == "paused" and released["version"] == paused["version"]
    with env.db.reader() as conn:
        events = repo.events(conn, auth, run["id"])
        assert len(events) == 1 and events[0]["payload"] == {"text": "Focus on cost"}
        assert repo.events(conn, auth, run["id"], after=first["sequence"]) == []
        assert not repo.steps(conn, auth, run["id"])
        assert conn.execute("SELECT 1 FROM agent_wakeup WHERE run_id=?", (run["id"],)).fetchone() is None
    with pytest.raises(AiclError):
        repo.claim(auth, run["id"], "worker")
