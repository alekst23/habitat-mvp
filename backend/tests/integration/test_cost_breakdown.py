"""Cost views reconcile to canonical receipts without inventing allocations."""
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

from aicl.control.budget import Estimate, MeasuredUsage
from aicl.studio.data import StudioData
from aicl.workflow.cost_projection import cost_jobs, cost_line, cost_summary
from aicl.workflow.routes import _audit_filter
from aicl.workflow.service import MockWorkflowService
from test_runtime_agent_research import agent_setup
from test_runtime_research_prelude import setup as research_setup


def test_job_rollup_reconciles_model_bundled_tools_and_compute_without_repricing(build_env):
    env, auth, inst, runtime, model, _, run, _, _, _ = agent_setup(build_env)
    model.estimate = Estimate(100, 100, 1)
    decide = model.decide
    model.decide = lambda *args: replace(decide(*args), usage=MeasuredUsage(20, 10, 1))
    assert runtime.advance_slice(auth, run["id"])["status"] == "waiting_owner"
    with env.db.reader() as conn:
        recorded = conn.execute("SELECT SUM(inference_micro_usd),SUM(compute_micro_usd) FROM budget_usage").fetchone()
        before = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("budget_usage", "budget_hold", "agent_step", "audit_event")}
    workflow = MockWorkflowService(env.db, env.clock)
    overview = workflow.overview(auth, inst.id)
    studio = StudioData(SimpleNamespace(db=env.db, clock=env.clock)).snapshot(auth, instance_id=inst.id)
    job = workflow.job(auth, "runtime:" + run["id"])
    summary = overview["cost_summary"]
    assert summary == studio["cost_summary"] == job["cost_summary"]
    assert (summary["settled_micro_usd"], summary["estimated_micro_usd"], summary["held_micro_usd"]) == (*recorded, 0)
    assert summary["total_micro_usd"] == sum(recorded) == 11250
    bundled, = [row for row in overview["cost_rows"] if row["component"] == "model_and_tools"]
    assert bundled["amount_micro_usd"] == 6200
    assert bundled["web_search_calls"] == 1 and bundled["input_tokens"] == 300
    assert bundled["pricing"] == "combined" and "individual prices were not recorded" in bundled["coverage_note"]
    assert bundled["hold_id"] and bundled["step_id"] and bundled["price_table_version"]
    assert bundled["evidence_url"].endswith("#step-" + bundled["step_id"])
    assert {row["component"] for row in job["cost_rows"]} == {"model", "model_and_tools", "compute"}
    assert summary["settled_micro_usd"] == sum(row["amount_micro_usd"] for row in job["cost_rows"] if row["charge_kind"] == "usage")
    rollup, = overview["cost_jobs"]
    assert rollup["job_id"] == job["id"] and rollup["line_count"] == 3
    assert rollup["evidence_url"].endswith("#cost-breakdown")
    assert rollup["settled_usd"] == .00625 and rollup["estimated_usd"] == .005
    storage, = [row for row in summary["components"] if row["component"] == "storage"]
    tools, = [row for row in summary["components"] if row["component"] == "tools"]
    assert storage["amount_micro_usd"] is None and storage["coverage"] == "not_metered"
    assert tools["amount_micro_usd"] is None and tools["coverage"] == "bundled"
    assert sum(row["amount_micro_usd"] or 0 for row in summary["components"]) == 11250
    with env.db.reader() as conn:
        assert before == {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in before}


def test_search_only_receipt_is_a_tool_charge_and_period_rollup_keeps_older_job_name(build_env):
    env, auth, inst, runtime, _, _, run, _, _, _ = research_setup(build_env)
    env.clock.advance(timedelta(days=1))
    runtime.advance_slice(auth, run["id"])
    overview = MockWorkflowService(env.db, env.clock).overview(auth, inst.id)
    search, = [row for row in overview["cost_rows"] if row["component"] == "tools"]
    assert search["amount_micro_usd"] == 5000 and search["pricing"] == "recorded"
    assert search["input_tokens"] == search["output_tokens"] == 0
    day = env.clock.now().date().isoformat()
    filtered, *_ = _audit_filter(overview, "costs", "", day, day)
    assert filtered["runs"] == []
    rollup, = filtered["cost_jobs"]
    assert rollup["job_name"] == overview["runs"][0]["deliverable_name"]
    assert rollup["settled_usd"] == .005
    assert filtered["cost_summary"]["settled_micro_usd"] == 5000
    assert filtered["cost_summary"]["estimated_micro_usd"] == 0
    earlier = (env.clock.now() - timedelta(days=2)).date().isoformat()
    empty, *_ = _audit_filter(overview, "costs", "", earlier, earlier)
    assert empty["cost_jobs"] == [] and empty["cost_summary"]["total_micro_usd"] == 0


def test_holds_funding_waivers_and_merchant_payments_do_not_inflate_resource_spend():
    rows = [{"category": category, "amount_micro_usd": amount, "amount_usd": amount / 1_000_000}
            for category, amount in (("Inference reservation", 400), ("Service funding", 5_000_000),
                                     ("Setup waived", 600), ("Merchant purchase", 100_000))]
    summary = cost_summary(rows)
    assert summary["settled_micro_usd"] == summary["estimated_micro_usd"] == summary["total_micro_usd"] == 0
    assert summary["held_micro_usd"] == 400 and summary["merchant_micro_usd"] == 100_000
    assert all(component["amount_micro_usd"] is None for component in summary["components"])


def test_explicit_recorded_components_remain_idempotent_and_unknown_costs_are_not_models():
    for category, component in (("Storage access", "storage"), ("Tool execution", "tools"), ("Unclassified fee", "other")):
        row = cost_line({"category": category, "amount_micro_usd": 7})
        assert row["component"] == component and cost_line(row) == row
    compute = cost_line({"category": "Provider charge", "component": "compute", "charge_kind": "usage", "amount_micro_usd": 11})
    assert compute["charge_kind"] == "usage" and compute["pricing"] == "recorded"
    assert cost_summary([compute])["settled_micro_usd"] == 11
    assert cost_summary([compute])["estimated_micro_usd"] == 0


def test_legacy_job_rollup_retains_original_and_replacement_purchase_ancestry(build_env):
    from aicl.db import from_iso
    from test_scheduled_owner_workflow import prepared, spec, tick, approved

    env, workflow, payments, auth, inst, _ = prepared(build_env, spec(purchase=True))
    first, _ = tick(workflow, auth, inst.id)
    original, = first["purchases"]
    job_id = first["runs"][0]["id"]
    env.clock.set(from_iso(original["expires_at"]) + timedelta(seconds=1))
    fresh = workflow.refresh_purchase(auth, original["id"])
    order_id = approved(workflow, payments, auth, fresh["id"], "now")["order_id"]
    payments.checkout(auth, order_id, "complete")
    workflow.payment_completed(auth, order_id)
    overview = workflow.overview(auth, inst.id)
    job = workflow.job(auth, job_id)
    assert job["cost_summary"] == overview["runs"][0]["cost_summary"] == overview["cost_summary"]
    model_lines = [row for row in job["cost_rows"] if row["component"] == "model"]
    assert len(model_lines) == 2 and all(row["job_id"] == job_id for row in model_lines)
    assert job["cost_summary"]["settled_micro_usd"] == job["inference_cost_micro_usd"]
    assert job["cost_summary"]["merchant_micro_usd"] == 1_000_000
    assert job["cost_summary"]["total_micro_usd"] == job["inference_cost_micro_usd"]


def test_job_labels_prefer_saved_output_and_never_repeat_full_supplied_context():
    line = {"category": "Inference usage", "amount_micro_usd": 100, "job_id": "runtime:12345678-abc", "agent_name": "Digest"}
    objective = "Summarize today's AI news\nSupplied context: private brief that belongs in the source job"
    job = {"id": line["job_id"], "deliverable_name": objective, "latest_deliverable": {"name": "Daily AI digest"}}
    assert cost_jobs([line], [job])[0]["job_name"] == "Daily AI digest"
    job["latest_deliverable"] = None
    assert cost_jobs([line], [job])[0]["job_name"] == "Summarize today's AI news"
    job["deliverable_name"] = "A" * 200 + "\nSupplied context"
    title = cost_jobs([line], [job])[0]["job_name"]
    assert len(title) <= 120 and title.endswith("…") and "Supplied context" not in title
