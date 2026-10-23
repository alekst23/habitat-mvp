"""Local commerce proofs: real SQLite, ownership and controls; no payment/model network calls."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from urllib.parse import urlsplit

import pytest

import seams
from aicl.control.errors import AiclError
from aicl.control.instances import GateContext, Limits
from aicl.db import from_iso


def commerce(env):
    from aicl.commerce.service import MockCommerceService
    return MockCommerceService(env.db, env.clock)


def ready(build_env, *, funded=True, enabled=True, limit_minor=200):
    env = build_env()
    auth, inst = env.new_instance(capabilities=("inference",))
    ops = seams.instance_operations(env)
    ops.set_lifecycle(auth, inst.id, inst.version, "activate")
    service = commerce(env)
    if enabled:
        service.configure(auth, inst.id, True, limit_minor, 1)
    if funded:
        order = service.create_topup(auth, inst.id, 500, "topup-initial")
        service.select_payment_buyer(auth, order["id"], "demo-buyer")
        service.checkout(auth, order["id"], "complete")
    return env, service, auth, inst, ops


def denied(reason, operation):
    with pytest.raises(AiclError) as caught:
        operation()
    assert caught.value.error == "denied"
    assert caught.value.extra["reason"] == reason


def error(code, operation):
    with pytest.raises(AiclError) as caught:
        operation()
    assert caught.value.error == code


def approved_purchase(service, auth, instance_id, request_id="purchase-1"):
    run = service.start_run(auth, instance_id, request_id)
    purchase = run["purchase"]
    approved = service.decide_purchase(auth, purchase["id"], "approve", purchase["quote_digest"])
    return run, approved, service.order(auth, approved["order_id"])


def test_mock_topup_purchase_and_resume_preserve_separate_money_and_survive_restart(build_env):
    env, service, auth, inst, _ = ready(build_env)
    before = service.dashboard(auth, inst.id)
    assert before["mode"] == "local_simulation"
    assert before["balance_micro_usd"] == 5_000_000
    assert before["policy"]["available_minor"] == 200

    run = service.start_run(auth, inst.id, "launch-kit-1")
    purchase = run["purchase"]
    assert run["state"] == "awaiting_approval" and run["output"] is None
    assert 0 < run["inference_cost_micro_usd"] < 50_000
    assert purchase["quote"]["amount_minor"] == 100
    assert purchase["quote"]["currency"] == "USD"
    assert service.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000 - run["inference_cost_micro_usd"]
    approved = service.decide_purchase(auth, purchase["id"], "approve", purchase["quote_digest"])
    assert approved["state"] == "awaiting_checkout"
    order = service.order(auth, approved["order_id"])
    assert order["purpose"] == "agent_purchase" and order["amount_minor"] == 100
    assert order["merchant_id"] != before["orders"][0]["merchant_id"]

    paid = service.checkout(auth, order["id"], "complete")
    assert paid["state"] == "completed" and paid["capture_id"]
    assert service.checkout(auth, order["id"], "complete") == paid
    after_purchase = service.dashboard(auth, inst.id)
    assert after_purchase["balance_micro_usd"] == 5_000_000 - run["inference_cost_micro_usd"]
    assert after_purchase["policy"]["spent_minor"] == 100
    assert after_purchase["policy"]["held_minor"] == 0
    fulfillment = service.purchase(auth, purchase["id"])["fulfillment"]
    assert fulfillment

    restarted = commerce(env)
    assert restarted.run(auth, run["id"])["state"] == "ready_to_resume"
    completed = restarted.resume_run(auth, run["id"])
    assert completed["state"] == "completed" and completed["output"]
    assert fulfillment["content"] in completed["output"] and fulfillment["name"] in completed["output"]
    assert run["inference_cost_micro_usd"] < completed["inference_cost_micro_usd"] < 100_000
    final = restarted.dashboard(auth, inst.id)
    assert final["balance_micro_usd"] == 5_000_000 - completed["inference_cost_micro_usd"]
    assert len(final["receipts"]) == 2
    assert {receipt["purpose"] for receipt in final["receipts"]} == {"service_topup", "agent_purchase"}
    assert restarted.resume_run(auth, run["id"]) == completed
    assert restarted.start_run(auth, inst.id, "launch-kit-1")["id"] == run["id"]
    assert restarted.dashboard(auth, inst.id)["balance_micro_usd"] == final["balance_micro_usd"]
    budget = env.budget.read_budget(inst.id)
    assert budget.windows["inference"]["day"].settled == completed["inference_cost_micro_usd"]
    assert budget.windows["inference"]["day"].held == 0
    assert budget.windows["compute"]["day"].settled == 0


def test_funding_requires_completed_payment_and_replay_cannot_change_amount_or_double_credit(build_env):
    env, service, auth, inst, _ = ready(build_env, funded=False)
    created = service.create_topup(auth, inst.id, 500, "fund-once")
    assert service.create_topup(auth, inst.id, 500, "fund-once") == created
    error("conflict", lambda: service.create_topup(auth, inst.id, 1000, "fund-once"))
    service.select_payment_buyer(auth, created["id"], "demo-buyer")
    assert service.checkout(auth, created["id"], "pending")["state"] == "pending"
    assert service.dashboard(auth, inst.id)["balance_micro_usd"] == 0
    denied("credit_insufficient", lambda: service.start_run(auth, inst.id, "no-funds"))
    complete = service.checkout(auth, created["id"], "complete")
    assert complete["state"] == "completed"
    assert commerce(env).checkout(auth, created["id"], "complete") == complete
    dashboard = service.dashboard(auth, inst.id)
    assert dashboard["balance_micro_usd"] == 5_000_000
    assert len(dashboard["orders"]) == len(dashboard["receipts"]) == 1

    cancelled = service.create_topup(auth, inst.id, 1000, "cancel-fund")
    assert service.checkout(auth, cancelled["id"], "cancel")["state"] == "cancelled"
    denied("confirmation_required", lambda: service.checkout(auth, cancelled["id"], "complete"))
    assert service.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000


def test_start_gate_preserves_credit_for_inactive_disabled_unresolved_or_exhausted_controls(build_env):
    env, service, auth, inst, ops = ready(build_env)

    def mutate(method, *args):
        return method(auth, inst.id, env.instances.get(auth, inst.id).version, *args)

    mutate(ops.set_lifecycle, "pause")
    denied("instance_not_active", lambda: service.start_run(auth, inst.id, "gated-run"))
    mutate(ops.set_lifecycle, "resume")
    mutate(ops.set_capability, "inference", False)
    denied("capability_disabled", lambda: service.start_run(auth, inst.id, "gated-run"))
    mutate(ops.set_capability, "inference", True)
    with env.db.transaction() as conn:
        env.instances.set_gated(conn, auth, inst.id, "network_denied", GateContext(host_hash12="a" * 12))
    denied("gate_unresolved", lambda: service.start_run(auth, inst.id, "gated-run"))
    with env.db.transaction() as conn:
        env.instances.clear_gated(conn, auth, inst.id)
    mutate(ops.set_limits, Limits(1, 10_000_000, 1_000_000, 10_000_000))
    denied("budget_exhausted", lambda: service.start_run(auth, inst.id, "gated-run"))
    dashboard = service.dashboard(auth, inst.id)
    assert dashboard["balance_micro_usd"] == 5_000_000 and dashboard["runs"] == []
    assert dashboard["policy"]["held_minor"] == 0
    with env.db.reader() as conn:
        assert conn.execute("SELECT count(*) FROM budget_usage WHERE instance_id = ?", (inst.id,)).fetchone()[0] == 0


def test_approval_binds_exact_quote_expires_and_never_substitutes_for_checkout(build_env):
    env, service, auth, inst, _ = ready(build_env)
    run = service.start_run(auth, inst.id, "exact-approval")
    purchase = run["purchase"]
    denied("confirmation_required", lambda: service.resume_run(auth, run["id"]))
    denied("confirmation_mismatch", lambda: service.decide_purchase(auth, purchase["id"], "approve", "0" * 64))
    assert service.purchase(auth, purchase["id"])["state"] == "awaiting_approval"
    env.clock.set(from_iso(purchase["expires_at"]) + timedelta(seconds=1))
    denied("confirmation_expired", lambda: service.decide_purchase(auth, purchase["id"], "approve", purchase["quote_digest"]))
    expired = commerce(env).purchase(auth, purchase["id"])
    assert expired["state"] == "expired"
    assert service.dashboard(auth, inst.id)["policy"]["held_minor"] == 0

    second, approved, order = approved_purchase(service, auth, inst.id, "requires-checkout")
    denied("confirmation_required", lambda: service.resume_run(auth, second["id"]))
    service.checkout(auth, order["id"], "pending")
    denied("confirmation_required", lambda: service.resume_run(auth, second["id"]))
    assert not service.purchase(auth, approved["id"])["fulfillment"]
    assert service.dashboard(auth, inst.id)["policy"]["held_minor"] == 100


def test_purchase_quota_counts_each_hold_once_and_serializes_competing_runs(build_env):
    env, service, auth, inst, _ = ready(build_env, limit_minor=100)
    barrier = Barrier(2)

    def compete(request_id):
        barrier.wait(timeout=5)
        try:
            return service.start_run(auth, inst.id, request_id)
        except AiclError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(compete, ("concurrent-a", "concurrent-b")))
    winners = [result for result in results if isinstance(result, dict)]
    losers = [result for result in results if isinstance(result, AiclError)]
    assert len(winners) == len(losers) == 1
    assert losers[0].error == "denied" and losers[0].extra["reason"] == "task_in_progress"
    run = winners[0]
    purchase = run["purchase"]
    dashboard = service.dashboard(auth, inst.id)
    assert dashboard["balance_micro_usd"] == 5_000_000 - run["inference_cost_micro_usd"]
    assert dashboard["policy"]["held_minor"] == 100 and dashboard["policy"]["available_minor"] == 0
    # Approval/capture must not add the same proposal's $1 hold a second time.
    approved = service.decide_purchase(auth, purchase["id"], "approve", purchase["quote_digest"])
    service.checkout(auth, approved["order_id"], "complete")
    settled = service.dashboard(auth, inst.id)["policy"]
    assert settled["spent_minor"] == 100 and settled["held_minor"] == 0 and settled["available_minor"] == 0
    denied("task_in_progress", lambda: service.start_run(auth, inst.id, "over-limit"))
    service.resume_run(auth, run["id"])
    denied("purchase_limit_exceeded", lambda: service.start_run(auth, inst.id, "over-limit"))


def test_decline_cancel_and_disabled_policy_never_deliver_or_charge_purchase(build_env):
    env, service, auth, inst, _ = ready(build_env, enabled=False)
    denied("purchases_disabled", lambda: service.start_run(auth, inst.id, "disabled"))
    assert service.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000
    service.configure(auth, inst.id, True, 100, 1)
    run = service.start_run(auth, inst.id, "declined")
    purchase = run["purchase"]
    declined = service.decide_purchase(auth, purchase["id"], "decline", purchase["quote_digest"])
    assert declined["state"] == "declined"
    denied("confirmation_required", lambda: service.decide_purchase(auth, purchase["id"], "approve", purchase["quote_digest"]))
    assert service.dashboard(auth, inst.id)["policy"]["held_minor"] == 0

    _, approved, order = approved_purchase(service, auth, inst.id, "cancelled")
    service.checkout(auth, order["id"], "pending")
    service.checkout(auth, order["id"], "cancel")
    denied("confirmation_required", lambda: service.checkout(auth, order["id"], "complete"))
    dashboard = service.dashboard(auth, inst.id)
    assert dashboard["policy"]["held_minor"] == dashboard["policy"]["spent_minor"] == 0
    assert not service.purchase(auth, approved["id"])["fulfillment"]
    assert all(receipt["purpose"] == "service_topup" for receipt in dashboard["receipts"])


def test_checkout_rechecks_owner_controls_and_resume_rechecks_inference_authority(build_env):
    env, service, auth, inst, ops = ready(build_env)
    run, purchase, order = approved_purchase(service, auth, inst.id)
    policy = service.dashboard(auth, inst.id)["policy"]
    service.configure(auth, inst.id, False, 200, policy["version"])
    denied("confirmation_required", lambda: service.checkout(auth, order["id"], "complete"))
    assert service.order(auth, order["id"])["capture_id"] is None
    assert service.dashboard(auth, inst.id)["policy"]["held_minor"] == 0
    policy = service.dashboard(auth, inst.id)["policy"]
    service.configure(auth, inst.id, True, 200, policy["version"])
    run, purchase, order = approved_purchase(service, auth, inst.id, "after-reenable")
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "pause")
    denied("instance_not_active", lambda: service.checkout(auth, order["id"], "complete"))
    assert service.order(auth, order["id"])["capture_id"] is None
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "resume")
    service.checkout(auth, order["id"], "complete")
    balance = service.dashboard(auth, inst.id)["balance_micro_usd"]
    ops.set_capability(auth, inst.id, env.instances.get(auth, inst.id).version, "inference", False)
    denied("capability_disabled", lambda: service.resume_run(auth, run["id"]))
    assert service.dashboard(auth, inst.id)["balance_micro_usd"] == balance
    assert service.run(auth, run["id"])["state"] == "ready_to_resume"


def test_commerce_objects_are_owner_scoped_and_stale_policy_writes_conflict(build_env):
    env, service, auth, inst, _ = ready(build_env)
    stranger, _ = env.new_instance()
    run, purchase, order = approved_purchase(service, auth, inst.id)
    for operation in (
        lambda: service.dashboard(stranger, inst.id),
        lambda: service.configure(stranger, inst.id, True, 10_000, 2),
        lambda: service.create_topup(stranger, inst.id, 500, "stranger-funding"),
        lambda: service.order(stranger, order["id"]),
        lambda: service.checkout(stranger, order["id"], "complete"),
        lambda: service.start_run(stranger, inst.id, "stranger-run"),
        lambda: service.purchase(stranger, purchase["id"]),
        lambda: service.decide_purchase(stranger, purchase["id"], "approve", purchase["quote_digest"]),
        lambda: service.run(stranger, run["id"]),
        lambda: service.resume_run(stranger, run["id"]),
    ):
        error("not_found", operation)
    error("conflict", lambda: service.configure(auth, inst.id, True, 10_000, 1))
    assert service.dashboard(auth, inst.id)["policy"]["limit_minor"] == 200
    assert service.order(auth, order["id"])["capture_id"] is None


def test_mismatched_or_reused_capture_cannot_post_credit(build_env, monkeypatch):
    env, service, auth, inst, _ = ready(build_env, funded=False)
    first = service.create_topup(auth, inst.id, 500, "verified-receipt")
    service.select_payment_buyer(auth, first["id"], "demo-buyer")
    capture = service.payments.capture
    for changed in ({"amount_minor": 1000}, {"currency": "EUR"},
                    {"merchant_id": "another-merchant"}, {"status": "PENDING"}):
        monkeypatch.setattr(service.payments, "capture", lambda order: {**capture(order), **changed})
        denied("confirmation_mismatch", lambda: service.checkout(auth, first["id"], "complete"))
        dashboard = service.dashboard(auth, inst.id)
        assert dashboard["balance_micro_usd"] == 0 and dashboard["receipts"] == []
        assert service.order(auth, first["id"])["state"] == "created"
    monkeypatch.setattr(service.payments, "capture", capture)
    completed = service.checkout(auth, first["id"], "complete")
    second = service.create_topup(auth, inst.id, 500, "different-order")
    monkeypatch.setattr(service.payments, "capture", lambda order: {
        **capture(order), "capture_id": completed["capture_id"],
    })
    error("conflict", lambda: service.checkout(auth, second["id"], "complete"))
    dashboard = service.dashboard(auth, inst.id)
    assert dashboard["balance_micro_usd"] == 5_000_000 and len(dashboard["receipts"]) == 1
    assert service.order(auth, second["id"])["state"] == "created"


def test_commerce_http_forms_require_owner_session_and_csrf_with_checkout_disclosure(web):
    from fastapi.testclient import TestClient
    from aicl.app import FIXTURE_CSRF_TOKEN
    from aicl.commerce.service import MockCommerceService

    created = web.tool(web.owner_a, "create_instance", {
        "idempotency_key": "wiz_" + "d" * 32, "template_id": "default", "name": "Purchase proof",
        "instructions": "Create a launch kit", "enabled_capabilities": ["inference"],
    })
    assert created.status_code == 200, created.text
    instance_id = created.json()["instance"]["id"]
    base = f"/instances/{instance_id}/commerce"
    canonical = f"/instances/{instance_id}"
    old_page = web.owner_a.get(base, follow_redirects=False)
    assert old_page.status_code == 303 and old_page.headers["location"] == canonical + "#funding"
    page = web.owner_a.get(canonical)
    assert page.status_code == 200 and "Fund with PayPal" in page.text
    for section in ('id="budgets"', 'id="funding"', 'id="setup"'):
        assert section in page.text
    assert f'/instances/{instance_id}/workflow' in page.text and "Total purchase limit (USD)" in page.text
    assert 'Start launch-kit task' not in page.text
    assert web.owner_b.get(base).status_code == 404
    visitor = TestClient(web.app)
    assert visitor.get(base, follow_redirects=False).status_code == 303
    origin = web.app.state.ctx.settings.public_base_url
    forms = (
        (f"{base}/settings", {"enabled": "on", "purchase_limit": "2.00", "expected_version": "1"}),
        (f"{base}/topups", {"amount_minor": "500", "request_id": "http-topup"}),
        (f"{base}/runs", {"request_id": "http-run"}),
        ("/commerce/purchases/unowned/decision", {"decision": "approve", "quote_digest": "0" * 64}),
        ("/commerce/runs/unowned/resume", {}),
        (f"{base}/brief", {"product_name": "Owner brief", "audience": "Preview owners",
                           "goal": "Collect feedback", "expected_version": "1"}),
    )
    for path, data in forms:
        rejected = web.owner_a.post(path, data=data, headers={"origin": origin})
        assert rejected.status_code == 403, rejected.text
    headers = {"origin": origin, "x-csrf-token": FIXTURE_CSRF_TOKEN}
    assert visitor.post(forms[-1][0], data=forms[-1][1], headers=headers).status_code == 401
    assert web.owner_b.post(forms[-1][0], data=forms[-1][1], headers=headers).status_code == 404
    configured = web.owner_a.post(forms[0][0], data=forms[0][1], headers=headers, follow_redirects=False)
    assert configured.status_code == 303, configured.text
    target = urlsplit(configured.headers["location"])
    assert target.path == canonical and target.fragment == "budgets"
    assert web.owner_b.post(forms[1][0], data=forms[1][1], headers=headers).status_code == 404
    started = web.owner_a.post(forms[1][0], data={**forms[1][1], "tenant_id": web.auth_b.tenant_id},
                               headers=headers, follow_redirects=False)
    assert started.status_code == 303, started.text
    order_path = started.headers["location"]
    assert "Demo checkout — no real charges." in web.owner_a.get(order_path).text
    assert web.owner_b.get(order_path).status_code == 404
    assert web.owner_b.post(f"{order_path}/checkout", data={"outcome": "complete"}, headers=headers).status_code == 404
    assert web.owner_a.post(f"{order_path}/checkout", data={"outcome": "complete"},
                            headers={"origin": origin}).status_code == 403
    ctx = web.app.state.ctx
    service = MockCommerceService(ctx.db, ctx.clock)
    assert service.dashboard(web.auth_a, instance_id)["balance_micro_usd"] == 0
    complete = web.owner_a.post(f"{order_path}/checkout",
                                data={"outcome": "complete", "buyer_id": "demo-buyer", "csrf_token": FIXTURE_CSRF_TOKEN},
                                headers={"origin": origin},
                                follow_redirects=False)
    assert complete.status_code == 303, complete.text
    assert service.dashboard(web.auth_a, instance_id)["balance_micro_usd"] == 5_000_000
    receipt = web.owner_a.get(order_path)
    assert f'href="{canonical}#setup"' in receipt.text
    assert f'href="{base}"' not in receipt.text


def test_production_has_no_mock_checkout_or_commerce_routes(base_env):
    from aicl.app import create_app
    from aicl.settings import Settings

    settings = Settings.from_env({**base_env, "AICL_ENVIRONMENT": "production",
                                  "AICL_PUBLIC_BASE_URL": "https://habitat.example"})
    app = create_app(settings)
    assert all(not any(part in getattr(route, "path", "") for part in ("commerce", "workflow", "/audit")) for route in app.routes)
