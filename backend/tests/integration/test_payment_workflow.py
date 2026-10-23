"""Remote payment orchestration proofs with a durable provider double and real SQLite."""
from datetime import timedelta

import pytest

from aicl.commerce.service import MockCommerceService
from aicl.control.errors import AiclError
from aicl.db import from_iso
from test_mock_commerce import approved_purchase, ready


class PaymentPort:
    transport = "http_mock"

    def __init__(self, db):
        self.db, self.orders, self.calls = db, {}, []
        self.lose_response = False
        self.mismatch = None

    def _outside_transaction(self):
        assert getattr(self.db._local, "conn", None) is None

    def execute(self, order, outcome):
        self._outside_transaction()
        self.calls.append((order["id"], outcome))
        result = {key: order[key] for key in ("amount_minor", "currency", "merchant_id", "purpose")}
        if order.get("buyer_id") is not None:
            result["buyer_id"] = order["buyer_id"]
        result.update(reference=order["id"], provider_order_id="MOCK-" + order["id"],
                      status={"complete": "COMPLETED", "pending": "PENDING", "cancel": "CANCELLED"}[outcome])
        if outcome == "complete":
            result["capture_id"] = "CAP-" + order["id"]
        self.orders[order["id"]] = result
        if self.lose_response:
            self.lose_response = False
            raise AiclError("unavailable", "Provider response lost", reason="provider_unavailable")
        return {**result, **(self.mismatch or {})}

    def status(self, order):
        self._outside_transaction()
        self.calls.append((order["id"], "status"))
        return {**self.orders[order["id"]], **(self.mismatch or {})}


def remote(build_env, *, funded=True):
    env, _, auth, inst, ops = ready(build_env, funded=funded)
    port = PaymentPort(env.db)
    return env, MockCommerceService(env.db, env.clock, payments=port), port, auth, inst, ops


def test_capture_response_loss_recovers_after_restart_once_even_when_agent_paused(build_env):
    env, service, port, auth, inst, ops = remote(build_env)
    run, purchase, order = approved_purchase(service, auth, inst.id)
    port.lose_response = True
    with pytest.raises(AiclError):
        service.checkout(auth, order["id"], "complete")
    uncertain = service.order(auth, order["id"])
    assert uncertain["payment_phase"] == "unknown" and uncertain["can_reconcile"]
    assert service.dashboard(auth, inst.id)["policy"]["held_minor"] == 100
    assert "payment_unresolved" in {item["reason"] for item in service.dashboard(auth, inst.id)["readiness"]["blockers"]}
    assert service.purchase(auth, purchase["id"])["fulfillment"] is None
    for mutate in (
        lambda: service.configure(auth, inst.id, False, 0, 2),
        lambda: service.decide_purchase(auth, purchase["id"], "decline", purchase["quote_digest"]),
        lambda: service.checkout(auth, order["id"], "cancel"),
        lambda: service.start_run(auth, inst.id, "cannot-duplicate"),
    ):
        with pytest.raises(AiclError):
            mutate()
    env.clock.set(from_iso(purchase["expires_at"]) + timedelta(seconds=1))
    with pytest.raises(AiclError):
        service.decide_purchase(auth, purchase["id"], "approve", purchase["quote_digest"])
    assert service.dashboard(auth, inst.id)["policy"]["held_minor"] == 100
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "pause")
    restarted = MockCommerceService(env.db, env.clock, payments=port)
    paid = restarted.reconcile_payment(auth, order["id"])
    assert paid["state"] == "completed" and paid["payment_phase"] == "completed"
    assert restarted.reconcile_payment(auth, order["id"]) == paid
    assert MockCommerceService(env.db, env.clock).checkout(auth, order["id"], "complete") == paid
    assert len(port.calls) == 2  # One dispatch and one status check, never a repeat capture.
    dashboard = restarted.dashboard(auth, inst.id)
    assert dashboard["current_run"]["state"] == "ready_to_resume"
    assert dashboard["policy"]["held_minor"] == 0 and dashboard["policy"]["spent_minor"] == 100
    assert len(dashboard["receipts"]) == 2 and len(dashboard["ledger"]) == 2
    with pytest.raises(AiclError) as paused:
        restarted.resume_run(auth, run["id"])
    assert paused.value.extra["reason"] == "instance_not_active"


@pytest.mark.parametrize("mismatch", [
    {"amount_minor": 501}, {"currency": "EUR"}, {"merchant_id": "wrong"},
    {"purpose": "agent_purchase"}, {"reference": "another-order"}, {"provider_order_id": ""},
    {"capture_id": ""},
])
def test_untrusted_capture_cannot_credit_then_valid_reconciliation_posts_once(build_env, mismatch):
    env, service, port, auth, inst, _ = remote(build_env, funded=False)
    order = service.create_topup(auth, inst.id, 500, "topup-http")
    service.select_payment_buyer(auth, order["id"], "demo-buyer")
    port.mismatch = mismatch
    with pytest.raises(AiclError):
        service.checkout(auth, order["id"], "complete")
    assert service.dashboard(auth, inst.id)["balance_micro_usd"] == 0
    assert service.order(auth, order["id"])["payment_phase"] == "unknown"
    port.mismatch = None
    paid = service.reconcile_payment(auth, order["id"])
    assert paid["state"] == "completed"
    assert service.reconcile_payment(auth, order["id"]) == paid
    dashboard = service.dashboard(auth, inst.id)
    assert dashboard["balance_micro_usd"] == 5_000_000 and len(dashboard["receipts"]) == 1


def test_pending_retains_hold_cancel_requires_provider_confirmation_and_owner_scope(build_env):
    env, service, port, auth, inst, _ = remote(build_env)
    run, purchase, order = approved_purchase(service, auth, inst.id)
    pending = service.checkout(auth, order["id"], "pending")
    assert pending["payment_phase"] == "pending" and pending["provider_order_id"]
    with pytest.raises(AiclError):
        service.configure(auth, inst.id, False, 0, 2)
    stranger, _ = env.new_instance()
    with pytest.raises(AiclError) as blocked:
        service.reconcile_payment(stranger, order["id"])
    assert blocked.value.error == "not_found" and len(port.calls) == 1
    port.lose_response = True
    with pytest.raises(AiclError):
        service.checkout(auth, order["id"], "cancel")
    assert service.dashboard(auth, inst.id)["policy"]["held_minor"] == 100
    cancelled = service.reconcile_payment(auth, order["id"])
    assert cancelled["state"] == "cancelled"
    assert service.dashboard(auth, inst.id)["policy"]["held_minor"] == 0
    assert service.run(auth, run["id"])["state"] == "cancelled"


def test_pending_completion_rechecks_policy_and_known_provider_binding(build_env):
    env, service, port, auth, inst, ops = remote(build_env)
    _, _, order = approved_purchase(service, auth, inst.id)
    service.checkout(auth, order["id"], "pending")
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "pause")
    with pytest.raises(AiclError) as paused:
        service.checkout(auth, order["id"], "complete")
    assert paused.value.extra["reason"] == "instance_not_active" and len(port.calls) == 1
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "resume")
    port.mismatch = {"provider_order_id": "SUBSTITUTED"}
    with pytest.raises(AiclError):
        service.checkout(auth, order["id"], "complete")
    assert service.order(auth, order["id"])["payment_phase"] == "unknown"
    assert service.dashboard(auth, inst.id)["policy"]["held_minor"] == 100
    port.mismatch = None
    assert service.reconcile_payment(auth, order["id"])["state"] == "completed"


def test_inflight_claim_is_committed_without_write_lock_and_concurrent_recovery_settles_once(build_env):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    env, service, port, auth, inst, _ = remote(build_env)
    _, purchase, order = approved_purchase(service, auth, inst.id)
    entered, release = Event(), Event()
    execute = port.execute

    def blocked_response(order, outcome):
        result = execute(order, outcome)
        entered.set()
        assert release.wait(5)
        return result

    port.execute = blocked_response
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(service.checkout, auth, order["id"], "complete")
        assert entered.wait(5)
        try:
            assert service.order(auth, order["id"])["payment_phase"] == "inflight"
            for outcome in ("complete", "cancel"):
                with pytest.raises(AiclError) as duplicate:
                    service.checkout(auth, order["id"], outcome)
                assert duplicate.value.extra["reason"] == "reconciliation_pending"
            with pytest.raises(AiclError):
                service.configure(auth, inst.id, False, 0, 2)
            # This separate transaction and reconciliation can finish while the
            # original provider request waits, proving no SQLite write lock is held.
            paid = service.reconcile_payment(auth, order["id"])
            assert paid["state"] == "completed"
        finally:
            release.set()
        assert first.result(timeout=5) == paid
    dashboard = service.dashboard(auth, inst.id)
    assert len(dashboard["receipts"]) == 2 and dashboard["policy"]["spent_minor"] == 100
    assert service.purchase(auth, purchase["id"])["state"] == "paid"
    assert len(port.calls) == 2
