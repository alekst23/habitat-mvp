"""Pure, deterministic local fixtures; deliberately no network or credential support.

These are not PayPal Sandbox adapters and cannot capture, infer or fulfill externally.
The small template below is original fixture content dedicated to CC0-1.0.
"""

from __future__ import annotations

from copy import deepcopy

from aicl.control.budget import Estimate, MeasuredUsage

MODE = "local_simulation"
TOPUP_AMOUNTS_MINOR = (500, 1000, 2000)
HABITAT_MERCHANT_ID = "habitat-demo"
HABITAT_MERCHANT_NAME = "Habitat Demo"
MODEL = "local-scripted-model"
TASK_SCENARIO = "marketing_launch_kit"
DEFAULT_TASK_BRIEF = {
    "product_name": "Habitat",
    "audience": "Owners exploring controlled agents for everyday work",
    "goal": "Introduce Habitat and invite owners to try the local demo",
}
ESTIMATE = Estimate(1000, 1000, 0)
MEASURED_USAGE = MeasuredUsage(500, 500, 0)
CATALOG = {
    "merchant_id": "demo-template-shop",
    "merchant_name": "Demo Template Shop",
    "offer_id": "launch-kit-template-v1",
    "version": "1",
    "item_name": "Marketing launch kit template",
    "quantity": 1,
    "amount_minor": 100,
    "currency": "USD",
    "license": "CC0-1.0 — original local demo fixture",
}
TEMPLATE = (
    "Launch kit template v1\n"
    "1. Promise: describe one concrete benefit for the audience.\n"
    "2. Proof: show the product performing one useful task.\n"
    "3. Invitation: give the audience one clear next step.\n"
)

# Closed, versioned fixtures: callers choose an offer ID, never supply seller,
# targeting, creative, price or payment destination. Approval binds the full quote.
ADS_MERCHANT_ID = "launchpad-ads-demo"
ADS_MERCHANT_NAME = "LaunchPad Ads"
_CAMPAIGN_COMMON = {
    "product_name": "PocketPlan",
    "platform": ADS_MERCHANT_NAME,
    "destination_url": "https://pocketplan.example/app",
    "duration_days": 3,
    "start_condition": "After payment and the owner's campaign continuation choice",
    "metrics": ["Impressions", "Clicks", "Attributed installs", "Cost per install"],
    "result_caveat": "A capped test measures interest; clicks and installs are not guaranteed.",
}
ADS_CATALOG = {
    "pocketplan-campaign-v1": {
        "merchant_id": ADS_MERCHANT_ID, "merchant_name": ADS_MERCHANT_NAME,
        "offer_id": "pocketplan-campaign-v1", "version": "1",
        "item_name": "PocketPlan freelancer campaign — 3-day test",
        "quantity": 1, "amount_minor": 3000, "currency": "USD",
        "fulfillment_kind": "prepaid_ad_credit",
        "campaign": {
            **_CAMPAIGN_COMMON,
            "campaign_name": "PocketPlan freelancer acquisition test",
            "targeting": "English-speaking freelancers interested in productivity and daily planning",
            "total_cap_minor": 3000, "daily_cap_minor": 1000,
            "creative": [
                {"headline": "A clearer day for independent work",
                 "body": "Turn your freelance to-do list into a focused daily plan with PocketPlan.",
                 "call_to_action": "Explore PocketPlan"},
                {"headline": "Plan the work that matters today",
                 "body": "PocketPlan helps freelancers organize priorities for the day ahead.",
                 "call_to_action": "Explore PocketPlan"},
            ],
            "rationale": "Test whether PocketPlan's daily-planning message attracts app installs from its initial freelancer audience.",
            "evidence": [
                "The owner-supplied product brief names freelancers as the initial audience.",
                "The campaign plan supplies two ad variants and the exact app destination for review.",
                "No paid-campaign baseline exists yet; this $30 test establishes one within a $10 daily cap.",
            ],
            "alternative": "Publish the prepared creative through the developer's existing organic channels before buying distribution.",
            "decline_outcome": "Keep the campaign plan and ad creative for revision; no paid campaign starts.",
        },
    },
    "pocketplan-expansion-v1": {
        "merchant_id": ADS_MERCHANT_ID, "merchant_name": ADS_MERCHANT_NAME,
        "offer_id": "pocketplan-expansion-v1", "version": "1",
        "item_name": "PocketPlan broader-audience campaign — optional test",
        "quantity": 1, "amount_minor": 1500, "currency": "USD",
        "fulfillment_kind": "prepaid_ad_credit",
        "campaign": {
            **_CAMPAIGN_COMMON,
            "campaign_name": "PocketPlan broader productivity audience test",
            "targeting": "English-speaking independent professionals interested in productivity and daily planning",
            "total_cap_minor": 1500, "daily_cap_minor": 500,
            "creative": [
                {"headline": "Make room for your priorities",
                 "body": "Build a focused daily plan for independent work with PocketPlan.",
                 "call_to_action": "Explore PocketPlan"},
            ],
            "rationale": "Compare a broader productivity audience with the original freelancer segment using a separately capped test.",
            "evidence": [
                "The campaign plan identifies independent professionals as a separate audience hypothesis.",
                "The original freelancer campaign is a separate $30 commitment; this request adds up to $15.",
                "This optional expansion does not claim the original test has established a winning audience.",
            ],
            "alternative": "Wait for the original three-day test to finish before considering a broader audience.",
            "decline_outcome": "Do not create the expansion campaign; keep the original campaign and its reporting unchanged.",
        },
    },
}


class MockPaymentAdapter:
    """A completion is pure fixture data; persistence is the service's transaction."""

    def capture(self, order: dict) -> dict:
        return {"capture_id": f"LOCAL-CAPTURE-{order['id']}", "amount_minor": order["amount_minor"],
                "currency": order["currency"], "merchant_id": order["merchant_id"], "status": "COMPLETED"}


class MockMerchantAdapter:
    def quote(self, offer_id: str | None = None) -> dict:
        if offer_id is None or offer_id == CATALOG["offer_id"]:
            return dict(CATALOG)
        if not isinstance(offer_id, str) or offer_id not in ADS_CATALOG:
            raise ValueError("unknown local offer")
        return deepcopy(ADS_CATALOG[offer_id])

    def fulfill(self, offer_id: str) -> dict:
        if offer_id in ADS_CATALOG:
            offer = self.quote(offer_id)
            return {"name": offer["item_name"], "kind": "prepaid_ad_credit", "offer_id": offer_id,
                    "prepaid_minor": offer["amount_minor"], "currency": offer["currency"],
                    "delivery_status": "not_started", "campaign": offer["campaign"],
                    "content": "Advertising funds prepaid. Campaign delivery and results are recorded separately."}
        if offer_id != CATALOG["offer_id"]:
            raise ValueError("unknown local offer")
        return {"name": CATALOG["item_name"], "content": TEMPLATE, "license": CATALOG["license"]}


class MockInferenceAdapter:
    """Scripted output and usage, bounded by ESTIMATE. This makes no model call."""

    def finish(self, agent_name: str, fulfillment: dict, brief: dict) -> str:
        product, audience, goal = (brief[key] for key in ("product_name", "audience", "goal"))
        return (
            f"Launch kit for {product}\nPrepared by {agent_name}\n\n"
            f"Audience: {audience}\nOwner goal: {goal}\n\n"
            f"Promise: introduce {product} to {audience} with one clear next step.\n"
            f"Proof: record a short walkthrough of {product} performing one useful task for this audience.\n"
            f"Invitation: {goal}\n\n"
            f"Launch post: Meet {product}, created for {audience}. See the walkthrough, explore the "
            f"example, and take the next step: {goal}\n\n"
            f"Three-step checklist: record a walkthrough of {product}; share the launch post with "
            f"{audience}; gather feedback against this goal: {goal}\n\n"
            f"Purchased template: {fulfillment['name']}\n"
            f"License: {fulfillment['license']}\n\n"
            f"Source structure used:\n{fulfillment['content']}"
        )
