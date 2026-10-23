"""Remembered mock buyers are owner preferences, never reusable payment consent."""
from dataclasses import replace
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
import uuid

import pytest

from aicl.commerce.service import MockCommerceService
from aicl.control.errors import AiclError
from test_mock_commerce import ready
from test_payment_workflow import PaymentPort


def service_with_port(build_env):
    env, _, auth, inst, _ = ready(build_env, funded=False)
    port = PaymentPort(env.db)
    return env, MockCommerceService(env.db, env.clock, payments=port), port, auth, inst


def test_first_checkout_requires_explicit_buyer_but_cancel_does_not(build_env):
    env, service, port, auth, inst = service_with_port(build_env)
    assert service.payment_profile(auth) is None
    order = service.create_topup(auth, inst.id, 500, "first-buyer")
    assert order["buyer_required"] and order["buyer_can_change"] and order["buyer_id"] is None
    for outcome in ("pending", "complete"):
        with pytest.raises(AiclError) as missing:
            service.checkout(auth, order["id"], outcome)
        assert missing.value.extra["reason"] == "buyer_required"
    assert port.calls == [] and service.dashboard(auth, inst.id)["balance_micro_usd"] == 0
    assert service.checkout(auth, order["id"], "cancel")["state"] == "cancelled"
    assert service.payment_profile(auth) is None


def test_preference_reused_across_agents_and_restart_without_approving_payments(build_env):
    env, service, port, auth, inst = service_with_port(build_env)
    order = service.create_topup(auth, inst.id, 500, "choose-buyer")
    selected = service.select_payment_buyer(auth, order["id"], "demo-buyer")
    assert selected["buyer_label"] == "Demo buyer" and selected["state"] == "created"
    assert port.calls == []
    with env.db.transaction() as conn:
        second = env.instances.insert_draft(conn, auth, replace(inst, id=str(uuid.uuid4()), lifecycle="draft"), ())
    restarted = MockCommerceService(env.db, env.clock, payments=port)
    second_order = restarted.create_topup(auth, second.id, 500, "another-agent")
    assert second_order["buyer_id"] == "demo-buyer" and second_order["state"] == "created"
    assert restarted.dashboard(auth, second.id)["payment_profile"] == {
        "buyer_id": "demo-buyer", "buyer_label": "Demo buyer"}
    assert restarted.dashboard(auth, second.id)["balance_micro_usd"] == 0
    assert port.calls == []


def test_buyer_selection_is_scoped_and_accepts_only_fixed_demo_identities(build_env):
    env, service, port, auth, inst = service_with_port(build_env)
    order = service.create_topup(auth, inst.id, 500, "scoped-buyer")
    stranger, other = env.new_instance()
    with pytest.raises(AiclError) as owned:
        service.select_payment_buyer(stranger, order["id"], "demo-buyer-alt")
    assert owned.value.error == "not_found"
    for buyer in ("owner@example.com", "", None, [], "demo-buyer\n"):
        with pytest.raises(AiclError) as invalid:
            service.select_payment_buyer(auth, order["id"], buyer)
        assert invalid.value.error == "validation_failed"
    service.select_payment_buyer(auth, order["id"], "demo-buyer")
    assert service.payment_profile(stranger) is None
    assert service.create_topup(stranger, other.id, 500, "other-owner")["buyer_id"] is None
    with pytest.raises(AiclError) as expired:
        service.payment_profile(replace(auth, expires_at=env.clock.now() - timedelta(seconds=1)))
    assert expired.value.error == "unauthenticated"
    assert port.calls == []


def test_pending_order_keeps_buyer_when_owner_changes_preference_and_capture_verifies_it(build_env):
    env, service, port, auth, inst = service_with_port(build_env)
    first = service.create_topup(auth, inst.id, 500, "first-bound")
    service.select_payment_buyer(auth, first["id"], "demo-buyer")
    assert service.checkout(auth, first["id"], "pending")["buyer_can_change"] is False
    second = service.create_topup(auth, inst.id, 500, "second-bound")
    service.select_payment_buyer(auth, second["id"], "demo-buyer-alt")
    assert service.payment_profile(auth)["buyer_id"] == "demo-buyer-alt"
    assert service.order(auth, first["id"])["buyer_id"] == "demo-buyer"
    with pytest.raises(AiclError) as immutable:
        service.select_payment_buyer(auth, first["id"], "demo-buyer-alt")
    assert immutable.value.error == "invalid_transition"
    service.select_payment_buyer(auth, first["id"], "demo-buyer")
    assert service.payment_profile(auth)["buyer_id"] == "demo-buyer-alt"
    port.mismatch = {"buyer_id": "demo-buyer-alt"}
    with pytest.raises(AiclError) as mismatch:
        service.checkout(auth, first["id"], "complete")
    assert mismatch.value.error == "provider_mismatch"
    assert service.dashboard(auth, inst.id)["balance_micro_usd"] == 0
    assert not service.order(auth, first["id"])["buyer_can_change"]
    port.mismatch = None
    assert service.reconcile_payment(auth, first["id"])["state"] == "completed"
    assert service.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000
    assert service.order(auth, first["id"])["buyer_id"] == "demo-buyer"


def test_legacy_unknown_order_recovers_with_unchanged_buyerless_binding(build_env):
    env, service, port, auth, inst = service_with_port(build_env)
    legacy = service.create_topup(auth, inst.id, 500, "legacy-buyerless")
    with env.db.transaction() as conn:
        conn.execute("UPDATE mock_commerce_order SET buyer_required = 0 WHERE id = ?", (legacy["id"],))
    port.lose_response = True
    with pytest.raises(AiclError):
        service.checkout(auth, legacy["id"], "complete")
    with env.db.reader() as conn:
        original_binding = conn.execute("SELECT payment_binding_json FROM mock_commerce_order WHERE id = ?", (legacy["id"],)).fetchone()[0]
    assert "buyer_id" not in json.loads(original_binding)
    new = service.create_topup(auth, inst.id, 500, "new-preference")
    service.select_payment_buyer(auth, new["id"], "demo-buyer")
    restarted = MockCommerceService(env.db, env.clock, payments=port)
    paid = restarted.reconcile_payment(auth, legacy["id"])
    assert paid["state"] == "completed" and paid["buyer_id"] is None
    with env.db.reader() as conn:
        assert conn.execute("SELECT payment_binding_json FROM mock_commerce_order WHERE id = ?", (legacy["id"],)).fetchone()[0] == original_binding
    assert restarted.checkout(auth, legacy["id"], "complete") == paid
    assert restarted.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000


@pytest.mark.parametrize("remote", [False, True])
def test_stale_buyer_on_confirmation_cannot_pay_using_newly_selected_account(build_env, remote):
    env, service, port, auth, inst = service_with_port(build_env)
    if not remote:
        service = MockCommerceService(env.db, env.clock)
    order = service.create_topup(auth, inst.id, 500, "stale-buyer")
    service.select_payment_buyer(auth, order["id"], "demo-buyer")
    service.select_payment_buyer(auth, order["id"], "demo-buyer-alt")
    with pytest.raises(AiclError) as changed:
        service.checkout(auth, order["id"], "complete", expected_buyer_id="demo-buyer")
    assert changed.value.extra["reason"] == "buyer_changed"
    assert port.calls == []
    assert service.order(auth, order["id"])["state"] == "created"
    assert service.dashboard(auth, inst.id)["balance_micro_usd"] == 0
    paid = service.checkout(auth, order["id"], "complete", expected_buyer_id="demo-buyer-alt")
    assert paid["state"] == "completed" and paid["buyer_id"] == "demo-buyer-alt"


def test_concurrent_first_buyer_selection_cannot_overwrite_winning_choice(build_env):
    env, service, port, auth, inst = service_with_port(build_env)
    order = service.create_topup(auth, inst.id, 500, "concurrent-first-buyer")
    barrier = Barrier(2)

    def choose(buyer_id):
        barrier.wait(timeout=5)
        try:
            return service.select_payment_buyer(auth, order["id"], buyer_id, expected_current_buyer_id=None)
        except AiclError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(choose, ("demo-buyer", "demo-buyer-alt")))
    chosen = [result for result in results if isinstance(result, dict)]
    refused = [result for result in results if isinstance(result, AiclError)]
    assert len(chosen) == len(refused) == 1
    assert refused[0].extra["reason"] == "buyer_changed"
    winner = chosen[0]["buyer_id"]
    assert service.order(auth, order["id"])["buyer_id"] == winner
    assert service.payment_profile(auth)["buyer_id"] == winner
    assert port.calls == []


def test_stale_explicit_buyer_change_preserves_order_and_owner_preference(build_env):
    env, service, port, auth, inst = service_with_port(build_env)
    order = service.create_topup(auth, inst.id, 500, "stale-account-change")
    service.select_payment_buyer(auth, order["id"], "demo-buyer", expected_current_buyer_id=None)
    service.select_payment_buyer(auth, order["id"], "demo-buyer-alt", expected_current_buyer_id="demo-buyer")
    with pytest.raises(AiclError) as changed:
        service.select_payment_buyer(auth, order["id"], "demo-buyer", expected_current_buyer_id="demo-buyer")
    assert changed.value.extra["reason"] == "buyer_changed"
    assert service.order(auth, order["id"])["buyer_id"] == "demo-buyer-alt"
    assert service.payment_profile(auth)["buyer_id"] == "demo-buyer-alt"
    assert port.calls == []
