"""Owner browser routes use real Sandbox adapter protocol against a fake HTTP server."""
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from aicl.app import FIXTURE_CSRF_TOKEN, FIXTURE_OWNERS, create_app
from aicl.commerce import paypal_sandbox
from aicl.commerce.factory import commerce_service
from aicl.commerce.service import MockCommerceService
from aicl.control.auth import AuthContext
from aicl.control.instances import Limits
from aicl.creation.operations import SqliteInstanceOperations
from aicl.creation.service import read_instance_snapshot
from aicl.settings import Settings
from test_mock_commerce import approved_purchase
from test_paypal_sandbox_adapter import Sandbox, APPROVAL_URL, REMOTE_ID, CAPTURE_ID
from test_paypal_sandbox_config import SERVICE, PURCHASE


@pytest.fixture
def sandbox_web(base_env, monkeypatch):
    server = Sandbox()
    adapter = paypal_sandbox.PayPalSandboxAdapter
    monkeypatch.setattr(paypal_sandbox, "PayPalSandboxAdapter",
                        lambda **kwargs: adapter(**kwargs, transport=httpx.MockTransport(server.handle)))
    settings = Settings.from_env({**base_env, **SERVICE, **PURCHASE,
                                  "AICL_ENVIRONMENT": "test", "AICL_TEST_MODE": "1"})
    app = create_app(settings)
    owner_id = FIXTURE_OWNERS["owner-a"]
    auth = AuthContext(owner_id, owner_id, "s-owner-a", datetime(2100, 1, 1, tzinfo=timezone.utc))
    with TestClient(app) as owner, TestClient(app) as other, TestClient(app) as anonymous:
        assert owner.post("/__test__/seed-session", json={"fixture": "owner-a"}).status_code == 200
        assert other.post("/__test__/seed-session", json={"fixture": "owner-b"}).status_code == 200
        headers = {"origin": settings.public_base_url}
        created = owner.post("/app-tools/create_instance", headers={**headers, "x-csrf-token": FIXTURE_CSRF_TOKEN},
            json={"idempotency_key": "wiz_" + "8" * 32, "template_id": "default", "name": "Sandbox checkout",
                  "instructions": "Check owner-approved payment routing.", "enabled_capabilities": ["inference"]})
        assert created.status_code == 200, created.text
        yield SimpleNamespace(app=app, owner=owner, other=other, anonymous=anonymous, headers=headers,
                              auth=auth, instance_id=created.json()["instance"]["id"], server=server,
                              service=commerce_service(app.state.ctx))


def post(web, path, **fields):
    return web.owner.post(path, headers=web.headers, data={"csrf_token": FIXTURE_CSRF_TOKEN, **fields},
                          follow_redirects=False)


def topup(web, request_id="sandbox-page-funding"):
    response = post(web, f"/instances/{web.instance_id}/commerce/topups", amount_minor="500", request_id=request_id)
    assert response.status_code == 303
    path = response.headers["location"]
    assert path.startswith("/commerce/orders/")
    return path, path.rsplit("/", 1)[1]


def test_sandbox_checkout_redirect_return_security_and_exactly_once_capture(sandbox_web):
    web = sandbox_web
    path, order_id = topup(web)
    page = web.owner.get(path)
    assert page.status_code == 200
    assert 'alt="PayPal"' in page.text and "PayPal Sandbox" in page.text
    assert path + "/paypal-start" in page.text and "Continue to PayPal" in page.text
    assert "Choose an account" not in page.text and 'name="buyer_id"' not in page.text
    assert 'name="outcome"' not in page.text

    fields = {"csrf_token": FIXTURE_CSRF_TOKEN}
    for action in ("paypal-start", "paypal-complete", "paypal-cancel", "reconcile"):
        target = path + "/" + action
        assert web.owner.post(target, headers=web.headers, follow_redirects=False).status_code == 403
        assert web.other.post(target, headers=web.headers, data=fields, follow_redirects=False).status_code == 404
        assert web.anonymous.post(target, headers=web.headers, data=fields, follow_redirects=False).status_code == 401
    # Neither mock endpoint can manufacture a Sandbox payment or a fictional buyer.
    for action, values in (("checkout", {"outcome": "complete", "buyer_id": "demo-buyer"}),
                           ("buyer", {"buyer_id": "demo-buyer"})):
        rejected = post(web, path + "/" + action, **values)
        assert rejected.status_code == 303 and "failure=" in rejected.headers["location"]
    assert not web.server.requests
    assert web.service.order(web.auth, order_id)["buyer_id"] is None

    started = post(web, path + "/paypal-start")
    assert started.status_code == 303 and started.headers["location"] == APPROVAL_URL
    before_count = len(web.server.requests)
    before_order = web.service.order(web.auth, order_id)
    returned = path + "/paypal-return?token=" + REMOTE_ID
    assert web.other.get(returned, follow_redirects=False).status_code == 404
    assert web.anonymous.get(returned, follow_redirects=False).headers["location"] == "/"
    wrong = web.owner.get(path + "/paypal-return?token=OTHER", follow_redirects=False)
    assert wrong.status_code == 303 and "paypal_return_mismatch" in wrong.headers["location"]
    with web.app.state.ctx.db.reader() as conn:
        before_database = list(conn.iterdump())
    valid = web.owner.get(returned)
    assert valid.status_code == 200 and "Returned from PayPal" in valid.text
    assert "Finish approved payment" in valid.text and f'value="{REMOTE_ID}"' in valid.text
    with web.app.state.ctx.db.reader() as conn:
        assert list(conn.iterdump()) == before_database
    assert len(web.server.requests) == before_count
    assert web.service.order(web.auth, order_id) == before_order
    assert web.service.dashboard(web.auth, web.instance_id)["balance_micro_usd"] == 0

    forged = post(web, path + "/paypal-complete", provider_order_id="OTHER")
    assert "failure=" in forged.headers["location"] and len(web.server.requests) == before_count
    # Approval comes from PayPal, not the return URL; a premature POST cannot pay.
    premature = post(web, path + "/paypal-complete", provider_order_id=REMOTE_ID)
    assert premature.status_code == 303 and "failure=" in premature.headers["location"]
    assert not any(request.url.path.endswith("/capture") for request in web.server.requests)
    assert web.service.dashboard(web.auth, web.instance_id)["balance_micro_usd"] == 0
    post(web, path + "/reconcile")
    web.server.approve()
    # An approved return is still read-only, until the owner's CSRF-protected POST.
    assert web.owner.get(returned).status_code == 200
    assert web.service.dashboard(web.auth, web.instance_id)["balance_micro_usd"] == 0
    paid = post(web, path + "/paypal-complete", provider_order_id=REMOTE_ID)
    assert paid.status_code == 303 and paid.headers["location"].endswith("#setup")
    receipt = web.owner.get(path)
    assert "Payment completed" in receipt.text and CAPTURE_ID in receipt.text
    post(web, path + "/paypal-complete", provider_order_id=REMOTE_ID)
    post(web, path + "/reconcile")
    dashboard = web.service.dashboard(web.auth, web.instance_id)
    assert dashboard["balance_micro_usd"] == 5_000_000 and len(dashboard["receipts"]) == 1
    assert len([request for request in web.server.requests if request.url.path.endswith("/capture")]) == 1


def approved_sandbox_purchase(web):
    ctx = web.app.state.ctx
    ops = SqliteInstanceOperations(ctx.db, ctx.clock)
    version = lambda: read_instance_snapshot(web.auth, web.instance_id).version
    ops.set_limits(web.auth, web.instance_id, version(), Limits(1_000_000, 10_000_000, 1_000_000, 10_000_000))
    ops.set_lifecycle(web.auth, web.instance_id, version(), "activate")
    web.service.configure(web.auth, web.instance_id, True, 200, 1)
    # Existing fixture funds remain fixture history; only this new purchase uses Sandbox.
    inline = MockCommerceService(ctx.db, ctx.clock)
    funding = inline.create_topup(web.auth, web.instance_id, 500, "prior-fixture-credit")
    inline.select_payment_buyer(web.auth, funding["id"], "demo-buyer")
    inline.checkout(web.auth, funding["id"], "complete")
    return approved_purchase(web.service, web.auth, web.instance_id)


def test_sandbox_cancel_return_keeps_purchase_hold_and_never_fakes_provider_cancellation(sandbox_web):
    web = sandbox_web
    _, purchase, order = approved_sandbox_purchase(web)
    path = "/commerce/orders/" + order["id"]
    started = post(web, path + "/paypal-start")
    assert started.headers["location"] == APPROVAL_URL
    before_order = web.service.order(web.auth, order["id"])
    before_count = len(web.server.requests)
    cancelled_return = web.owner.get(path + "/paypal-cancel?token=" + REMOTE_ID)
    assert cancelled_return.status_code == 200 and "Checkout interrupted" in cancelled_return.text
    assert "purchase hold are preserved" in cancelled_return.text
    assert web.service.order(web.auth, order["id"]) == before_order
    assert web.service.dashboard(web.auth, web.instance_id)["policy"]["held_minor"] == 100
    assert post(web, path + "/paypal-cancel").headers["location"] == path
    assert web.service.order(web.auth, order["id"]) == before_order and len(web.server.requests) == before_count
    post(web, path + "/reconcile")
    assert web.service.purchase(web.auth, purchase["id"])["state"] == "payment_pending"
    assert web.service.dashboard(web.auth, web.instance_id)["policy"]["held_minor"] == 100
    assert not any(request.url.path.endswith(("/capture", "/cancel")) for request in web.server.requests)
    # Local cancellation is valid only before this separate order has been dispatched.
    untouched, untouched_id = topup(web, "cancel-before-paypal")
    calls = len(web.server.requests)
    post(web, untouched + "/paypal-cancel")
    assert web.service.order(web.auth, untouched_id)["state"] == "cancelled"
    assert len(web.server.requests) == calls


def test_sandbox_lost_capture_page_recovers_receipt_without_another_capture(sandbox_web):
    web = sandbox_web
    path, order_id = topup(web)
    post(web, path + "/paypal-start")
    web.server.approve()
    web.server.capture_response_loss = True
    def lose_confirmation(document):
        if document["status"] == "COMPLETED":
            raise httpx.ReadTimeout("fixture confirmation unavailable")
        return document
    web.server.mutate_document = lose_confirmation
    uncertain = post(web, path + "/paypal-complete", provider_order_id=REMOTE_ID)
    assert uncertain.status_code == 303 and "failure=" in uncertain.headers["location"]
    page = web.owner.get(uncertain.headers["location"])
    assert "Payment result needs checking" in page.text and "Check payment status" in page.text
    assert "Finish approved payment" not in page.text
    assert web.service.dashboard(web.auth, web.instance_id)["balance_micro_usd"] == 0
    assert web.service.order(web.auth, order_id)["payment_phase"] == "unknown"
    web.server.mutate_document = lambda document: document
    recovered = post(web, path + "/reconcile")
    assert recovered.headers["location"].endswith("#setup")
    assert CAPTURE_ID in web.owner.get(path).text
    assert web.service.dashboard(web.auth, web.instance_id)["balance_micro_usd"] == 5_000_000
    assert len([request for request in web.server.requests if request.url.path.endswith("/capture")]) == 1


def test_expired_paypal_return_requires_explicit_renewal_of_the_exact_purchase(sandbox_web, monkeypatch):
    from datetime import timedelta

    web = sandbox_web
    _, purchase, order = approved_sandbox_purchase(web)
    path = "/commerce/orders/" + order["id"]
    assert post(web, path + "/paypal-start").headers["location"] == APPROVAL_URL
    web.server.approve()
    later = web.app.state.ctx.clock.now() + timedelta(minutes=16)
    monkeypatch.setattr(web.app.state.ctx.clock, "now", lambda: later)
    calls = len(web.server.requests)
    page = web.owner.get(path + "/paypal-return?token=" + REMOTE_ID)
    assert page.status_code == 200 and "Renew your purchase approval" in page.text
    assert 'type="checkbox" name="renew_approval" value="true" required' in page.text
    assert f'name="quote_digest" value="{purchase["quote_digest"]}"' in page.text
    assert f'name="provider_order_id" value="{REMOTE_ID}"' in page.text
    assert "Renew approval &amp; finish payment" in page.text
    assert len(web.server.requests) == calls
    missing = post(web, path + "/paypal-complete", provider_order_id=REMOTE_ID,
                   quote_digest=purchase["quote_digest"])
    assert "paypal_approval_expired" in missing.headers["location"]
    wrong = post(web, path + "/paypal-complete", provider_order_id=REMOTE_ID,
                 renew_approval="true", quote_digest="different-quote")
    assert "confirmation_mismatch" in wrong.headers["location"]
    assert len(web.server.requests) == calls
    assert web.service.dashboard(web.auth, web.instance_id)["policy"]["held_minor"] == 100
    fields = {"provider_order_id": REMOTE_ID, "renew_approval": "true", "quote_digest": purchase["quote_digest"]}
    confirmed = post(web, path + "/paypal-complete", **fields)
    assert confirmed.status_code == 303 and "failure=" not in confirmed.headers["location"]
    post(web, path + "/paypal-complete", **fields)
    paid = web.service.order(web.auth, order["id"])
    assert paid["state"] == "completed" and paid["provider_order_id"] == REMOTE_ID
    assert CAPTURE_ID in web.owner.get(path).text
    assert len([request for request in web.server.requests if request.url.path.endswith("/capture")]) == 1
    with web.app.state.ctx.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM mock_commerce_receipt WHERE order_id = ?", (order["id"],)).fetchone()[0] == 1
