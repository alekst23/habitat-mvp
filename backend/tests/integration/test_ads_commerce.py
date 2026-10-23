"""Trusted campaign purchases retain approval, quota and payment boundaries."""

import hashlib

import pytest

from aicl.commerce.adapters import MockMerchantAdapter
from aicl.commerce.service import MockCommerceService, _canonical
from aicl.control.errors import AiclError
from test_mock_commerce import denied, error, ready
from test_payment_workflow import PaymentPort


BRIEF = {"product_name": "PocketPlan", "audience": "Freelancers", "goal": "Test app marketing within a capped budget."}
CAMPAIGN = "pocketplan-campaign-v1"
EXPANSION = "pocketplan-expansion-v1"


def proposal(env, service, auth, instance_id, *, request_id="campaign-plan", offer_id=CAMPAIGN):
    with env.db.transaction() as conn:
        return service._start_workflow_run(conn, auth, instance_id, request_id, BRIEF,
                                           purchase_required=True, offer_id=offer_id)


def test_campaign_exact_approval_pays_once_but_does_not_claim_ad_delivery(build_env):
    env, service, auth, inst, _ = ready(build_env, limit_minor=4500)
    run = proposal(env, service, auth, inst.id)
    purchase = run["purchase"]
    quote = purchase["quote"]
    assert quote["merchant_name"] == "LaunchPad Ads" and quote["amount_minor"] == 3000
    assert quote["campaign"]["duration_days"] == 3 and quote["campaign"]["daily_cap_minor"] == 1000
    assert quote["campaign"]["destination_url"] == "https://pocketplan.example/app"
    assert len(quote["campaign"]["creative"]) == 2
    assert purchase["campaign"] == quote["campaign"]
    assert purchase["fulfillment"] is None
    denied("confirmation_mismatch", lambda: service.decide_purchase(auth, purchase["id"], "approve", "0" * 64))

    approved = service.decide_purchase(auth, purchase["id"], "approve", purchase["quote_digest"])
    order = service.order(auth, approved["order_id"])
    assert order["quote"] == quote and order["campaign"] == quote["campaign"]
    assert order["fulfillment"] is None
    assert service.dashboard(auth, inst.id)["policy"]["held_minor"] == 3000
    paid = service.checkout(auth, order["id"], "complete")
    assert service.checkout(auth, order["id"], "complete") == paid
    assert paid["fulfillment"]["kind"] == "prepaid_ad_credit"
    assert paid["fulfillment"]["prepaid_minor"] == 3000
    assert paid["fulfillment"]["delivery_status"] == "not_started"
    assert "license" not in paid["fulfillment"]
    assert "impressions" not in paid["fulfillment"]
    dashboard = service.dashboard(auth, inst.id)
    assert dashboard["policy"]["spent_minor"] == 3000 and dashboard["policy"]["held_minor"] == 0
    assert dashboard["balance_micro_usd"] == 5_000_000 - run["inference_cost_micro_usd"]
    assert len(dashboard["receipts"]) == 2  # Funding and one campaign payment.


def test_campaign_replay_preserves_offer_and_no_duplicate_charge_or_hold(build_env):
    env, service, auth, inst, _ = ready(build_env, limit_minor=4500)
    run = proposal(env, service, auth, inst.id)
    before = service.dashboard(auth, inst.id)
    assert proposal(env, service, auth, inst.id) == run
    error("conflict", lambda: proposal(env, service, auth, inst.id, offer_id=EXPANSION))
    assert service.dashboard(auth, inst.id)["balance_micro_usd"] == before["balance_micro_usd"]
    assert service.dashboard(auth, inst.id)["policy"] == before["policy"]


@pytest.mark.parametrize("field,value", [("destination_url", "https://other.example/app"),
                                         ("targeting", "Everyone"), ("daily_cap_minor", 2000)])
def test_campaign_tampering_is_rejected_even_with_recomputed_digest(build_env, field, value):
    env, service, auth, inst, _ = ready(build_env, limit_minor=4500)
    purchase = proposal(env, service, auth, inst.id)["purchase"]
    quote = purchase["quote"]
    quote["campaign"][field] = value
    digest = hashlib.sha256(_canonical({"instance_id": inst.id, "run_id": purchase["run_id"],
                                       "quote": quote, "expires_at": purchase["expires_at"]}).encode()).hexdigest()
    with env.db.transaction() as conn:
        conn.execute("UPDATE mock_commerce_purchase SET quote_json=?,quote_digest=? WHERE id=?",
                     (_canonical(quote), digest, purchase["id"]))
    denied("confirmation_mismatch", lambda: service.decide_purchase(auth, purchase["id"], "approve", digest))
    assert service.purchase(auth, purchase["id"])["order_id"] is None


def test_campaign_limits_unknown_offers_and_owner_scope_fail_before_charge(build_env):
    env, service, auth, inst, _ = ready(build_env, limit_minor=2999)
    denied("purchase_limit_exceeded", lambda: proposal(env, service, auth, inst.id))
    error("validation_failed", lambda: proposal(env, service, auth, inst.id, offer_id="untrusted-seller"))
    assert service.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000
    assert service.dashboard(auth, inst.id)["runs"] == []
    service.configure(auth, inst.id, True, 4500, 2)
    purchase = proposal(env, service, auth, inst.id)["purchase"]
    stranger, _ = env.new_instance()
    error("not_found", lambda: service.purchase(stranger, purchase["id"]))
    error("not_found", lambda: service.decide_purchase(stranger, purchase["id"], "approve", purchase["quote_digest"]))


def test_expansion_decline_is_independent_of_paid_original_campaign(build_env):
    env, service, auth, inst, _ = ready(build_env, limit_minor=4500)
    campaign = proposal(env, service, auth, inst.id)["purchase"]
    order = service.decide_purchase(auth, campaign["id"], "approve", campaign["quote_digest"])
    service.checkout(auth, order["order_id"], "complete")
    expansion = proposal(env, service, auth, inst.id, request_id="optional-expansion", offer_id=EXPANSION)["purchase"]
    assert expansion["quote"]["amount_minor"] == 1500
    assert expansion["campaign"]["daily_cap_minor"] == 500
    service.decide_purchase(auth, expansion["id"], "decline", expansion["quote_digest"])
    assert service.purchase(auth, campaign["id"])["state"] == "paid"
    assert service.purchase(auth, expansion["id"])["fulfillment"] is None
    policy = service.dashboard(auth, inst.id)["policy"]
    assert policy["spent_minor"] == 3000 and policy["held_minor"] == 0 and policy["available_minor"] == 1500


def test_ad_payment_response_mismatch_retains_hold_then_reconciles_once(build_env):
    env, _, auth, inst, _ = ready(build_env, limit_minor=4500)
    port = PaymentPort(env.db)
    service = MockCommerceService(env.db, env.clock, payments=port)
    purchase = proposal(env, service, auth, inst.id)["purchase"]
    approved = service.decide_purchase(auth, purchase["id"], "approve", purchase["quote_digest"])
    port.mismatch = {"merchant_id": "demo-template-shop"}
    error("provider_mismatch", lambda: service.checkout(auth, approved["order_id"], "complete"))
    assert service.purchase(auth, purchase["id"])["fulfillment"] is None
    assert service.dashboard(auth, inst.id)["policy"]["held_minor"] == 3000
    port.mismatch = None
    paid = service.reconcile_payment(auth, approved["order_id"])
    assert paid["fulfillment"]["prepaid_minor"] == 3000
    assert service.reconcile_payment(auth, approved["order_id"]) == paid
    assert len(port.calls) == 2


def test_legacy_offer_remains_unchanged_and_quotes_cannot_mutate_fixtures(build_env):
    merchant = MockMerchantAdapter()
    mutated = merchant.quote(CAMPAIGN)
    mutated["campaign"]["creative"][0]["headline"] = "Untrusted replacement"
    assert merchant.quote(CAMPAIGN)["campaign"]["creative"][0]["headline"] != "Untrusted replacement"
    env, service, auth, inst, _ = ready(build_env)
    purchase = proposal(env, service, auth, inst.id, offer_id=None)["purchase"]
    assert purchase["quote"]["offer_id"] == "launch-kit-template-v1"
    assert purchase["quote"]["amount_minor"] == 100 and purchase["campaign"] is None
    approved = service.decide_purchase(auth, purchase["id"], "approve", purchase["quote_digest"])
    paid = service.checkout(auth, approved["order_id"], "complete")
    assert "license" in paid["fulfillment"] and "kind" not in paid["fulfillment"]
