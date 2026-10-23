"""Exercise the actual Sandbox HTTP protocol with no network or real credentials."""

from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import uuid

import httpx
import pytest

from aicl.commerce.paypal_sandbox import PayPalSandboxAdapter
from aicl.control.errors import AiclError


SERVICE_MERCHANT = "HABITAT1234567"
PURCHASE_MERCHANT = "SELLER12345678"
REMOTE_ID = "5O190127TN364715T"
CAPTURE_ID = "3C679366HH908993F"
APPROVAL_URL = f"https://www.sandbox.paypal.com/checkoutnow?token={REMOTE_ID}"


def local_order(purpose="service_topup", **changes):
    return {"id": str(uuid.uuid4()), "purpose": purpose, "currency": "USD", "amount_minor": 500,
            "merchant_id": "habitat-demo" if purpose == "service_topup" else "launchpad-ads-demo",
            "created_at": datetime.now(timezone.utc).isoformat(), **changes}


class Sandbox:
    """Stateful PayPal-shaped server, including approval outside Habitat."""

    def __init__(self):
        self.requests = []
        self.orders = {}
        self.created = None
        self.document = None
        self.create_response_loss = False
        self.capture_response_loss = False
        self.fail_capture = False
        self.pending_capture = False
        self.minimal_create = False
        self.mutate_document = lambda value: value

    def handle(self, request):
        self.requests.append(request)
        assert request.url.scheme == "https" and request.url.host == "api-m.sandbox.paypal.com"
        if request.url.path == "/v1/oauth2/token":
            assert request.method == "POST"
            assert request.headers["authorization"].startswith("Basic ")
            assert request.content == b"grant_type=client_credentials"
            return httpx.Response(200, json={"access_token": "fixture-bearer-not-real", "token_type": "Bearer", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer fixture-bearer-not-real"
        assert request.headers["prefer"] == "return=representation"
        if request.url.path == "/v2/checkout/orders":
            assert request.method == "POST"
            payload = json.loads(request.content)
            request_id = request.headers["paypal-request-id"]
            if request_id not in self.orders:
                self.created = payload
                self.document = {"id": REMOTE_ID, "status": "PAYER_ACTION_REQUIRED", "intent": "CAPTURE",
                                 "purchase_units": deepcopy(payload["purchase_units"]),
                                 "links": [{"rel": "payer-action", "method": "GET", "href": APPROVAL_URL}]}
                self.orders[request_id] = self.document
            else:
                assert payload == self.created
            if self.create_response_loss:
                self.create_response_loss = False
                raise httpx.ReadTimeout("lost create response, do not expose this body", request=request)
            if self.minimal_create:
                return httpx.Response(201, json={key: self.document[key] for key in ("id", "status", "links")})
            return httpx.Response(201, json=self.mutate_document(deepcopy(self.document)))
        if request.url.path == f"/v2/checkout/orders/{REMOTE_ID}":
            assert request.method == "GET"
            return httpx.Response(200, json=self.mutate_document(deepcopy(self.document)))
        if request.url.path == f"/v2/checkout/orders/{REMOTE_ID}/capture":
            assert request.method == "POST" and self.document["status"] == "APPROVED"
            assert json.loads(request.content) == {}
            if self.fail_capture:
                raise httpx.ReadTimeout("no capture response", request=request)
            self.document["status"] = "COMPLETED"
            self.document["links"] = []
            self.document["purchase_units"][0]["payments"] = {"captures": [{
                "id": CAPTURE_ID, "status": "PENDING" if self.pending_capture else "COMPLETED",
                "amount": deepcopy(self.document["purchase_units"][0]["amount"]),
            }]}
            if self.capture_response_loss:
                self.capture_response_loss = False
                raise httpx.ReadTimeout("lost capture response", request=request)
            return httpx.Response(201, json={"id": REMOTE_ID, "status": "COMPLETED"})
        raise AssertionError(f"Unexpected method/path: {request.method} {request.url.path}")

    def approve(self):
        self.document["status"] = "APPROVED"


def adapter(server, **overrides):
    return PayPalSandboxAdapter(**{
        "client_id": "service-client", "client_secret": "service-secret", "merchant_id": SERVICE_MERCHANT,
        "public_base_url": "http://127.0.0.1:4173", "purchase_client_id": "seller-client",
        "purchase_client_secret": "seller-secret", "purchase_merchant_id": PURCHASE_MERCHANT,
        "transport": httpx.MockTransport(server.handle), **overrides,
    })


def bound(local, result):
    return {**local, "provider_order_id": result["provider_order_id"],
            "provider_merchant_id": result["provider_merchant_id"]}


def test_oauth_create_external_approval_capture_and_replay_verify_authoritative_receipt():
    server, order = Sandbox(), local_order()
    client = adapter(server)
    started = client.execute(order, "start")
    assert started == {"provider_order_id": REMOTE_ID, "provider_merchant_id": SERVICE_MERCHANT,
                       "status": "CREATED", "reference": order["id"], "purpose": order["purpose"],
                       "amount_minor": 500, "currency": "USD", "merchant_id": "habitat-demo", "approval_url": APPROVAL_URL}
    context = server.created["payment_source"]["paypal"]["experience_context"]
    assert context == {"return_url": f"http://127.0.0.1:4173/commerce/orders/{order['id']}/paypal-return",
                       "cancel_url": f"http://127.0.0.1:4173/commerce/orders/{order['id']}/paypal-cancel",
                       "landing_page": "LOGIN", "user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING"}
    assert server.created["purchase_units"][0]["payee"] == {"merchant_id": SERVICE_MERCHANT}
    assert "mock_buyer_id" not in server.created
    order = bound(order, started)
    with pytest.raises(AiclError, match="invalid_transition"):
        client.execute(order, "complete")
    assert not any(request.url.path.endswith("/capture") for request in server.requests)
    server.approve()
    completed = client.execute(order, "complete")
    assert completed["status"] == "COMPLETED" and completed["capture_id"] == CAPTURE_ID
    assert client.execute(order, "complete") == completed
    assert client.status(order) == completed
    assert len([request for request in server.requests if request.url.path.endswith("/capture")]) == 1
    assert len(server.orders) == 1
    creates = [request for request in server.requests if request.url.path == "/v2/checkout/orders"]
    captures = [request for request in server.requests if request.url.path.endswith("/capture")]
    assert creates[0].headers["paypal-request-id"] != captures[0].headers["paypal-request-id"]
    assert all(len(request.headers["paypal-request-id"]) <= 38 for request in [*creates, *captures])
    # OAuth uses the receiving merchant's credentials, never exposes them to payloads.
    assert server.requests[0].headers["authorization"] == "Basic " + base64.b64encode(b"service-client:service-secret").decode()


def test_separate_purchase_seller_credentials_and_bound_payee_are_required():
    server, order = Sandbox(), local_order("agent_purchase")
    client = adapter(server)
    assert client.supports_purchases and client.merchant_id_for(order) == PURCHASE_MERCHANT
    started = client.execute(order, "start")
    assert started["merchant_id"] == "launchpad-ads-demo" and started["provider_merchant_id"] == PURCHASE_MERCHANT
    assert server.requests[0].headers["authorization"] == "Basic " + base64.b64encode(b"seller-client:seller-secret").decode()
    assert server.created["purchase_units"][0]["payee"] == {"merchant_id": PURCHASE_MERCHANT}
    request_count = len(server.requests)
    with pytest.raises(AiclError, match="provider_mismatch"):
        client.status({**bound(order, started), "provider_merchant_id": SERVICE_MERCHANT})
    without_seller = adapter(server, purchase_client_id="", purchase_client_secret="", purchase_merchant_id="")
    assert without_seller.supports_purchases is False
    with pytest.raises(AiclError, match="provider_not_configured"):
        without_seller.execute(order, "start")
    assert len(server.requests) == request_count


def test_lost_create_response_recovers_same_request_without_approving_or_capturing():
    server, order = Sandbox(), local_order()
    server.create_response_loss = True
    with pytest.raises(AiclError, match="provider_unavailable"):
        adapter(server).execute(order, "start")
    recovered = adapter(server).status(order)
    assert recovered["status"] == "CREATED" and recovered["approval_url"] == APPROVAL_URL
    creates = [request for request in server.requests if request.url.path == "/v2/checkout/orders"]
    assert len(creates) == 2 and len(server.orders) == 1
    assert creates[0].headers["paypal-request-id"] == creates[1].headers["paypal-request-id"]
    assert not any(request.url.path.endswith("/capture") for request in server.requests)


def test_minimal_create_response_requires_authoritative_get_scope_verification():
    server, order = Sandbox(), local_order()
    server.minimal_create = True
    client = adapter(server)
    started = client.execute(order, "start")
    assert started["approval_url"] == APPROVAL_URL and started["status"] == "CREATED"
    assert server.requests[-1].method == "GET" and server.requests[-1].url.path.endswith(REMOTE_ID)
    server.document["purchase_units"][0]["payee"]["merchant_id"] = "WRONGSELLER"
    with pytest.raises(AiclError, match="provider_mismatch"):
        client.status(order)


@pytest.mark.parametrize("created_at", [None, "invalid", "2026-01-01T00:00:00", "2000-01-01T00:00:00+00:00",
                                       (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                                       (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()])
def test_unknown_provider_id_is_never_recreated_outside_safe_window(created_at):
    server = Sandbox()
    with pytest.raises(AiclError, match="provider_unavailable"):
        adapter(server).status(local_order(created_at=created_at))
    assert not server.orders


def test_existing_provider_id_only_gets_status_even_when_local_order_is_old():
    server, order = Sandbox(), local_order()
    client = adapter(server)
    order = bound(order, client.execute(order, "start"))
    assert client.status({**order, "created_at": "2000-01-01T00:00:00Z"})["status"] == "CREATED"
    assert len([request for request in server.requests if request.url.path == "/v2/checkout/orders"]) == 1


@pytest.mark.parametrize("loss", [False, True])
def test_pending_capture_is_never_credited_or_captured_again(loss):
    server, order = Sandbox(), local_order("agent_purchase")
    server.pending_capture, server.capture_response_loss = True, loss
    client = adapter(server)
    order = bound(order, client.execute(order, "start"))
    server.approve()
    pending = client.execute(order, "complete")
    assert pending["status"] == "PENDING" and "capture_id" not in pending
    assert client.status(order) == pending
    assert client.execute(order, "complete") == pending
    assert len([request for request in server.requests if request.url.path.endswith("/capture")]) == 1


def test_lost_capture_response_reconciles_authoritative_get_without_second_charge():
    server, order = Sandbox(), local_order()
    server.capture_response_loss = True
    client = adapter(server)
    order = bound(order, client.execute(order, "start"))
    server.approve()
    completed = client.execute(order, "complete")
    assert completed["status"] == "COMPLETED" and completed["capture_id"] == CAPTURE_ID
    assert client.execute(order, "complete") == completed
    assert len([request for request in server.requests if request.url.path.endswith("/capture")]) == 1


def test_uncertain_capture_stays_unknown_and_retry_uses_same_capture_key():
    server, order = Sandbox(), local_order()
    server.fail_capture = True
    client = adapter(server)
    order = bound(order, client.execute(order, "start"))
    server.approve()
    with pytest.raises(AiclError, match="provider_unavailable"):
        client.execute(order, "complete")
    assert client.status(order)["status"] == "APPROVED"
    server.fail_capture = False
    assert client.execute(order, "complete")["capture_id"] == CAPTURE_ID
    captures = [request for request in server.requests if request.url.path.endswith("/capture")]
    assert len(captures) == 2 and captures[0].headers["paypal-request-id"] == captures[1].headers["paypal-request-id"]


@pytest.mark.parametrize("path,value", [
    (("purchase_units", 0, "payee", "merchant_id"), "UNEXPECTEDSELLER"),
    (("purchase_units", 0, "amount", "value"), "5.001"),
    (("purchase_units", 0, "amount", "value"), "500.00"),
    (("purchase_units", 0, "amount", "currency_code"), "EUR"),
    (("purchase_units", 0, "reference_id"), str(uuid.uuid4())),
    (("purchase_units", 0, "custom_id"), "agent_purchase"),
    (("intent",), "AUTHORIZE"),
    (("id",), "../../evil"),
])
def test_response_mismatches_are_rejected_before_any_capture(path, value):
    server = Sandbox()
    def mutate(document):
        target = document
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        return document
    server.mutate_document = mutate
    with pytest.raises(AiclError, match="provider_mismatch"):
        adapter(server).execute(local_order(), "start")
    assert not any(request.url.path.endswith("/capture") for request in server.requests)


@pytest.mark.parametrize("url", [
    f"https://www.paypal.com/checkoutnow?token={REMOTE_ID}",
    f"https://www.sandbox.paypal.com.evil.test/checkoutnow?token={REMOTE_ID}",
    f"http://www.sandbox.paypal.com/checkoutnow?token={REMOTE_ID}",
    f"https://evil@www.sandbox.paypal.com/checkoutnow?token={REMOTE_ID}",
    f"https://www.sandbox.paypal.com:444/checkoutnow?token={REMOTE_ID}",
    f"https://www.sandbox.paypal.com:443/checkoutnow?token={REMOTE_ID}",
    f"https://www.sandbox.paypal.com/unexpected?token={REMOTE_ID}",
    "https://www.sandbox.paypal.com/checkoutnow?token=ANOTHERORDER",
    f"https://www.sandbox.paypal.com/checkoutnow?token={REMOTE_ID}&token={REMOTE_ID}",
    f"https://www.sandbox.paypal.com/checkoutnow?token={REMOTE_ID}#fragment",
])
def test_approval_redirect_is_bound_to_sandbox_host_and_exact_order_token(url):
    server = Sandbox()
    def mutate(document):
        document["links"][0]["href"] = url
        return document
    server.mutate_document = mutate
    with pytest.raises(AiclError, match="provider_mismatch"):
        adapter(server).execute(local_order(), "start")


@pytest.mark.parametrize("mutation", ["amount", "currency", "capture_status", "missing", "multiple", "order_id"])
def test_only_one_exact_completed_capture_can_be_settled(mutation):
    server, order = Sandbox(), local_order()
    client = adapter(server)
    order = bound(order, client.execute(order, "start"))
    server.approve()
    assert client.execute(order, "complete")["status"] == "COMPLETED"
    def mutate(document):
        captures = document["purchase_units"][0]["payments"]["captures"]
        if mutation == "amount":
            captures[0]["amount"]["value"] = "4.99"
        elif mutation == "currency":
            captures[0]["amount"]["currency_code"] = "EUR"
        elif mutation == "capture_status":
            captures[0]["status"] = "DECLINED"
        elif mutation == "missing":
            captures.clear()
        elif mutation == "multiple":
            captures.append(deepcopy(captures[0]))
        else:
            document["id"] = "WRONGORDER"
        return document
    server.mutate_document = mutate
    with pytest.raises(AiclError, match="provider_mismatch"):
        client.status(order)


def test_cancel_does_not_fabricate_remote_cancellation_or_make_network_call():
    server = Sandbox()
    with pytest.raises(AiclError, match="invalid_transition"):
        adapter(server).execute(local_order(), "cancel")
    assert server.requests == []


@pytest.mark.parametrize("status", [301, 307, 401, 403, 429, 500])
def test_auth_errors_and_redirects_are_sanitized_and_never_followed(status):
    requests = []
    def error(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "https://example.test/steal"},
                              json={"error": "service-secret fixture-bearer-not-real"})
    client = adapter(Sandbox(), transport=httpx.MockTransport(error))
    with pytest.raises(AiclError) as failure:
        client.execute(local_order(), "start")
    assert failure.value.error == "provider_unavailable"
    assert "service-secret" not in failure.value.message and "fixture-bearer" not in failure.value.message
    assert len(requests) == 1 and requests[0].url.host == "api-m.sandbox.paypal.com"


@pytest.mark.parametrize("origin", ["https://user:secret@example.test", "https://example.test/path", "http://example.test",
                                     "https://example.test?x=1", "https://example.test#x", "https://example.test:99999",
                                     "https://example.test\n"])
def test_configuration_requires_clean_callback_origin_and_complete_seller_credentials(origin):
    with pytest.raises(ValueError):
        adapter(Sandbox(), public_base_url=origin)


def test_purchase_settings_are_all_or_none_and_provider_url_cannot_be_configured():
    with pytest.raises(ValueError):
        adapter(Sandbox(), purchase_client_secret="")
    with pytest.raises(TypeError):
        adapter(Sandbox(), base_url="https://api-m.paypal.com")
    with pytest.raises(ValueError):
        adapter(Sandbox(), timeout_seconds=60)


@pytest.mark.parametrize("changes", [{"merchant_id": "launchpad-ads-demo"}, {"currency": "EUR"},
                                     {"amount_minor": True}, {"amount_minor": -1}, {"id": "../invalid"},
                                     {"provider_order_id": "https://evil.test"}])
def test_invalid_local_order_never_reaches_paypal(changes):
    server = Sandbox()
    with pytest.raises(AiclError, match="provider_mismatch"):
        adapter(server).execute(local_order(**changes), "start")
    assert server.requests == []
