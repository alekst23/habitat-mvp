"""Sandbox orchestration uses durable SQLite claims and a network-free provider double."""
from pathlib import Path
from unittest.mock import patch

import pytest

from aicl.commerce.service import MockCommerceService
from aicl.control.errors import AiclError
from aicl.db import MIGRATIONS_DIR
from test_mock_commerce import approved_purchase, ready


class SandboxPort:
    transport = "paypal_sandbox"

    def __init__(self, db):
        self.db, self.orders, self.calls = db, {}, []
        self.payee = "SANDBOXMERCHANT"
        self.lost = False
        self.mismatch = {}

    def merchant_id_for(self, order):
        return self.payee

    def execute(self, order, outcome):
        assert getattr(self.db._local, "conn", None) is None
        with self.db.reader() as conn:
            persisted = conn.execute("SELECT * FROM mock_commerce_order WHERE id = ?", (order["id"],)).fetchone()
            assert persisted["payment_phase"] == "inflight" and persisted["payment_binding_json"]
        self.calls.append(outcome)
        if outcome == "start":
            result = {key: order[key] for key in ("amount_minor", "currency", "merchant_id", "purpose", "provider_merchant_id")}
            provider_id = "PAYPAL" + order["id"].replace("-", "")
            result.update(reference=order["id"], provider_order_id=provider_id, status="CREATED",
                          approval_url="https://www.sandbox.paypal.com/checkoutnow?token=" + provider_id)
            self.orders.setdefault(order["id"], result)
        else:
            assert outcome == "complete"
            result = self.orders[order["id"]]
            if result["status"] != "APPROVED":
                raise AiclError("invalid_transition", "PayPal buyer approval required")
            result.update(status="COMPLETED", capture_id="CAPTURE" + order["id"])
        if self.lost:
            self.lost = False
            raise TimeoutError("response lost")
        return {**self.orders[order["id"]], **self.mismatch}

    def status(self, order):
        assert getattr(self.db._local, "conn", None) is None
        self.calls.append("status")
        return {**self.orders[order["id"]], **self.mismatch}


def sandbox(build_env, *, funded=False):
    env, inline, auth, inst, ops = ready(build_env, funded=funded)
    port = SandboxPort(env.db)
    return env, MockCommerceService(env.db, env.clock, payments=port), port, auth, inst, ops, inline


def test_sandbox_funding_requires_external_approval_and_capture_and_posts_once(build_env):
    env, service, port, auth, inst, _, _ = sandbox(build_env)
    order = service.create_topup(auth, inst.id, 500, "sandbox-funding")
    assert order["is_paypal_sandbox"] and order["can_begin_paypal"]
    assert not order["buyer_required"] and not order["buyer_can_change"]
    with pytest.raises(AiclError):
        service.select_payment_buyer(auth, order["id"], "demo-buyer")
    with pytest.raises(AiclError):
        service.checkout(auth, order["id"], "complete")
    begun = service.begin_paypal_checkout(auth, order["id"])
    assert begun["approval_url"].startswith("https://www.sandbox.paypal.com/")
    assert begun["can_complete_paypal"] and begun["can_reconcile"]
    assert service.begin_paypal_checkout(auth, order["id"]) == begun
    assert port.calls == ["start"]
    assert service.dashboard(auth, inst.id)["balance_micro_usd"] == 0
    with pytest.raises(AiclError):
        service.complete_paypal_checkout(auth, order["id"], provider_order_id="forged")
    stranger, _ = env.new_instance()
    with pytest.raises(AiclError) as inaccessible:
        service.complete_paypal_checkout(stranger, order["id"], provider_order_id=begun["provider_order_id"])
    assert inaccessible.value.error == "not_found" and port.calls == ["start"]
    # Callback cannot authorize payment: the adapter requires provider approval.
    with pytest.raises(AiclError):
        service.complete_paypal_checkout(auth, order["id"], provider_order_id=begun["provider_order_id"])
    assert service.order(auth, order["id"])["payment_phase"] == "unknown"
    service.reconcile_payment(auth, order["id"])
    port.orders[order["id"]]["status"] = "APPROVED"
    approved = service.reconcile_payment(auth, order["id"])
    assert approved["state"] == "pending"
    assert service.dashboard(auth, inst.id)["balance_micro_usd"] == 0
    paid = service.complete_paypal_checkout(auth, order["id"], provider_order_id=begun["provider_order_id"])
    calls = list(port.calls)
    assert service.complete_paypal_checkout(auth, order["id"], provider_order_id=begun["provider_order_id"]) == paid
    assert service.reconcile_payment(auth, order["id"]) == paid and port.calls == calls
    dashboard = service.dashboard(auth, inst.id)
    assert dashboard["balance_micro_usd"] == 5_000_000
    assert len(dashboard["receipts"]) == len(dashboard["ledger"]) == 1
    assert dashboard["payment_profile"] is None


def test_sandbox_purchase_capture_rechecks_controls_and_unknown_never_releases_hold(build_env):
    env, service, port, auth, inst, ops, _ = sandbox(build_env, funded=True)
    _, purchase, order = approved_purchase(service, auth, inst.id)
    begun = service.begin_paypal_checkout(auth, order["id"])
    assert service.cancel_paypal_checkout(auth, order["id"])["state"] == "pending"
    assert service.dashboard(auth, inst.id)["policy"]["held_minor"] == 100
    port.orders[order["id"]]["status"] = "APPROVED"
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "pause")
    with pytest.raises(AiclError) as paused:
        service.complete_paypal_checkout(auth, order["id"], provider_order_id=begun["provider_order_id"])
    assert paused.value.extra["reason"] == "instance_not_active" and port.calls == ["start"]
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "resume")
    port.lost = True
    with pytest.raises(AiclError):
        service.complete_paypal_checkout(auth, order["id"], provider_order_id=begun["provider_order_id"])
    unknown = service.order(auth, order["id"])
    assert unknown["payment_phase"] == "unknown" and not unknown["can_complete_paypal"]
    assert service.cancel_paypal_checkout(auth, order["id"]) == unknown
    with pytest.raises(AiclError):
        service.decide_purchase(auth, purchase["id"], "decline", purchase["quote_digest"])
    assert service.dashboard(auth, inst.id)["policy"]["held_minor"] == 100
    paid = service.reconcile_payment(auth, order["id"])
    assert paid["state"] == "completed" and port.calls == ["start", "complete", "status"]
    dashboard = service.dashboard(auth, inst.id)
    assert dashboard["policy"]["spent_minor"] == 100 and dashboard["policy"]["held_minor"] == 0
    assert len(dashboard["receipts"]) == 2  # Existing fixture funding stays distinct.
    assert len(dashboard["ledger"]) == 2  # Purchase never debits service credit.


def test_sandbox_exact_approval_and_payee_are_bound_before_dispatch(build_env):
    env, service, port, auth, inst, _, _ = sandbox(build_env, funded=True)
    _, purchase, order = approved_purchase(service, auth, inst.id)
    begun = service.begin_paypal_checkout(auth, order["id"])
    with env.db.transaction() as conn:
        conn.execute("UPDATE mock_commerce_purchase SET approved_at = approved_at || 'changed' WHERE id = ?", (purchase["id"],))
    with pytest.raises(AiclError) as changed:
        service.complete_paypal_checkout(auth, order["id"], provider_order_id=begun["provider_order_id"])
    assert changed.value.error == "provider_mismatch" and port.calls == ["start"]
    topup = service.create_topup(auth, inst.id, 500, "bound-payee")
    port.payee = "DIFFERENTMERCHANT"
    with pytest.raises(AiclError) as wrong_payee:
        service.begin_paypal_checkout(auth, topup["id"])
    assert wrong_payee.value.error == "provider_mismatch" and port.calls == ["start"]


def test_transport_switch_cannot_send_legacy_mock_orders_to_paypal_or_settle_sandbox_locally(build_env):
    env, service, port, auth, inst, _, inline = sandbox(build_env)
    mock = inline.create_topup(auth, inst.id, 500, "old-inline")
    inline.select_payment_buyer(auth, mock["id"], "demo-buyer")
    with pytest.raises(AiclError):
        service.begin_paypal_checkout(auth, mock["id"])
    paid = service.checkout(auth, mock["id"], "complete")
    assert paid["payment_transport"] == "inline_fixture" and not port.calls
    order = service.create_topup(auth, inst.id, 500, "new-sandbox")
    with pytest.raises(AiclError):
        inline.checkout(auth, order["id"], "complete")
    with pytest.raises(AiclError):
        inline.begin_paypal_checkout(auth, order["id"])
    assert inline.order(auth, order["id"])["state"] == "created" and not port.calls
    assert service.cancel_paypal_checkout(auth, order["id"])["state"] == "cancelled"


@pytest.mark.parametrize("mismatch", [{"provider_merchant_id": "WRONG"},
    {"approval_url": "https://attacker.invalid/checkoutnow?token=x"}, {"amount_minor": 999}])
def test_sandbox_mismatched_response_cannot_credit_and_preserves_unknown(build_env, mismatch):
    env, service, port, auth, inst, _, _ = sandbox(build_env)
    order = service.create_topup(auth, inst.id, 500, "mismatch")
    port.mismatch = mismatch
    with pytest.raises(AiclError):
        service.begin_paypal_checkout(auth, order["id"])
    assert service.order(auth, order["id"])["payment_phase"] == "unknown"
    assert service.dashboard(auth, inst.id)["balance_micro_usd"] == 0
    port.mismatch = {}
    assert service.reconcile_payment(auth, order["id"])["state"] == "pending"
    assert not service.dashboard(auth, inst.id)["receipts"]


def test_sandbox_migration_preserves_existing_orders_receipts_and_ledgers(build_env, tmp_path):
    legacy = tmp_path / "legacy-migrations"
    legacy.mkdir()
    for migration in MIGRATIONS_DIR.glob("*.sql"):
        if migration.name < "0016_paypal_sandbox.sql":
            (legacy / migration.name).write_text(migration.read_text())
    with patch("aicl.db.MIGRATIONS_DIR", legacy):
        env = build_env()
    # Seed a complete legacy checkout without touching its append-only history.
    auth, inst = env.new_instance()
    with env.db.transaction() as conn:
        conn.execute("INSERT INTO mock_commerce_order (id,instance_id,tenant_id,owner_id,purpose,request_id,amount_minor,currency,merchant_id,merchant_name,state,created_at,updated_at) VALUES ('old',?,?,?,'service_topup','old',500,'USD','habitat-demo','Habitat','completed','now','now')", (inst.id, auth.tenant_id, auth.owner_id))
        conn.execute("INSERT INTO mock_commerce_receipt (id,order_id,instance_id,purpose,capture_id,merchant_id,merchant_name,amount_minor,currency,created_at) VALUES ('receipt','old',?,'service_topup','old-capture','habitat-demo','Habitat',500,'USD','now')", (inst.id,))
        conn.execute("INSERT INTO mock_commerce_ledger (id,instance_id,kind,delta_micro_usd,reference,receipt_id,created_at) VALUES ('ledger',?,'service_topup',5000000,'topup:old','receipt','now')", (inst.id,))
        before = {table: [dict(row) for row in conn.execute("SELECT * FROM " + table)] for table in ("mock_commerce_order", "mock_commerce_receipt", "mock_commerce_ledger")}
    env.db.migrate()
    with env.db.reader() as conn:
        assert list(conn.execute("PRAGMA foreign_key_check")) == []
        for table, records in before.items():
            after = [dict(row) for row in conn.execute("SELECT * FROM " + table)]
            assert [{key: row[key] for key in records[0]} for row in after] == records
        assert conn.execute("SELECT provider_merchant_id, paypal_approval_url FROM mock_commerce_order").fetchone()[:] == (None, None)


def test_expired_sandbox_purchase_needs_explicit_exact_renewal_and_current_controls(build_env):
    from datetime import timedelta
    import json

    env, service, port, auth, inst, ops, _ = sandbox(build_env, funded=True)
    _, purchase, order = approved_purchase(service, auth, inst.id)
    begun = service.begin_paypal_checkout(auth, order["id"])
    port.orders[order["id"]]["status"] = "APPROVED"
    with env.db.reader() as conn:
        original_purchase = dict(conn.execute("SELECT * FROM mock_commerce_purchase WHERE id = ?", (purchase["id"],)).fetchone())
        original_binding = conn.execute("SELECT payment_binding_json FROM mock_commerce_order WHERE id = ?", (order["id"],)).fetchone()[0]
    env.clock.set(env.clock.now() + timedelta(minutes=16))
    args = {"provider_order_id": begun["provider_order_id"]}
    with pytest.raises(AiclError) as expired:
        service.complete_paypal_checkout(auth, order["id"], **args)
    assert expired.value.extra["reason"] == "paypal_approval_expired"
    assert service.purchase(auth, purchase["id"])["state"] == "payment_pending"
    assert service.dashboard(auth, inst.id)["policy"]["held_minor"] == 100
    with pytest.raises(AiclError) as wrong:
        service.complete_paypal_checkout(auth, order["id"], **args, renew_approval=True, quote_digest="changed")
    assert wrong.value.extra["reason"] == "confirmation_mismatch"
    renewal = {**args, "renew_approval": True, "quote_digest": purchase["quote_digest"]}
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "pause")
    with pytest.raises(AiclError) as paused:
        service.complete_paypal_checkout(auth, order["id"], **renewal)
    assert paused.value.extra["reason"] == "instance_not_active"
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "resume")
    ops.set_capability(auth, inst.id, env.instances.get(auth, inst.id).version, "inference", False)
    with pytest.raises(AiclError) as disabled:
        service.complete_paypal_checkout(auth, order["id"], **renewal)
    assert disabled.value.extra["reason"] == "capability_disabled"
    ops.set_capability(auth, inst.id, env.instances.get(auth, inst.id).version, "inference", True)
    with env.db.transaction() as conn:
        conn.execute("UPDATE mock_commerce_account SET purchase_enabled = 0 WHERE instance_id = ?", (inst.id,))
    with pytest.raises(AiclError) as policy:
        service.complete_paypal_checkout(auth, order["id"], **renewal)
    assert policy.value.extra["reason"] == "purchases_disabled"
    with env.db.transaction() as conn:
        conn.execute("UPDATE mock_commerce_account SET purchase_enabled = 1 WHERE instance_id = ?", (inst.id,))
    assert port.calls == ["start"]
    paid = service.complete_paypal_checkout(auth, order["id"], **renewal)
    assert paid["state"] == "completed" and port.calls == ["start", "complete"]
    assert service.complete_paypal_checkout(auth, order["id"], **renewal) == paid
    assert port.calls == ["start", "complete"]
    with env.db.reader() as conn:
        after = conn.execute("SELECT * FROM mock_commerce_purchase WHERE id = ?", (purchase["id"],)).fetchone()
        for key in ("approved_at", "quote_digest", "quote_json", "expires_at"):
            assert after[key] == original_purchase[key]
        assert conn.execute("SELECT payment_binding_json FROM mock_commerce_order WHERE id = ?", (order["id"],)).fetchone()[0] == original_binding
        renewals = [json.loads(row[0]) for row in conn.execute("SELECT details FROM audit_event WHERE event_type = 'commerce.purchase_changed'")
                    if json.loads(row[0]).get("action") == "sandbox_approval_renewed"]
        assert len(renewals) == 1 and renewals[0]["payload_digest_prefix"] == purchase["quote_digest"][:12]
        assert renewals[0]["order_id"] == order["id"]
        assert conn.execute("SELECT COUNT(*) FROM mock_commerce_receipt WHERE order_id = ?", (order["id"],)).fetchone()[0] == 1


def test_expired_sandbox_renewal_cannot_approve_a_changed_merchant_quote(build_env):
    from datetime import timedelta

    env, service, port, auth, inst, _, _ = sandbox(build_env, funded=True)
    _, purchase, order = approved_purchase(service, auth, inst.id)
    begun = service.begin_paypal_checkout(auth, order["id"])
    port.orders[order["id"]]["status"] = "APPROVED"
    env.clock.set(env.clock.now() + timedelta(minutes=16))
    original = service.merchant.quote
    service.merchant.quote = lambda offer_id=None: {**original(offer_id), "amount_minor": 200}
    with pytest.raises(AiclError) as changed:
        service.complete_paypal_checkout(auth, order["id"], provider_order_id=begun["provider_order_id"],
                                         renew_approval=True, quote_digest=purchase["quote_digest"])
    assert changed.value.extra["reason"] == "confirmation_mismatch" and port.calls == ["start"]
    assert service.dashboard(auth, inst.id)["policy"]["held_minor"] == 100
    assert service.purchase(auth, purchase["id"])["state"] == "payment_pending"
