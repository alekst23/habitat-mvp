"""Owner task journey: a bounded brief, one current run, and visible setup blockers."""

import json
import shutil

import pytest

from aicl.control.errors import AiclError
from aicl.control.instances import GateContext, Limits
from support import historical_budget_fixture
from test_mock_commerce import commerce, ready


BRIEF = {
    "product_name": "Orchard Notes",
    "audience": "Independent orchard growers",
    "goal": "Invite growers to try the harvest planning checklist",
}


def test_task_brief_survives_restart_drives_output_and_binds_idempotency(build_env):
    env, service, auth, inst, _ = ready(build_env)
    before = service.dashboard(auth, inst.id)
    assert not before["brief_saved"]
    saved = service.save_brief(auth, inst.id, {key: f" {value} " for key, value in BRIEF.items()}, before["policy"]["version"])
    assert saved["draft_brief"] == BRIEF and saved["version"] == before["policy"]["version"] + 1
    assert commerce(env).dashboard(auth, inst.id)["draft_brief"] == BRIEF
    assert service.dashboard(auth, inst.id)["brief_saved"]
    assert service.dashboard(auth, inst.id)["balance_micro_usd"] == before["balance_micro_usd"]
    with pytest.raises(AiclError) as stale:
        service.save_brief(auth, inst.id, BRIEF, before["policy"]["version"])
    assert stale.value.error == "conflict"
    run = service.start_run(auth, inst.id, "custom-brief", brief=BRIEF)
    assert run["brief"] == BRIEF and run["scenario"] == "marketing_launch_kit"
    with env.db.reader() as conn:
        assert json.loads(conn.execute("SELECT brief_json FROM mock_commerce_run WHERE id = ?", (run["id"],)).fetchone()[0]) == BRIEF
    restarted = commerce(env)
    assert restarted.start_run(auth, inst.id, "custom-brief", brief=BRIEF) == run
    before = restarted.dashboard(auth, inst.id)
    with pytest.raises(AiclError) as changed:
        restarted.start_run(auth, inst.id, "custom-brief", brief={**BRIEF, "product_name": "Other product"})
    assert changed.value.error == "conflict"
    assert restarted.dashboard(auth, inst.id)["balance_micro_usd"] == before["balance_micro_usd"]
    restarted.save_brief(auth, inst.id, {**BRIEF, "product_name": "Future product"}, before["policy"]["version"])
    assert restarted.run(auth, run["id"])["brief"] == BRIEF
    purchase = run["purchase"]
    approved = restarted.decide_purchase(auth, purchase["id"], "approve", purchase["quote_digest"])
    restarted.checkout(auth, approved["order_id"], "complete")
    completed = restarted.resume_run(auth, run["id"])
    assert completed["brief"] == BRIEF
    assert all(value in completed["output"] for value in BRIEF.values())
    assert "Purchased template:" in completed["output"]
    assert completed["purchase"]["fulfillment"]["content"] in completed["output"]


def test_one_current_task_blocks_duplicate_work_but_keeps_retry_and_history(build_env):
    env, service, auth, inst, _ = ready(build_env, limit_minor=1000)
    run = service.start_run(auth, inst.id, "first", brief=BRIEF)
    purchase = run["purchase"]
    before = service.dashboard(auth, inst.id)
    assert before["current_run"]["id"] == run["id"]
    assert before["history_runs"] == []
    assert before["active_run_count"] == before["attention_count"] == 1
    for state in ("awaiting_approval", "awaiting_checkout", "payment_pending", "ready_to_resume"):
        if state == "awaiting_checkout":
            purchase = service.decide_purchase(auth, purchase["id"], "approve", purchase["quote_digest"])
        elif state == "payment_pending":
            service.checkout(auth, purchase["order_id"], "pending")
        elif state == "ready_to_resume":
            service.checkout(auth, purchase["order_id"], "complete")
        with pytest.raises(AiclError) as blocked:
            service.start_run(auth, inst.id, "second", brief=BRIEF)
        assert blocked.value.error == "denied" and blocked.value.extra["reason"] == "task_in_progress"
        assert service.start_run(auth, inst.id, "first", brief=BRIEF)["state"] == state
        assert service.dashboard(auth, inst.id)["balance_micro_usd"] == before["balance_micro_usd"]
    service.resume_run(auth, run["id"])
    completed = service.dashboard(auth, inst.id)
    assert completed["current_run"]["id"] == run["id"]
    assert completed["active_run_count"] == completed["attention_count"] == 0
    second = service.start_run(auth, inst.id, "second", brief={**BRIEF, "product_name": "Next product"})
    dashboard = service.dashboard(auth, inst.id)
    assert dashboard["current_run"]["id"] == second["id"]
    assert [item["id"] for item in dashboard["history_runs"]] == [run["id"]]


def test_readiness_reports_all_setup_controls_in_one_response(build_env):
    env = build_env()
    auth, inst = env.new_instance(limits=Limits(0, 0, 0, 0))
    with env.db.transaction() as conn:
        env.instances.set_gated(conn, auth, inst.id, "network_denied", GateContext(host_hash12="a" * 12))
    readiness = commerce(env).dashboard(auth, inst.id)["readiness"]
    assert not readiness["ready"]
    assert {blocker["reason"] for blocker in readiness["blockers"]} == {
        "instance_not_active", "capability_disabled", "gate_unresolved", "credit_insufficient",
        "budget_exhausted", "purchases_disabled", "purchase_limit_exceeded",
    }


def test_current_readiness_uses_held_or_paid_purchase_without_second_allowance(build_env):
    env, service, auth, inst, ops = ready(build_env, limit_minor=100)
    run = service.start_run(auth, inst.id, "exact-allowance", brief=BRIEF)
    purchase = run["purchase"]
    for state in ("awaiting_approval", "awaiting_checkout", "payment_pending", "ready_to_resume"):
        if state == "awaiting_checkout":
            purchase = service.decide_purchase(auth, purchase["id"], "approve", purchase["quote_digest"])
        elif state == "payment_pending":
            service.checkout(auth, purchase["order_id"], "pending")
        elif state == "ready_to_resume":
            service.checkout(auth, purchase["order_id"], "complete")
        dashboard = service.dashboard(auth, inst.id)
        assert dashboard["current_run"]["state"] == state
        assert dashboard["current_readiness"] == {"ready": True, "blockers": []}
        assert not dashboard["readiness"]["ready"]
        assert "purchase_limit_exceeded" in {item["reason"] for item in dashboard["readiness"]["blockers"]}
    service.configure(auth, inst.id, False, 100, dashboard["policy"]["version"])
    assert service.dashboard(auth, inst.id)["current_readiness"]["ready"]
    ops.set_capability(auth, inst.id, env.instances.get(auth, inst.id).version, "inference", False)
    blocked = service.dashboard(auth, inst.id)["current_readiness"]
    assert not blocked["ready"]
    assert {item["reason"] for item in blocked["blockers"]} == {"capability_disabled"}


def test_invalid_brief_is_rejected_without_charging_or_creating_work(build_env):
    env, service, auth, inst, _ = ready(build_env)
    invalid = [None, "", " " * 4, 12]
    for field, limit in (("product_name", 120), ("audience", 240), ("goal", 600)):
        for value in invalid + ["x" * (limit + 1)]:
            with pytest.raises(AiclError) as rejected:
                service.start_run(auth, inst.id, "invalid", brief={**BRIEF, field: value})
            assert rejected.value.error == "validation_failed"
    for value in ({}, {**BRIEF, "scenario": "arbitrary_program"}, [], "do something"):
        with pytest.raises(AiclError) as rejected:
            service.start_run(auth, inst.id, "invalid", brief=value)
        assert rejected.value.error == "validation_failed"
    dashboard = service.dashboard(auth, inst.id)
    assert dashboard["balance_micro_usd"] == 5_000_000 and dashboard["runs"] == []


def test_forward_migration_preserves_funding_and_surfaces_older_active_task(build_env, tmp_path, monkeypatch):
    import aicl.db as database
    from aicl.commerce.adapters import DEFAULT_TASK_BRIEF

    legacy = tmp_path / "legacy-migrations"
    legacy.mkdir()
    for path in database.MIGRATIONS_DIR.glob("*.sql"):
        if path.stem < "0010":
            shutil.copyfile(path, legacy / path.name)
    with monkeypatch.context() as patch:
        patch.setattr(database, "MIGRATIONS_DIR", legacy)
        with historical_budget_fixture(build_env) as historical_build:
            env, service, auth, inst, _ = ready(historical_build, funded=False)
    with env.db.transaction() as conn:
        # Seed the historical schema directly: the current service requires its
        # current migrations and must not operate against a pre-upgrade database.
        now = database.to_iso(env.clock.now())
        conn.execute("INSERT INTO mock_commerce_order (id,instance_id,tenant_id,owner_id,purpose,request_id,"
                     "amount_minor,currency,merchant_id,merchant_name,state,created_at,updated_at) "
                     "VALUES ('legacy-order',?,?,?,'service_topup','legacy-topup',500,'USD','habitat-demo','Habitat Demo','completed',?,?)",
                     (inst.id, auth.tenant_id, auth.owner_id, now, now))
        conn.execute("INSERT INTO mock_commerce_receipt (id,order_id,instance_id,purpose,capture_id,merchant_id,merchant_name,amount_minor,currency,created_at) "
                     "VALUES ('legacy-receipt','legacy-order',?,'service_topup','LOCAL-CAPTURE-legacy','habitat-demo','Habitat Demo',500,'USD',?)",
                     (inst.id, now))
        conn.execute("INSERT INTO mock_commerce_ledger (id,instance_id,kind,delta_micro_usd,reference,receipt_id,created_at) "
                     "VALUES ('legacy-ledger',?,'service_topup',5000000,'topup:legacy-order','legacy-receipt',?)", (inst.id, now))
        for run_id, state in (("older-active", "awaiting_approval"), ("newer-completed", "completed")):
            conn.execute("INSERT INTO mock_commerce_run (id,instance_id,tenant_id,owner_id,request_id,state,created_at,updated_at) "
                         "VALUES (?,?,?,?,?,?,?,?)", (run_id, inst.id, auth.tenant_id, auth.owner_id, run_id, state,
                                                       database.to_iso(env.clock.now()), database.to_iso(env.clock.now())))
    env.db.migrate()
    env.db.migrate()  # Repeat startup cannot reset existing records or reapply ALTER TABLE.
    dashboard = commerce(env).dashboard(auth, inst.id)
    assert dashboard["balance_micro_usd"] == 5_000_000 and len(dashboard["receipts"]) == 1
    assert dashboard["current_run"]["id"] == "older-active"
    assert dashboard["current_run"]["brief"] == DEFAULT_TASK_BRIEF
    assert [run["id"] for run in dashboard["history_runs"]] == ["newer-completed"]
    assert dashboard["active_run_count"] == dashboard["attention_count"] == 1
    assert dashboard["draft_brief"] == DEFAULT_TASK_BRIEF and not dashboard["brief_saved"]
    assert dashboard["payment_profile"] is None
    assert dashboard["orders"][0]["buyer_id"] is None and not dashboard["orders"][0]["buyer_required"]
