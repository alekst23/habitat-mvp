"""SQLite-backed local commerce demo, with real owner controls and fake providers.

Inline fixtures settle atomically. HTTP mock and PayPal Sandbox payment ports use
a durable claim, network dispatch outside SQLite, and verified local settlement.
Unknown remote outcomes retain quota until an owner reconciles the same order.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import timedelta
from functools import wraps
from urllib.parse import parse_qs, urlsplit

from aicl.clock import Clock
from aicl.control.auth import AuthContext
from aicl.commerce.buyers import DEMO_BUYERS
from aicl.commerce.adapters import (
    CATALOG, DEFAULT_TASK_BRIEF, ESTIMATE, HABITAT_MERCHANT_ID, HABITAT_MERCHANT_NAME, MEASURED_USAGE, MODE, MODEL,
    TASK_SCENARIO,
    TOPUP_AMOUNTS_MINOR, MockInferenceAdapter, MockMerchantAdapter, MockPaymentAdapter,
)
from aicl.control.audit import AuditEvent, SqliteAuditLog
from aicl.control.budget import SqliteBudgetPort
from aicl.control.errors import AiclError
from aicl.control.price_table import cost_micro_usd, effective_version
from aicl.db import Database, to_iso

_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ACTIVE_PURCHASES = ("awaiting_approval", "awaiting_checkout", "payment_pending")
_ACTIVE_RUNS = (*_ACTIVE_PURCHASES, "ready_to_resume")
_BRIEF_LIMITS = {"product_name": 120, "audience": 240, "goal": 600}
_UNSET_BUYER = object()


def _new_id() -> str:
    return str(uuid.uuid4())


def _canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _mutation(method):
    """Audit a scoped refusal after its transaction has rolled back, without secrets."""
    @wraps(method)
    def call(self, auth, *args, **kwargs):
        try:
            return method(self, auth, *args, **kwargs)
        except AiclError as error:
            instance_id = getattr(error, "commerce_instance_id", None)
            if error.error == "denied" and instance_id:
                with self.db.transaction() as conn:
                    self._owned_instance(conn, auth, instance_id)
                    self._event(conn, auth, instance_id, "commerce.denied", "denied",
                                reason=str(error.extra.get("reason", "check_unavailable")))
            raise
    return call


class MockCommerceService:
    """All public methods require the authenticated owner; never accepts tenant IDs.

    Money is integer USD cents on orders and integer micro-USD in the service-credit
    ledger. Purchase allowance is cumulative policy quota, not service credit.
    """

    def __init__(self, db: Database, clock: Clock, hold_stale_seconds: int = 900, *, payments=None) -> None:
        self.db, self.clock = db, clock
        self.budget = SqliteBudgetPort(db, clock, hold_stale_seconds)
        self.audit = SqliteAuditLog(clock)
        self.payments, self.merchant, self.inference = (
            payments or MockPaymentAdapter(), MockMerchantAdapter(), MockInferenceAdapter())
        self.payment_transport = getattr(self.payments, "transport", "inline_fixture")
        if self.payment_transport not in ("inline_fixture", "http_mock", "paypal_sandbox"):
            raise ValueError("unsupported payment transport")

    def _owned_instance(self, conn, auth, instance_id):
        if auth.expires_at <= self.clock.now():
            raise AiclError("unauthenticated", "sign in required")
        row = conn.execute("SELECT * FROM agent_instance WHERE id = ? AND tenant_id = ? AND owner_id = ?",
                           (instance_id, auth.tenant_id, auth.owner_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "instance not found")
        return row

    def _owned_resource(self, conn, auth, table, resource_id):
        queries = {
            "mock_commerce_order": "SELECT * FROM mock_commerce_order WHERE id = ? AND tenant_id = ? AND owner_id = ?",
            "mock_commerce_run": "SELECT * FROM mock_commerce_run WHERE id = ? AND tenant_id = ? AND owner_id = ?",
            "mock_commerce_purchase": "SELECT * FROM mock_commerce_purchase WHERE id = ? AND tenant_id = ? AND owner_id = ?",
        }
        if table not in queries:
            raise ValueError("unsupported resource")
        row = conn.execute(queries[table],
                           (resource_id, auth.tenant_id, auth.owner_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "commerce record not found")
        self._owned_instance(conn, auth, row["instance_id"])
        return row

    def _event(self, conn, auth, instance_id, event_type, outcome="committed", reason=None, **details):
        self.audit.append(conn, AuditEvent(event_type, "owner", outcome, auth.tenant_id, auth.owner_id,
                                          instance_id, reason=reason, details={"mode": MODE, **details}))

    def _reject(self, instance_id, reason, message):
        error = AiclError("denied", message, reason=reason)
        error.commerce_instance_id = instance_id
        raise error

    def _request_id(self, value):
        if not isinstance(value, str) or not _REQUEST_ID.fullmatch(value):
            raise AiclError("validation_failed", "request_id must be a short stable identifier")

    def _brief(self, value):
        if value is None:
            return dict(DEFAULT_TASK_BRIEF)
        if not isinstance(value, dict) or set(value) != set(_BRIEF_LIMITS):
            raise AiclError("validation_failed", "Task brief must contain product_name, audience and goal.")
        normalized, errors = {}, {}
        for field, limit in _BRIEF_LIMITS.items():
            item = value[field]
            if not isinstance(item, str) or not item.strip() or len(item.strip()) > limit:
                errors[field] = f"Enter 1–{limit} characters."
            else:
                normalized[field] = item.strip()
        if errors:
            raise AiclError("validation_failed", "Complete the task brief within the stated limits.", field_errors=errors)
        return normalized

    def _draft_brief(self, conn, instance_id):
        row = conn.execute("SELECT draft_brief_json FROM mock_commerce_account WHERE instance_id = ?", (instance_id,)).fetchone()
        return (json.loads(row[0]) or dict(DEFAULT_TASK_BRIEF)) if row else dict(DEFAULT_TASK_BRIEF)

    def _account(self, conn, instance_id):
        conn.execute("INSERT OR IGNORE INTO mock_commerce_account (instance_id) VALUES (?)", (instance_id,))

    def _balance(self, conn, instance_id):
        balance = conn.execute("SELECT COALESCE(SUM(delta_micro_usd),0) FROM mock_commerce_ledger "
                               "WHERE instance_id = ?", (instance_id,)).fetchone()[0]
        # Live calls retain service credit while outside the SQLite transaction.
        # Every commerce path must respect those reservations, including fixtures.
        reserved = conn.execute("SELECT COALESCE(SUM(h.inference_micro_usd+h.compute_micro_usd),0) "
                                "FROM budget_hold h JOIN workflow_inference_attempt a ON a.hold_id=h.id "
                                "WHERE h.instance_id=? AND h.state IN ('held','unknown')", (instance_id,)).fetchone()[0]
        compute = conn.execute("SELECT COALESCE(SUM(cost_micro_usd),0) FROM render_compute_usage WHERE instance_id=?", (instance_id,)).fetchone()[0]
        compute_held = conn.execute("SELECT COALESCE(SUM(h.compute_micro_usd),0) FROM render_dispatch d JOIN budget_hold h ON h.id=d.hold_id WHERE d.instance_id=? AND h.state IN ('held','unknown')", (instance_id,)).fetchone()[0]
        return balance - reserved - compute - compute_held

    def _policy(self, conn, instance_id):
        row = conn.execute("SELECT * FROM mock_commerce_account WHERE instance_id = ?", (instance_id,)).fetchone()
        amounts = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN quota_state = 'held' THEN amount_minor ELSE 0 END),0), "
            "COALESCE(SUM(CASE WHEN quota_state = 'spent' THEN amount_minor ELSE 0 END),0) "
            "FROM mock_commerce_purchase WHERE instance_id = ?", (instance_id,)).fetchone()
        limit = row["purchase_limit_minor"] if row else 0
        return {"enabled": bool(row["purchase_enabled"]) if row else False, "limit_minor": limit,
                "held_minor": amounts[0], "spent_minor": amounts[1],
                "available_minor": max(0, limit - sum(amounts)), "version": row["version"] if row else 1}

    def _controls(self, conn, auth, instance_id):
        inst = self._owned_instance(conn, auth, instance_id)
        if inst["lifecycle"] != "active":
            self._reject(instance_id, "instance_not_active", "Activate or resume the agent before continuing.")
        enabled = conn.execute("SELECT enabled FROM capability_grant WHERE instance_id = ? AND capability = 'inference'",
                               (instance_id,)).fetchone()
        if not enabled or not enabled[0]:
            self._reject(instance_id, "capability_disabled", "Enable inference before continuing.")
        if inst["gated_reason"]:
            self._reject(instance_id, "gate_unresolved", "Resolve the agent's existing control gate before continuing.")
        return inst

    def _purchase_policy(self, conn, instance_id, *, additional=0):
        policy = self._policy(conn, instance_id)
        if not policy["enabled"]:
            self._reject(instance_id, "purchases_disabled", "Enable owner-approved purchases before starting this demo.")
        if policy["spent_minor"] + policy["held_minor"] + additional > policy["limit_minor"]:
            self._reject(instance_id, "purchase_limit_exceeded", "The purchase would exceed this agent's allowance.")
        return policy

    def _quote(self, instance_id, offer_id=None):
        try:
            return {**self.merchant.quote(offer_id), "recipient": f"agent:{instance_id}"}
        except ValueError:
            raise AiclError("validation_failed", "Choose a supported, versioned purchase offer.") from None

    def _price_info(self, conn):
        version = effective_version(conn, self.clock.now())
        def price(tokens):
            return None if version is None else sum(cost_micro_usd(version, meter, tokens) for meter in
                ("inference.input_tokens", "inference.output_tokens"))
        return {"model": MODEL, "estimated_step_micro_usd": price(1000), "measured_step_micro_usd": price(500),
                "input_tokens": 500, "output_tokens": 500, "price_table_version": version.version if version else None}

    def _readiness(self, conn, auth, instance_id, *, run_state=None):
        blockers = []
        def blocked(reason, message):
            if not any(item["reason"] == reason for item in blockers):
                blockers.append({"reason": reason, "message": message})
        inst = self._owned_instance(conn, auth, instance_id)
        unresolved = conn.execute("SELECT * FROM mock_commerce_order WHERE instance_id = ? AND state = 'pending'", (instance_id,)).fetchall()
        if any(dict(order).get("payment_phase") in ("inflight", "unknown") for order in unresolved):
            blocked("payment_unresolved", "Check the unresolved payment status before continuing with new work.")
        if inst["lifecycle"] != "active":
            blocked("instance_not_active", "Activate or resume the agent before continuing.")
        enabled = conn.execute("SELECT enabled FROM capability_grant WHERE instance_id = ? AND capability = 'inference'",
                               (instance_id,)).fetchone()
        if not enabled or not enabled[0]:
            blocked("capability_disabled", "Enable inference before continuing.")
        if inst["gated_reason"]:
            blocked("gate_unresolved", "Resolve the agent's existing control gate before continuing.")
        prices = self._price_info(conn)
        estimate = prices["estimated_step_micro_usd"]
        if estimate is None:
            blocked("price_unavailable", "A current price table is required.")
        elif self._balance(conn, instance_id) < estimate:
            blocked("credit_insufficient", "Add service credit to fund the agent's bounded inference step.")
        view = self.budget.read_budget(instance_id)
        if view.blocking_hold_count:
            blocked("reconciliation_pending", "Resolve the existing unknown or stale work reservation.")
        for category, windows in view.windows.items():
            for amounts in windows.values():
                if amounts.limit <= 0 or (category == "inference" and estimate is not None and amounts.available < estimate):
                    blocked("budget_exhausted", "Set positive daily and monthly inference and compute limits with room for this run.")
        # A current purchase already holds its allowance. A delivered purchase needs
        # only the next inference step, never another purchase authorization or hold.
        if run_state != "ready_to_resume":
            policy = self._policy(conn, instance_id)
            if not policy["enabled"]:
                blocked("purchases_disabled", "Enable owner-approved purchases and set an allowance.")
            if run_state in _ACTIVE_PURCHASES:
                if policy["spent_minor"] + policy["held_minor"] > policy["limit_minor"]:
                    blocked("purchase_limit_exceeded", "The existing purchase commitments exceed this agent's allowance.")
            elif policy["available_minor"] < CATALOG["amount_minor"]:
                blocked("purchase_limit_exceeded", "Allow at least $1.00 of available purchase quota for the template.")
        return {"ready": not blockers, "blockers": blockers}

    def _receipt_projection(self, row):
        return {**dict(row), "mode": MODE}

    def _payment_profile(self, conn, auth):
        if auth.expires_at <= self.clock.now():
            raise AiclError("unauthenticated", "sign in required")
        row = conn.execute("SELECT buyer_id FROM mock_payment_profile WHERE tenant_id = ? AND owner_id = ?",
                           (auth.tenant_id, auth.owner_id)).fetchone()
        return {"buyer_id": row["buyer_id"], "buyer_label": DEMO_BUYERS[row["buyer_id"]]} if row else None

    def payment_profile(self, auth: AuthContext) -> dict | None:
        with self.db.reader() as conn:
            return self._payment_profile(conn, auth)

    def _buyer_can_change(self, order):
        # Once sent, provider idempotency binds the original payload even if no
        # response arrived. The owner's preference must never rewrite that order.
        return (order["payment_transport"] != "paypal_sandbox" and order["state"] == "created" and order["payment_phase"] in ("not_started", "created")
                and not order["payment_binding_json"] and not order["provider_order_id"])

    @_mutation
    def select_payment_buyer(self, auth: AuthContext, order_id: str, buyer_id: str,
                             *, expected_current_buyer_id=_UNSET_BUYER) -> dict:
        if not isinstance(buyer_id, str) or buyer_id not in DEMO_BUYERS:
            raise AiclError("validation_failed", "Choose one of the fictional demo buyers.")
        with self.db.transaction() as conn:
            order = self._owned_resource(conn, auth, "mock_commerce_order", order_id)
            if order["payment_transport"] == "paypal_sandbox":
                raise AiclError("invalid_transition", "Choose your Sandbox buyer securely at PayPal checkout.")
            if expected_current_buyer_id is not _UNSET_BUYER and expected_current_buyer_id != order["buyer_id"]:
                self._reject(order["instance_id"], "buyer_changed", "The buyer changed in another tab. Review this checkout before choosing an account.")
            if not self._buyer_can_change(order):
                if order["buyer_id"] == buyer_id:
                    return self._order_projection(conn, order)
                raise AiclError("invalid_transition", "This payment already has a fixed buyer. Use a new order to change accounts.")
            now = to_iso(self.clock.now())
            conn.execute("INSERT INTO mock_payment_profile (tenant_id,owner_id,buyer_id,updated_at) VALUES (?,?,?,?) "
                         "ON CONFLICT(tenant_id,owner_id) DO UPDATE SET buyer_id = excluded.buyer_id, updated_at = excluded.updated_at",
                         (auth.tenant_id, auth.owner_id, buyer_id, now))
            conn.execute("UPDATE mock_commerce_order SET buyer_id = ?, updated_at = ? WHERE id = ?", (buyer_id, now, order_id))
            self._event(conn, auth, order["instance_id"], "commerce.checkout_changed", order_id=order_id,
                        action="buyer_selected", buyer_id=buyer_id)
            return self._order_projection(conn, self._owned_resource(conn, auth, "mock_commerce_order", order_id))

    def _require_payment_buyer(self, order, expected_buyer_id=None):
        if order["buyer_required"] and not order["buyer_id"]:
            self._reject(order["instance_id"], "buyer_required", "Select a demo PayPal buyer before authorizing this payment.")
        if expected_buyer_id is not None and expected_buyer_id != order["buyer_id"]:
            self._reject(order["instance_id"], "buyer_changed", "The buyer changed in another tab. Review this checkout before paying.")

    def _order_projection(self, conn, row):
        receipt = conn.execute("SELECT capture_id FROM mock_commerce_receipt WHERE order_id = ?", (row["id"],)).fetchone()
        purchase = conn.execute("SELECT quote_json,fulfillment_json FROM mock_commerce_purchase WHERE id = ?",
                                (row["purchase_id"],)).fetchone() if row["purchase_id"] else None
        quote = json.loads(purchase["quote_json"]) if purchase else None
        return {key: row[key] for key in ("id", "instance_id", "purpose", "amount_minor", "currency", "merchant_id",
                "merchant_name", "state", "purchase_id", "created_at")} | {
                    "mode": MODE, "capture_id": receipt[0] if receipt else None,
                    "quote": quote, "campaign": quote.get("campaign") if quote else None,
                    "fulfillment": json.loads(purchase["fulfillment_json"]) if purchase and purchase["fulfillment_json"] else None,
                    "payment_transport": dict(row).get("payment_transport", "inline_fixture"),
                    "provider_order_id": dict(row).get("provider_order_id"),
                    "is_paypal_sandbox": row["payment_transport"] == "paypal_sandbox",
                    "approval_url": row["paypal_approval_url"] if row["payment_transport"] == "paypal_sandbox" else None,
                    "can_begin_paypal": row["payment_transport"] == "paypal_sandbox"
                        and row["state"] == "created" and row["payment_phase"] == "not_started",
                    "can_complete_paypal": row["payment_transport"] == "paypal_sandbox"
                        and bool(row["provider_order_id"]) and row["state"] == "pending"
                        and row["payment_phase"] == "created",
                    "payment_phase": dict(row).get("payment_phase", "not_started"),
                    "buyer_id": row["buyer_id"], "buyer_label": DEMO_BUYERS.get(row["buyer_id"]),
                    "buyer_required": bool(row["buyer_required"]), "buyer_can_change": self._buyer_can_change(row),
                    "can_reconcile": dict(row).get("payment_transport") in ("http_mock", "paypal_sandbox")
                        and row["state"] not in ("completed", "cancelled")
                        and dict(row).get("payment_phase") != "not_started"}

    def _purchase_projection(self, conn, row):
        order = conn.execute("SELECT id FROM mock_commerce_order WHERE purchase_id = ?", (row["id"],)).fetchone()
        receipt = None if not order else conn.execute("SELECT id FROM mock_commerce_receipt WHERE order_id = ?", (order[0],)).fetchone()
        quote = json.loads(row["quote_json"])
        return {key: row[key] for key in ("id", "instance_id", "run_id", "state", "quote_digest", "expires_at", "approved_at")} | {
            "mode": MODE, "quote": quote, "campaign": quote.get("campaign"), "order_id": order[0] if order else None,
            "receipt_id": receipt[0] if receipt else None,
            "fulfillment": json.loads(row["fulfillment_json"]) if row["fulfillment_json"] else None}

    def _run_projection(self, conn, row):
        purchase = conn.execute("SELECT * FROM mock_commerce_purchase WHERE run_id = ?", (row["id"],)).fetchone()
        return {key: row[key] for key in ("id", "instance_id", "state", "output", "inference_cost_micro_usd", "created_at")} | {
            "mode": MODE, "model": MODEL, "token_usage": {"input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"]},
            "scenario": TASK_SCENARIO, "brief": json.loads(row["brief_json"]),
            "purchase_id": purchase["id"] if purchase else None,
            "purchase": self._purchase_projection(conn, purchase) if purchase else None}

    def dashboard(self, auth: AuthContext, instance_id: str) -> dict:
        with self.db.reader() as conn:
            self._owned_instance(conn, auth, instance_id)
            # Active tasks take precedence even for databases containing multiple legacy runs.
            # Retain the recent history limit while never hiding an unresolved task.
            rows = conn.execute("SELECT * FROM mock_commerce_run WHERE instance_id = ? ORDER BY rowid DESC LIMIT 50", (instance_id,)).fetchall()
            active_rows = conn.execute("SELECT * FROM mock_commerce_run WHERE instance_id = ? "
                                       "AND state IN (?,?,?,?) ORDER BY rowid DESC", (instance_id, *_ACTIVE_RUNS)).fetchall()
            current_row = active_rows[0] if active_rows else rows[0] if rows else None
            recent_ids = {row["id"] for row in rows}
            runs = [self._run_projection(conn, row) for row in rows + [row for row in active_rows if row["id"] not in recent_ids]]
            current = next((run for run in runs if current_row and run["id"] == current_row["id"]), None)
            account = conn.execute("SELECT draft_brief_json FROM mock_commerce_account WHERE instance_id = ?", (instance_id,)).fetchone()
            return {"mode": MODE, "payment_transport": self.payment_transport, "payment_profile": None if self.payment_transport == "paypal_sandbox" else self._payment_profile(conn, auth),
                    "instance_id": instance_id, "balance_micro_usd": self._balance(conn, instance_id),
                    "scenario": TASK_SCENARIO, "draft_brief": self._draft_brief(conn, instance_id),
                    "brief_saved": bool(account and json.loads(account[0])),
                    "current_run": current, "history_runs": [run for run in runs if not current or run["id"] != current["id"]],
                    "active_run_count": len(active_rows), "attention_count": len(active_rows),
                    "policy": self._policy(conn, instance_id), "catalog": self.merchant.quote(),
                    "topup_amounts_minor": list(TOPUP_AMOUNTS_MINOR), "inference": self._price_info(conn),
                    "readiness": self._readiness(conn, auth, instance_id),
                    "current_readiness": self._readiness(conn, auth, instance_id, run_state=current["state"] if current else None),
                    "orders": [self._order_projection(conn, r) for r in conn.execute(
                        "SELECT * FROM mock_commerce_order WHERE instance_id = ? ORDER BY rowid DESC LIMIT 50", (instance_id,))],
                    "purchases": [self._purchase_projection(conn, r) for r in conn.execute(
                        "SELECT * FROM mock_commerce_purchase WHERE instance_id = ? ORDER BY rowid DESC LIMIT 50", (instance_id,))],
                    "runs": runs,
                    "receipts": [self._receipt_projection(r) for r in conn.execute(
                        "SELECT * FROM mock_commerce_receipt WHERE instance_id = ? ORDER BY rowid DESC LIMIT 100", (instance_id,))],
                    "ledger": [dict(r) for r in conn.execute(
                        "SELECT * FROM mock_commerce_ledger WHERE instance_id = ? ORDER BY rowid DESC LIMIT 100", (instance_id,))]}

    @_mutation
    def save_brief(self, auth: AuthContext, instance_id: str, brief: dict, expected_version: int) -> dict:
        if brief is None:
            raise AiclError("validation_failed", "Complete the task brief before saving.")
        normalized = self._brief(brief)
        if type(expected_version) is not int or expected_version < 1:
            raise AiclError("validation_failed", "expected_version must be a positive integer")
        with self.db.transaction() as conn:
            self._owned_instance(conn, auth, instance_id)
            self._account(conn, instance_id)
            policy = self._policy(conn, instance_id)
            if policy["version"] != expected_version:
                raise AiclError("conflict", "Task or purchase settings changed; reload and try again.", current_version=policy["version"])
            conn.execute("UPDATE mock_commerce_account SET draft_brief_json = ?, version = version + 1 WHERE instance_id = ?",
                         (_canonical(normalized), instance_id))
            self._event(conn, auth, instance_id, "commerce.policy_changed", action="task_brief_saved", version=expected_version + 1)
            return {"scenario": TASK_SCENARIO, "draft_brief": normalized, "version": expected_version + 1}

    @_mutation
    def configure(self, auth: AuthContext, instance_id: str, enabled: bool, limit_minor: int, expected_version: int) -> dict:
        if type(enabled) is not bool or type(limit_minor) is not int or not 0 <= limit_minor <= 1_000_000:
            raise AiclError("validation_failed", "Use a boolean enabled flag and an integer allowance of 0–1000000 cents.")
        if type(expected_version) is not int or expected_version < 1:
            raise AiclError("validation_failed", "expected_version must be a positive integer")
        with self.db.transaction() as conn:
            self._owned_instance(conn, auth, instance_id)
            self._account(conn, instance_id)
            policy = self._policy(conn, instance_id)
            if policy["version"] != expected_version:
                raise AiclError("conflict", "Purchase policy changed; reload and try again.", current_version=policy["version"])
            minimum = policy["spent_minor"] + (policy["held_minor"] if enabled else 0)
            if limit_minor < minimum:
                raise AiclError("conflict", "Allowance cannot be below purchases already spent or held.")
            if not enabled:
                for purchase in conn.execute("SELECT * FROM mock_commerce_purchase WHERE instance_id = ? AND quota_state = 'held'",
                                             (instance_id,)).fetchall():
                    self._end_purchase(conn, auth, purchase, "cancelled")
            conn.execute("UPDATE mock_commerce_account SET purchase_enabled = ?, purchase_limit_minor = ?, version = version + 1 "
                         "WHERE instance_id = ?", (int(enabled), limit_minor, instance_id))
            self._event(conn, auth, instance_id, "commerce.policy_changed", enabled=enabled, amount_minor=limit_minor,
                        version=expected_version + 1)
            return self._policy(conn, instance_id)

    @_mutation
    def create_topup(self, auth: AuthContext, instance_id: str, amount_minor: int, request_id: str) -> dict:
        self._request_id(request_id)
        if type(amount_minor) is not int or amount_minor not in TOPUP_AMOUNTS_MINOR:
            raise AiclError("validation_failed", "Choose a top-up of $5, $10 or $20.")
        with self.db.transaction() as conn:
            inst = self._owned_instance(conn, auth, instance_id)
            existing = conn.execute("SELECT * FROM mock_commerce_order WHERE tenant_id = ? AND purpose = 'service_topup' AND request_id = ?",
                                    (auth.tenant_id, request_id)).fetchone()
            if existing:
                if existing["instance_id"] != instance_id or existing["owner_id"] != auth.owner_id or existing["amount_minor"] != amount_minor:
                    raise AiclError("conflict", "request_id was already used for a different top-up.")
                return self._order_projection(conn, existing)
            if inst["lifecycle"] == "archived":
                self._reject(instance_id, "instance_not_active", "An archived agent cannot receive a new top-up.")
            self._account(conn, instance_id)
            order_id = self._insert_order(conn, auth, instance_id, "service_topup", request_id, amount_minor,
                                          HABITAT_MERCHANT_ID, HABITAT_MERCHANT_NAME)
            self._event(conn, auth, instance_id, "commerce.order_created", order_id=order_id, purpose="service_topup", amount_minor=amount_minor)
            return self._order_projection(conn, self._owned_resource(conn, auth, "mock_commerce_order", order_id))

    def _insert_order(self, conn, auth, instance_id, purpose, request_id, amount_minor, merchant_id, merchant_name, purchase_id=None):
        order_id, now = _new_id(), to_iso(self.clock.now())
        conn.execute("INSERT INTO mock_commerce_order (id,instance_id,tenant_id,owner_id,purpose,request_id,purchase_id,"
                     "amount_minor,currency,merchant_id,merchant_name,state,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,'USD',?,?,'created',?,?)",
                     (order_id, instance_id, auth.tenant_id, auth.owner_id, purpose, request_id, purchase_id,
                      amount_minor, merchant_id, merchant_name, now, now))
        conn.execute("UPDATE mock_commerce_order SET payment_transport = ? WHERE id = ?", (self.payment_transport, order_id))
        if self.payment_transport == "paypal_sandbox":
            order = dict(conn.execute("SELECT * FROM mock_commerce_order WHERE id = ?", (order_id,)).fetchone())
            payee = self.payments.merchant_id_for(order)
            if not isinstance(payee, str) or not payee or len(payee) > 128:
                raise self._provider_error("provider_unavailable", "A configured PayPal Sandbox merchant is required.")
            conn.execute("UPDATE mock_commerce_order SET provider_merchant_id = ? WHERE id = ?", (payee, order_id))
        else:
            profile = self._payment_profile(conn, auth)
            conn.execute("UPDATE mock_commerce_order SET buyer_required = 1, buyer_id = ? WHERE id = ?",
                         (profile["buyer_id"] if profile else None, order_id))
        return order_id

    def order(self, auth: AuthContext, order_id: str) -> dict:
        with self.db.reader() as conn:
            return self._order_projection(conn, self._owned_resource(conn, auth, "mock_commerce_order", order_id))

    def purchase(self, auth: AuthContext, purchase_id: str) -> dict:
        with self.db.reader() as conn:
            return self._purchase_projection(conn, self._owned_resource(conn, auth, "mock_commerce_purchase", purchase_id))

    def run(self, auth: AuthContext, run_id: str) -> dict:
        with self.db.reader() as conn:
            return self._run_projection(conn, self._owned_resource(conn, auth, "mock_commerce_run", run_id))

    def _payment_outstanding(self, conn, purchase_id):
        order = conn.execute("SELECT * FROM mock_commerce_order WHERE purchase_id = ?", (purchase_id,)).fetchone()
        return bool(order and dict(order).get("payment_transport") in ("http_mock", "paypal_sandbox")
                    and dict(order).get("payment_phase") not in ("not_started", "completed", "cancelled"))

    def _end_purchase(self, conn, auth, purchase, state, *, verified_cancel=False):
        if not verified_cancel and self._payment_outstanding(conn, purchase["id"]):
            self._reject(purchase["instance_id"], "reconciliation_pending",
                         "Reconcile the provider payment before releasing this purchase allowance.")
        now = to_iso(self.clock.now())
        conn.execute("UPDATE mock_commerce_purchase SET state = ?, quota_state = 'released', updated_at = ? WHERE id = ? AND quota_state = 'held'",
                     (state, now, purchase["id"]))
        conn.execute("UPDATE mock_commerce_run SET state = ?, updated_at = ? WHERE id = ?", (state, now, purchase["run_id"]))
        conn.execute("UPDATE mock_commerce_order SET state = 'cancelled', updated_at = ? WHERE purchase_id = ? AND state != 'completed'",
                     (now, purchase["id"]))
        self._event(conn, auth, purchase["instance_id"], "commerce.purchase_changed", purchase_id=purchase["id"], action=state)

    def _valid_purchase(self, conn, auth, purchase):
        if purchase["state"] not in _ACTIVE_PURCHASES:
            self._reject(purchase["instance_id"], "confirmation_required", "This purchase is no longer awaiting authorization.")
        if purchase["expires_at"] <= to_iso(self.clock.now()):
            self._end_purchase(conn, auth, purchase, "expired")
            error = AiclError("denied", "The exact purchase approval expired. Start a new run for a fresh quote.", reason="confirmation_expired")
            error.commerce_instance_id = purchase["instance_id"]
            error.commit_on_error = True  # expiration releases only a known-unpaid local fixture
            raise error
        self._controls(conn, auth, purchase["instance_id"])
        self._purchase_policy(conn, purchase["instance_id"])
        return self._trusted_purchase_quote(purchase)

    def _trusted_purchase_quote(self, purchase):
        """Verify the immutable offer independently of current execution authority.

        A dispatched payment may settle after expiry or pause. Its receipt must
        still match the exact trusted offer and digest without reauthorizing work.
        """
        quote = json.loads(purchase["quote_json"])
        expected_digest = hashlib.sha256(_canonical({"instance_id": purchase["instance_id"], "run_id": purchase["run_id"],
            "quote": quote, "expires_at": purchase["expires_at"]}).encode()).hexdigest()
        try:
            trusted = self._quote(purchase["instance_id"], quote.get("offer_id")) if isinstance(quote, dict) else None
        except AiclError:
            trusted = None
        if (not isinstance(quote, dict) or expected_digest != purchase["quote_digest"] or quote != trusted
                or quote.get("amount_minor") != purchase["amount_minor"]):
            self._reject(purchase["instance_id"], "confirmation_mismatch", "The seller quote changed; a new purchase approval is required.")
        return quote

    @_mutation
    def decide_purchase(self, auth: AuthContext, purchase_id: str, decision: str, quote_digest: str) -> dict:
        if decision not in ("approve", "decline"):
            raise AiclError("validation_failed", "decision must be approve or decline")
        with self.db.transaction() as conn:
            purchase = self._owned_resource(conn, auth, "mock_commerce_purchase", purchase_id)
            if quote_digest != purchase["quote_digest"]:
                self._reject(purchase["instance_id"], "confirmation_mismatch", "Approval must match the displayed seller, item and total.")
            if decision == "decline":
                if purchase["state"] == "declined":
                    return self._purchase_projection(conn, purchase)
                if purchase["state"] not in _ACTIVE_PURCHASES:
                    raise AiclError("invalid_transition", "A completed or closed purchase cannot be declined.")
                self._end_purchase(conn, auth, purchase, "declined")
            else:
                if purchase["state"] == "paid":
                    return self._purchase_projection(conn, purchase)
                quote = self._valid_purchase(conn, auth, purchase)
                if purchase["approved_at"] is None:
                    now = to_iso(self.clock.now())
                    self._insert_order(conn, auth, purchase["instance_id"], "agent_purchase", purchase_id, quote["amount_minor"],
                                       quote["merchant_id"], quote["merchant_name"], purchase_id)
                    conn.execute("UPDATE mock_commerce_purchase SET state = 'awaiting_checkout', approved_at = ?, updated_at = ? WHERE id = ?",
                                 (now, now, purchase_id))
                    conn.execute("UPDATE mock_commerce_run SET state = 'awaiting_checkout', updated_at = ? WHERE id = ?", (now, purchase["run_id"]))
                    self._event(conn, auth, purchase["instance_id"], "commerce.purchase_changed", purchase_id=purchase_id,
                                action="approved", payload_digest_prefix=quote_digest[:12])
            return self._purchase_projection(conn, self._owned_resource(conn, auth, "mock_commerce_purchase", purchase_id))

    @_mutation
    def checkout(self, auth: AuthContext, order_id: str, outcome: str, *, expected_buyer_id: str | None = None) -> dict:
        if outcome not in ("complete", "cancel", "pending"):
            raise AiclError("validation_failed", "outcome must be complete, cancel or pending")
        with self.db.reader() as conn:
            order = self._owned_resource(conn, auth, "mock_commerce_order", order_id)
            if order["payment_transport"] == "paypal_sandbox":
                raise AiclError("invalid_transition", "Use the PayPal Sandbox checkout and verified return flow for this order.")
            remote = dict(order).get("payment_transport") == "http_mock"
        if remote:
            return self._http_checkout(auth, order_id, outcome, expected_buyer_id=expected_buyer_id)
        with self.db.transaction() as conn:
            order = self._owned_resource(conn, auth, "mock_commerce_order", order_id)
            if order["state"] == "completed":
                if outcome != "complete":
                    raise AiclError("invalid_transition", "A recorded payment cannot be cancelled or made pending.")
                return self._order_projection(conn, order)
            if order["state"] == "cancelled":
                if outcome != "cancel":
                    self._reject(order["instance_id"], "confirmation_required", "This local checkout was cancelled and cannot be completed.")
                return self._order_projection(conn, order)
            purchase = None
            if order["purchase_id"]:
                purchase = self._owned_resource(conn, auth, "mock_commerce_purchase", order["purchase_id"])
            if outcome == "cancel":
                if purchase:
                    self._end_purchase(conn, auth, purchase, "cancelled")
                else:
                    conn.execute("UPDATE mock_commerce_order SET state = 'cancelled', updated_at = ? WHERE id = ?", (to_iso(self.clock.now()), order_id))
            else:
                self._require_payment_buyer(order, expected_buyer_id)
                inst = self._owned_instance(conn, auth, order["instance_id"])
                if purchase:
                    quote = self._valid_purchase(conn, auth, purchase)
                    if purchase["approved_at"] is None:
                        self._reject(inst["id"], "confirmation_required", "The exact owner purchase approval is required before checkout.")
                    if (order["purpose"], order["merchant_id"], order["amount_minor"], order["currency"]) != (
                            "agent_purchase", quote["merchant_id"], quote["amount_minor"], quote["currency"]):
                        self._reject(inst["id"], "confirmation_mismatch", "The checkout does not match the approved quote.")
                elif inst["lifecycle"] == "archived":
                    self._reject(inst["id"], "instance_not_active", "An archived agent cannot receive new service credit.")
                if outcome == "pending":
                    if order["state"] != "pending":
                        now = to_iso(self.clock.now())
                        conn.execute("UPDATE mock_commerce_order SET state = 'pending', updated_at = ? WHERE id = ?", (now, order_id))
                        if purchase:
                            conn.execute("UPDATE mock_commerce_purchase SET state = 'payment_pending', updated_at = ? WHERE id = ?", (now, purchase["id"]))
                            conn.execute("UPDATE mock_commerce_run SET state = 'payment_pending', updated_at = ? WHERE id = ?", (now, purchase["run_id"]))
                else:
                    self._complete_order(conn, auth, order, purchase)
            self._event(conn, auth, order["instance_id"], "commerce.checkout_changed", order_id=order_id, action=outcome, purpose=order["purpose"])
            return self._order_projection(conn, self._owned_resource(conn, auth, "mock_commerce_order", order_id))

    def _check_paypal_merchant(self, order):
        if (not order["provider_merchant_id"]
                or self.payments.merchant_id_for(dict(order)) != order["provider_merchant_id"]):
            raise self._provider_error("provider_mismatch", "This checkout belongs to its original PayPal Sandbox merchant.")

    @_mutation
    def begin_paypal_checkout(self, auth: AuthContext, order_id: str) -> dict:
        """Create an idempotent Sandbox order; buyer authorization happens at PayPal."""
        return self._paypal_checkout(auth, order_id, "start")

    @_mutation
    def complete_paypal_checkout(self, auth: AuthContext, order_id: str, *, provider_order_id: str,
                                 renew_approval: bool = False, quote_digest: str | None = None) -> dict:
        """Capture only the stored provider order after a fresh owner/quote check.

        The adapter independently retrieves PayPal's authoritative approval state;
        neither a browser return token nor this method manufactures approval.
        """
        return self._paypal_checkout(auth, order_id, "complete", provider_order_id=provider_order_id,
                                     renew_approval=renew_approval, quote_digest=quote_digest)

    @_mutation
    def cancel_paypal_checkout(self, auth: AuthContext, order_id: str) -> dict:
        # PayPal Orders has no cancel API. Returning from checkout is not proof
        # that a submitted payment is void, so dispatched holds remain reserved.
        with self.db.transaction() as conn:
            order = self._owned_resource(conn, auth, "mock_commerce_order", order_id)
            if order["payment_transport"] != "paypal_sandbox":
                raise AiclError("invalid_transition", "This is not a PayPal Sandbox checkout.")
            if (order["state"] != "created" or order["payment_phase"] != "not_started"
                    or order["payment_binding_json"] or order["provider_order_id"]):
                return self._order_projection(conn, order)
            purchase = self._owned_resource(conn, auth, "mock_commerce_purchase", order["purchase_id"]) if order["purchase_id"] else None
            if purchase:
                self._end_purchase(conn, auth, purchase, "cancelled")
            conn.execute("UPDATE mock_commerce_order SET state = 'cancelled', payment_phase = 'cancelled', updated_at = ? WHERE id = ?",
                         (to_iso(self.clock.now()), order_id))
            self._event(conn, auth, order["instance_id"], "commerce.checkout_changed", order_id=order_id,
                        action="cancelled_before_dispatch", purpose=order["purpose"])
            return self._order_projection(conn, self._owned_resource(conn, auth, "mock_commerce_order", order_id))

    def _paypal_checkout(self, auth, order_id, outcome, *, provider_order_id=None,
                         renew_approval=False, quote_digest=None):
        with self.db.reader() as conn:
            existing = self._owned_resource(conn, auth, "mock_commerce_order", order_id)
            if existing["payment_transport"] != "paypal_sandbox":
                raise AiclError("invalid_transition", "This order uses its original payment provider.")
            if outcome == "complete" and (not provider_order_id or provider_order_id != existing["provider_order_id"]):
                raise self._provider_error("provider_mismatch", "The PayPal return does not match this checkout.")
            if existing["state"] == "completed":
                return self._order_projection(conn, existing)
        self._require_http_port("paypal_sandbox")
        attempt_id = _new_id()
        with self.db.transaction() as conn:
            order = self._owned_resource(conn, auth, "mock_commerce_order", order_id)
            if outcome == "complete" and (not provider_order_id or provider_order_id != order["provider_order_id"]):
                raise self._provider_error("provider_mismatch", "The PayPal return does not match this checkout.")
            if order["state"] == "completed":
                return self._order_projection(conn, order)
            if order["state"] == "cancelled":
                raise AiclError("invalid_transition", "This checkout was cancelled before payment.")
            if order["payment_phase"] in ("inflight", "unknown", "pending"):
                self._reject(order["instance_id"], "reconciliation_pending",
                             "Check the PayPal payment status before continuing this checkout.")
            self._check_paypal_merchant(order)
            purchase = self._owned_resource(conn, auth, "mock_commerce_purchase", order["purchase_id"]) if order["purchase_id"] else None
            if outcome == "start" and order["provider_order_id"]:
                self._check_payment_binding(order, purchase)
                return self._order_projection(conn, order)
            inst = self._owned_instance(conn, auth, order["instance_id"])
            renewed = False
            if purchase:
                if outcome == "complete" and purchase["expires_at"] <= to_iso(self.clock.now()):
                    # A PayPal checkout can outlast the proposal TTL. Keep its
                    # existing hold and immutable provider payload; the owner may
                    # explicitly renew authority for this exact capture only.
                    if renew_approval is not True:
                        self._reject(inst["id"], "paypal_approval_expired",
                                     "Review and approve this exact purchase again before finishing its PayPal payment.")
                    if (purchase["state"] not in _ACTIVE_PURCHASES or purchase["approved_at"] is None
                            or quote_digest != purchase["quote_digest"]):
                        self._reject(inst["id"], "confirmation_mismatch", "Renewal must match the original approved purchase.")
                    quote = self._trusted_purchase_quote(purchase)
                    self._controls(conn, auth, inst["id"])
                    self._purchase_policy(conn, inst["id"])
                    renewed = True
                else:
                    quote = self._valid_purchase(conn, auth, purchase)
                if purchase["approved_at"] is None:
                    self._reject(inst["id"], "confirmation_required", "Exact owner purchase approval is required before checkout.")
                if (order["purpose"], order["merchant_id"], order["amount_minor"], order["currency"]) != (
                        "agent_purchase", quote["merchant_id"], quote["amount_minor"], quote["currency"]):
                    self._reject(inst["id"], "confirmation_mismatch", "The checkout does not match the approved quote.")
            elif inst["lifecycle"] == "archived":
                self._reject(inst["id"], "instance_not_active", "An archived agent cannot receive new service credit.")
            binding = self._check_payment_binding(order, purchase)
            if renewed:
                self._event(conn, auth, inst["id"], "commerce.purchase_changed", purchase_id=purchase["id"],
                            order_id=order_id, action="sandbox_approval_renewed",
                            payload_digest_prefix=purchase["quote_digest"][:12])
            now = to_iso(self.clock.now())
            conn.execute("UPDATE mock_commerce_order SET payment_binding_json = ?, payment_phase = 'inflight', "
                         "payment_attempt_id = ?, state = 'pending', updated_at = ? WHERE id = ?",
                         (binding, attempt_id, now, order_id))
            if purchase:
                conn.execute("UPDATE mock_commerce_purchase SET state = 'payment_pending', updated_at = ? WHERE id = ?", (now, purchase["id"]))
                conn.execute("UPDATE mock_commerce_run SET state = 'payment_pending', updated_at = ? WHERE id = ?", (now, purchase["run_id"]))
            self._event(conn, auth, order["instance_id"], "commerce.checkout_changed", order_id=order_id,
                        action="paypal_" + outcome + "_dispatch", purpose=order["purpose"])
            dispatched = dict(self._owned_resource(conn, auth, "mock_commerce_order", order_id))
        return self._dispatch_payment(auth, dispatched, attempt_id, outcome=outcome)

    def _provider_error(self, reason, message):
        return AiclError(reason, message)

    def _require_http_port(self, transport="http_mock"):
        if transport not in ("http_mock", "paypal_sandbox") or self.payment_transport != transport:
            raise self._provider_error("provider_unavailable", "Restart with this order's original payment provider to continue.")
        if getattr(self.db._local, "conn", None) is not None:
            raise self._provider_error("provider_unavailable", "Payment requests must run outside a database transaction.")

    def _payment_binding(self, order, purchase):
        binding = {key: order[key] for key in ("id", "instance_id", "purpose", "amount_minor", "currency", "merchant_id", "purchase_id")} | {
            "quote_digest": purchase["quote_digest"] if purchase else None,
            "approved_at": purchase["approved_at"] if purchase else None,
            "quote_json": purchase["quote_json"] if purchase else None,
        }
        if order["buyer_id"] is not None:
            binding["buyer_id"] = order["buyer_id"]
        # Keep legacy mock bindings byte-identical. Sandbox adds explicit provider
        # and payee binding so a configuration change cannot redirect a payment.
        if order["payment_transport"] == "paypal_sandbox":
            binding.update(payment_transport=order["payment_transport"], provider_merchant_id=order["provider_merchant_id"])
        return binding

    def _check_payment_binding(self, order, purchase):
        binding = _canonical(self._payment_binding(order, purchase))
        if order["payment_binding_json"] and order["payment_binding_json"] != binding:
            raise self._provider_error("provider_mismatch", "The payment binding changed; no credit or delivery was recorded.")
        return binding

    def _validate_provider_response(self, order, result):
        expected = {"reference": order["id"], **{key: order[key] for key in
                    ("purpose", "amount_minor", "currency", "merchant_id")}}
        if order["buyer_id"] is not None:
            expected["buyer_id"] = order["buyer_id"]
        if order["payment_transport"] == "paypal_sandbox":
            expected["provider_merchant_id"] = order["provider_merchant_id"]
        if (not isinstance(result, dict) or type(result.get("amount_minor")) is not int
                or any(result.get(key) != value for key, value in expected.items())
                or result.get("status") not in ("CREATED", "APPROVED", "PENDING", "COMPLETED", "CANCELLED")):
            raise self._provider_error("provider_mismatch", "The payment provider response does not match this order.")
        provider_id = result.get("provider_order_id")
        if (not isinstance(provider_id, str) or not provider_id or len(provider_id) > 128
                or (order["provider_order_id"] and order["provider_order_id"] != provider_id)):
            raise self._provider_error("provider_mismatch", "The payment provider order identity does not match.")
        if order["payment_transport"] == "paypal_sandbox":
            approval_url = result.get("approval_url")
            if approval_url is not None:
                try:
                    parsed = urlsplit(approval_url)
                    valid = (parsed.scheme == "https" and parsed.netloc == "www.sandbox.paypal.com"
                             and parsed.path == "/checkoutnow" and not parsed.fragment
                             and parse_qs(parsed.query).get("token") == [provider_id])
                except (TypeError, ValueError):
                    valid = False
                if not valid:
                    raise self._provider_error("provider_mismatch", "The PayPal approval URL does not match this Sandbox order.")
            if result["status"] == "CREATED" and not approval_url:
                raise self._provider_error("provider_mismatch", "The PayPal approval URL is missing.")
        if result["status"] == "COMPLETED":
            capture_id = result.get("capture_id")
            if not isinstance(capture_id, str) or not capture_id or len(capture_id) > 128:
                raise self._provider_error("provider_mismatch", "The payment provider capture identity is invalid.")

    def _mark_payment_unknown(self, auth, order_id, attempt_id):
        with self.db.transaction() as conn:
            order = self._owned_resource(conn, auth, "mock_commerce_order", order_id)
            if order["state"] not in ("completed", "cancelled") and order["payment_attempt_id"] == attempt_id:
                conn.execute("UPDATE mock_commerce_order SET payment_phase = 'unknown', updated_at = ? WHERE id = ?",
                             (to_iso(self.clock.now()), order_id))
                self._event(conn, auth, order["instance_id"], "commerce.checkout_changed", order_id=order_id,
                            action="provider_unknown", purpose=order["purpose"])

    def _dispatch_payment(self, auth, order, attempt_id, *, outcome=None):
        # The claim and immutable binding above must already be committed. Neither
        # execute nor status is allowed to hold the application's SQLite write lock.
        try:
            result = self.payments.status(order) if outcome is None else self.payments.execute(order, outcome)
            self._validate_provider_response(order, result)
            return self._settle_provider_response(auth, order["id"], attempt_id, result)
        except Exception as error:
            self._mark_payment_unknown(auth, order["id"], attempt_id)
            if isinstance(error, AiclError):
                raise
            raise self._provider_error("provider_unavailable", "The payment response is unknown. Check payment status before retrying.") from error

    def _http_checkout(self, auth, order_id, outcome, *, expected_buyer_id=None):
        # Replaying a known terminal result does not need the remote service online.
        with self.db.reader() as conn:
            existing = self._owned_resource(conn, auth, "mock_commerce_order", order_id)
            if existing["state"] in ("completed", "cancelled"):
                allowed = "complete" if existing["state"] == "completed" else "cancel"
                if outcome != allowed:
                    raise AiclError("invalid_transition", "A settled payment cannot change its outcome.")
                return self._order_projection(conn, existing)
        self._require_http_port()
        attempt_id = _new_id()
        with self.db.transaction() as conn:
            order = self._owned_resource(conn, auth, "mock_commerce_order", order_id)
            if order["state"] in ("completed", "cancelled"):
                allowed = "complete" if order["state"] == "completed" else "cancel"
                if outcome != allowed:
                    raise AiclError("invalid_transition", "A settled payment cannot change its outcome.")
                return self._order_projection(conn, order)
            if order["payment_phase"] in ("inflight", "unknown"):
                self._reject(order["instance_id"], "reconciliation_pending",
                             "The payment outcome is unknown. Check payment status before attempting another action.")
            purchase = self._owned_resource(conn, auth, "mock_commerce_purchase", order["purchase_id"]) if order["purchase_id"] else None
            if outcome != "cancel":
                self._require_payment_buyer(order, expected_buyer_id)
                inst = self._owned_instance(conn, auth, order["instance_id"])
                if purchase:
                    quote = self._valid_purchase(conn, auth, purchase)
                    if purchase["approved_at"] is None:
                        self._reject(inst["id"], "confirmation_required", "Exact owner purchase approval is required before checkout.")
                    if (order["purpose"], order["merchant_id"], order["amount_minor"], order["currency"]) != (
                            "agent_purchase", quote["merchant_id"], quote["amount_minor"], quote["currency"]):
                        self._reject(inst["id"], "confirmation_mismatch", "The checkout does not match the approved quote.")
                elif inst["lifecycle"] == "archived":
                    self._reject(inst["id"], "instance_not_active", "An archived agent cannot receive new service credit.")
            binding = self._check_payment_binding(order, purchase)
            now = to_iso(self.clock.now())
            conn.execute("UPDATE mock_commerce_order SET payment_binding_json = ?, payment_phase = 'inflight', "
                         "payment_attempt_id = ?, state = 'pending', updated_at = ? WHERE id = ?",
                         (binding, attempt_id, now, order_id))
            if purchase:
                conn.execute("UPDATE mock_commerce_purchase SET state = 'payment_pending', updated_at = ? WHERE id = ?", (now, purchase["id"]))
                conn.execute("UPDATE mock_commerce_run SET state = 'payment_pending', updated_at = ? WHERE id = ?", (now, purchase["run_id"]))
            self._event(conn, auth, order["instance_id"], "commerce.checkout_changed", order_id=order_id,
                        action="provider_dispatch", purpose=order["purpose"])
            dispatched = dict(self._owned_resource(conn, auth, "mock_commerce_order", order_id))
        return self._dispatch_payment(auth, dispatched, attempt_id, outcome=outcome)

    @_mutation
    def reconcile_payment(self, auth: AuthContext, order_id: str) -> dict:
        # Status retrieval never grants a new payment or resumes agent inference.
        with self.db.reader() as conn:
            order = self._owned_resource(conn, auth, "mock_commerce_order", order_id)
            if order["state"] in ("completed", "cancelled"):
                return self._order_projection(conn, order)
            if order["payment_transport"] not in ("http_mock", "paypal_sandbox"):
                raise AiclError("invalid_transition", "This inline fixture has no remote payment to reconcile.")
            transport = order["payment_transport"]
        self._require_http_port(transport)
        attempt_id = _new_id()
        with self.db.transaction() as conn:
            order = self._owned_resource(conn, auth, "mock_commerce_order", order_id)
            if order["state"] in ("completed", "cancelled"):
                return self._order_projection(conn, order)
            if order["payment_phase"] == "not_started" or not order["payment_binding_json"]:
                raise AiclError("invalid_transition", "Approve checkout before checking the payment status.")
            purchase = self._owned_resource(conn, auth, "mock_commerce_purchase", order["purchase_id"]) if order["purchase_id"] else None
            self._check_payment_binding(order, purchase)
            if order["payment_transport"] == "paypal_sandbox":
                self._check_paypal_merchant(order)
            conn.execute("UPDATE mock_commerce_order SET payment_attempt_id = ?, payment_phase = 'inflight', updated_at = ? WHERE id = ?",
                         (attempt_id, to_iso(self.clock.now()), order_id))
            dispatched = dict(self._owned_resource(conn, auth, "mock_commerce_order", order_id))
        return self._dispatch_payment(auth, dispatched, attempt_id)

    def _settle_provider_response(self, auth, order_id, attempt_id, result):
        with self.db.transaction() as conn:
            order = self._owned_resource(conn, auth, "mock_commerce_order", order_id)
            self._validate_provider_response(order, result)
            purchase = self._owned_resource(conn, auth, "mock_commerce_purchase", order["purchase_id"]) if order["purchase_id"] else None
            self._check_payment_binding(order, purchase)
            if order["state"] in ("completed", "cancelled"):
                # A stale status response cannot undo a concurrently recorded result.
                return self._order_projection(conn, order)
            duplicate = conn.execute("SELECT id FROM mock_commerce_order WHERE provider_order_id = ? AND id != ?",
                                     (result["provider_order_id"], order_id)).fetchone()
            if duplicate:
                raise self._provider_error("provider_mismatch", "The payment provider order was already bound to a different checkout.")
            if result["status"] not in ("COMPLETED", "CANCELLED") and order["payment_attempt_id"] != attempt_id:
                return self._order_projection(conn, order)
            now = to_iso(self.clock.now())
            if result["status"] == "COMPLETED":
                # Dispatch-time controls authorized this payment. Pausing the agent
                # afterward must not hide a capture or drop its receipt; resume still gates.
                self._complete_order(conn, auth, order, purchase, capture=result)
                phase = "completed"
            elif result["status"] == "CANCELLED":
                if purchase:
                    self._end_purchase(conn, auth, purchase, "cancelled", verified_cancel=True)
                else:
                    conn.execute("UPDATE mock_commerce_order SET state = 'cancelled', updated_at = ? WHERE id = ?", (now, order_id))
                phase = "cancelled"
            else:
                phase = "pending" if result["status"] == "PENDING" else "created"
            conn.execute("UPDATE mock_commerce_order SET provider_order_id = ?, payment_phase = ?, "
                         "paypal_approval_url = COALESCE(?, paypal_approval_url), updated_at = ? WHERE id = ?",
                         (result["provider_order_id"], phase, result.get("approval_url") if order["payment_transport"] == "paypal_sandbox" else None,
                          now, order_id))
            self._event(conn, auth, order["instance_id"], "commerce.checkout_changed", order_id=order_id,
                        action="provider_" + phase, purpose=order["purpose"])
            return self._order_projection(conn, self._owned_resource(conn, auth, "mock_commerce_order", order_id))

    def _complete_order(self, conn, auth, order, purchase, capture=None):
        if capture is None:
            # A pre-existing inline order never changes transports when the server restarts.
            adapter = self.payments if self.payment_transport == "inline_fixture" else MockPaymentAdapter()
            capture = adapter.capture(dict(order))
        if not isinstance(capture, dict) or (capture.get("status"), capture.get("amount_minor"), capture.get("currency"), capture.get("merchant_id")) != (
                "COMPLETED", order["amount_minor"], order["currency"], order["merchant_id"]):
            self._reject(order["instance_id"], "confirmation_mismatch", "The local capture does not match this order.")
        capture_id = capture.get("capture_id")
        if not isinstance(capture_id, str) or not capture_id or len(capture_id) > 128:
            self._reject(order["instance_id"], "confirmation_mismatch", "The local capture identity is invalid.")
        if conn.execute("SELECT 1 FROM mock_commerce_receipt WHERE capture_id = ?", (capture_id,)).fetchone():
            raise AiclError("conflict", "This simulated capture was already recorded for another order.")
        now, receipt_id = to_iso(self.clock.now()), _new_id()
        conn.execute("INSERT INTO mock_commerce_receipt (id,order_id,instance_id,purpose,capture_id,merchant_id,merchant_name,amount_minor,currency,created_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", (receipt_id, order["id"], order["instance_id"], order["purpose"], capture["capture_id"],
                     order["merchant_id"], order["merchant_name"], order["amount_minor"], order["currency"], now))
        if order["purpose"] == "service_topup":
            if purchase is not None or order["merchant_id"] != HABITAT_MERCHANT_ID:
                raise AiclError("conflict", "Funding purpose does not match the Habitat merchant.")
            conn.execute("INSERT INTO mock_commerce_ledger (id,instance_id,kind,delta_micro_usd,reference,receipt_id,created_at) "
                         "VALUES (?,?,'service_topup',?,?,?,?)", (_new_id(), order["instance_id"], order["amount_minor"] * 10_000,
                         "topup:" + order["id"], receipt_id, now))
        else:
            quote = self._trusted_purchase_quote(purchase) if purchase else None
            if (quote is None or order["purpose"] != "agent_purchase" or purchase["approved_at"] is None
                    or (order["merchant_id"], order["amount_minor"], order["currency"], order["instance_id"], order["purchase_id"]) !=
                       (quote["merchant_id"], quote["amount_minor"], quote["currency"], purchase["instance_id"], purchase["id"])):
                raise AiclError("conflict", "Purchase purpose does not match the integrated demo seller.")
            fulfillment = self.merchant.fulfill(quote["offer_id"])
            conn.execute("UPDATE mock_commerce_purchase SET state = 'paid', quota_state = 'spent', fulfillment_json = ?, updated_at = ? WHERE id = ?",
                         (_canonical(fulfillment), now, purchase["id"]))
            conn.execute("UPDATE mock_commerce_run SET state = 'ready_to_resume', updated_at = ? WHERE id = ?", (now, purchase["run_id"]))
        conn.execute("UPDATE mock_commerce_order SET state = 'completed', updated_at = ? WHERE id = ?", (now, order["id"]))
        self._event(conn, auth, order["instance_id"], "commerce.payment_recorded", order_id=order["id"], receipt_id=receipt_id,
                    purpose=order["purpose"], amount_minor=order["amount_minor"])

    def _charge_inference(self, conn, auth, instance_id, run_id, step):
        self._controls(conn, auth, instance_id)
        prices = self._price_info(conn)
        estimate = prices["estimated_step_micro_usd"]
        if estimate is None:
            self._reject(instance_id, "price_unavailable", "A current price table is required before inference.")
        if self._balance(conn, instance_id) < estimate:
            self._reject(instance_id, "credit_insufficient", "Service credit must cover the full bounded inference estimate.")
        try:
            hold = self.budget.reserve(conn, instance_id, f"commerce:{run_id}:{step}", ESTIMATE)
        except AiclError as error:
            error.commerce_instance_id = instance_id
            raise
        if self._balance(conn, instance_id) < hold.inference_micro_usd + hold.compute_micro_usd:
            self._reject(instance_id, "credit_insufficient", "Service credit must cover the reserved inference estimate.")
        usage = self.budget.settle(conn, hold.id, MEASURED_USAGE)
        charge = usage.inference_micro_usd + usage.compute_micro_usd
        if charge > hold.inference_micro_usd + hold.compute_micro_usd:
            raise AiclError("conflict", "Mock model exceeded the reserved bound.")
        now = to_iso(self.clock.now())
        conn.execute("INSERT INTO mock_commerce_ledger (id,instance_id,kind,delta_micro_usd,reference,hold_id,created_at) "
                     "VALUES (?,?,'inference_usage',?,?,?,?)", (_new_id(), instance_id, -charge, f"inference:{run_id}:{step}", hold.id, now))
        conn.execute("UPDATE mock_commerce_run SET inference_cost_micro_usd = inference_cost_micro_usd + ?, "
                     "input_tokens = input_tokens + ?, output_tokens = output_tokens + ?, updated_at = ? WHERE id = ?",
                     (charge, MEASURED_USAGE.inference_input_tokens, MEASURED_USAGE.inference_output_tokens, now, run_id))
        self._event(conn, auth, instance_id, "budget.reserved", hold_id=hold.id,
                    micro_usd=hold.inference_micro_usd + hold.compute_micro_usd, price_table_version=hold.price_table_version)
        self._event(conn, auth, instance_id, "budget.settled", hold_id=hold.id, micro_usd=charge, price_table_version=hold.price_table_version)

    @_mutation
    def start_run(self, auth: AuthContext, instance_id: str, request_id: str, brief: dict | None = None) -> dict:
        self._request_id(request_id)
        normalized = self._brief(brief)
        with self.db.transaction() as conn:
            self._owned_instance(conn, auth, instance_id)
            existing = conn.execute("SELECT * FROM mock_commerce_run WHERE tenant_id = ? AND request_id = ?", (auth.tenant_id, request_id)).fetchone()
            if existing:
                if (existing["instance_id"] != instance_id or existing["owner_id"] != auth.owner_id
                        or json.loads(existing["brief_json"]) != normalized):
                    raise AiclError("conflict", "request_id was already used for a different task or agent.")
                return self._run_projection(conn, existing)
            active = conn.execute("SELECT id FROM mock_commerce_run WHERE instance_id = ? "
                                  "AND state IN (?,?,?,?) LIMIT 1", (instance_id, *_ACTIVE_RUNS)).fetchone()
            if active:
                self._reject(instance_id, "task_in_progress", "Finish or close the current task before starting another.")
            unresolved = conn.execute("SELECT * FROM mock_commerce_order WHERE instance_id = ? AND state = 'pending'", (instance_id,)).fetchall()
            if any(dict(order).get("payment_phase") in ("inflight", "unknown") for order in unresolved):
                self._reject(instance_id, "payment_unresolved", "Check the unresolved payment status before starting another task.")
            self._controls(conn, auth, instance_id)
            self._purchase_policy(conn, instance_id, additional=CATALOG["amount_minor"])
            run_id, purchase_id, now = _new_id(), _new_id(), to_iso(self.clock.now())
            self._account(conn, instance_id)
            conn.execute("INSERT INTO mock_commerce_run (id,instance_id,tenant_id,owner_id,request_id,state,brief_json,created_at,updated_at) "
                         "VALUES (?,?,?,?,?,'awaiting_approval',?,?,?)", (run_id, instance_id, auth.tenant_id, auth.owner_id, request_id,
                                                                       _canonical(normalized), now, now))
            self._charge_inference(conn, auth, instance_id, run_id, "plan")
            quote, expires = self._quote(instance_id), to_iso(self.clock.now() + timedelta(minutes=15))
            digest = hashlib.sha256(_canonical({"instance_id": instance_id, "run_id": run_id, "quote": quote, "expires_at": expires}).encode()).hexdigest()
            conn.execute("INSERT INTO mock_commerce_purchase (id,run_id,instance_id,tenant_id,owner_id,quote_json,quote_digest,amount_minor,state,quota_state,"
                         "expires_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,'awaiting_approval','held',?,?,?)",
                         (purchase_id, run_id, instance_id, auth.tenant_id, auth.owner_id, _canonical(quote), digest, quote["amount_minor"], expires, now, now))
            self._event(conn, auth, instance_id, "commerce.run_started", run_id=run_id, purchase_id=purchase_id, amount_minor=quote["amount_minor"])
            return self._run_projection(conn, self._owned_resource(conn, auth, "mock_commerce_run", run_id))

    def _start_workflow_run(self, conn, auth, instance_id, request_id, brief, *, purchase_required=False, charge=True, offer_id=None,
                            action="scheduled_fixture"):
        """Internal scheduled-fixture primitive, inside the workflow's transaction.

        Distinct configured jobs may wait independently. The workflow owns occurrence
        deduplication; this stable commerce request also prevents duplicate charges.
        All controls, quote authorization, holds and accounting remain shared.
        """
        self._request_id(request_id)
        normalized = self._brief(brief)
        self._owned_instance(conn, auth, instance_id)
        if offer_id is not None and not purchase_required:
            raise AiclError("validation_failed", "A purchase offer requires a purchase request.")
        quote = self._quote(instance_id, offer_id) if purchase_required else None
        existing = conn.execute("SELECT * FROM mock_commerce_run WHERE tenant_id = ? AND request_id = ?",
                                (auth.tenant_id, request_id)).fetchone()
        if existing:
            purchase = conn.execute("SELECT quote_json FROM mock_commerce_purchase WHERE run_id = ?", (existing["id"],)).fetchone()
            if (existing["instance_id"] != instance_id or existing["owner_id"] != auth.owner_id
                    or json.loads(existing["brief_json"]) != normalized
                    or (json.loads(purchase["quote_json"]) if purchase else None) != quote):
                raise AiclError("conflict", "Workflow occurrence already belongs to another job.")
            return self._run_projection(conn, existing)
        self._controls(conn, auth, instance_id)
        if purchase_required:
            self._purchase_policy(conn, instance_id, additional=quote["amount_minor"])
        now, run_id = to_iso(self.clock.now()), _new_id()
        self._account(conn, instance_id)
        conn.execute("INSERT INTO mock_commerce_run (id,instance_id,tenant_id,owner_id,request_id,state,brief_json,created_at,updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?)", (run_id, instance_id, auth.tenant_id, auth.owner_id, request_id,
                     "awaiting_approval" if purchase_required else "completed", _canonical(normalized), now, now))
        if charge:
            self._charge_inference(conn, auth, instance_id, run_id, "plan")
        purchase_id = None
        if purchase_required:
            purchase_id = _new_id()
            expires = to_iso(self.clock.now() + timedelta(minutes=15))
            digest = hashlib.sha256(_canonical({"instance_id": instance_id, "run_id": run_id, "quote": quote, "expires_at": expires}).encode()).hexdigest()
            conn.execute("INSERT INTO mock_commerce_purchase (id,run_id,instance_id,tenant_id,owner_id,quote_json,quote_digest,amount_minor,state,quota_state,"
                         "expires_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,'awaiting_approval','held',?,?,?)",
                         (purchase_id, run_id, instance_id, auth.tenant_id, auth.owner_id, _canonical(quote), digest, quote["amount_minor"], expires, now, now))
        self._event(conn, auth, instance_id, "commerce.run_started", run_id=run_id, purchase_id=purchase_id, action=action)
        return self._run_projection(conn, self._owned_resource(conn, auth, "mock_commerce_run", run_id))

    @_mutation
    def resume_run(self, auth: AuthContext, run_id: str) -> dict:
        with self.db.transaction() as conn:
            run = self._owned_resource(conn, auth, "mock_commerce_run", run_id)
            if conn.execute("SELECT 1 FROM mock_workflow_run WHERE commerce_run_id=?", (run_id,)).fetchone():
                raise AiclError("invalid_transition", "Use the scheduled job's purchase continuation choice to resume this work.")
            if run["state"] == "completed":
                return self._run_projection(conn, run)
            purchase = conn.execute("SELECT * FROM mock_commerce_purchase WHERE run_id = ?", (run_id,)).fetchone()
            if run["state"] != "ready_to_resume" or not purchase or purchase["state"] != "paid" or not purchase["fulfillment_json"]:
                self._reject(run["instance_id"], "confirmation_required", "Complete the approved purchase checkout and receive the asset before resuming.")
            inst = self._controls(conn, auth, run["instance_id"])
            self._charge_inference(conn, auth, run["instance_id"], run_id, "finish")
            output = self.inference.finish(inst["name"], json.loads(purchase["fulfillment_json"]), json.loads(run["brief_json"]))
            conn.execute("UPDATE mock_commerce_run SET state = 'completed', output = ?, updated_at = ? WHERE id = ?",
                         (output, to_iso(self.clock.now()), run_id))
            self._event(conn, auth, run["instance_id"], "commerce.run_completed", run_id=run_id, purchase_id=purchase["id"])
            return self._run_projection(conn, self._owned_resource(conn, auth, "mock_commerce_run", run_id))
