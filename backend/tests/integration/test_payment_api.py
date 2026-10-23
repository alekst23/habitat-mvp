"""The separate HTTP mock keeps provider truth through retries and process restarts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from aicl.commerce.payment_api import create_payment_app
from aicl.commerce.payment_client import HttpMockPaymentAdapter
from aicl.control.errors import AiclError


TOKEN = "local-test-token-not-a-paypal-credential"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def order(purpose="service_topup"):
    return {"id": str(uuid.uuid4()), "purpose": purpose, "currency": "USD",
            "amount_minor": 500 if purpose == "service_topup" else 100,
            "merchant_id": "habitat-demo" if purpose == "service_topup" else "demo-template-shop"}


def payload(local):
    return {"intent": "CAPTURE", "purchase_units": [{"reference_id": local["id"],
            "custom_id": local["purpose"], "payee": {"merchant_id": local["merchant_id"]},
            "amount": {"currency_code": local["currency"],
                       "value": f"{local['amount_minor'] // 100}.{local['amount_minor'] % 100:02d}"}}]}


class LocalApiTransport(httpx.BaseTransport):
    """Exercise HTTP serialization without opening a live listener in tests."""

    def __init__(self, app, *, lose_capture_once=False):
        self.server = TestClient(app)
        self.lose_capture_once = lose_capture_once

    def handle_request(self, request):
        response = self.server.request(request.method, request.url.path,
                                       headers=dict(request.headers), content=request.content)
        if request.url.path.endswith("/capture") and self.lose_capture_once:
            self.lose_capture_once = False
            raise httpx.ReadTimeout("response lost after provider committed", request=request)
        return httpx.Response(response.status_code, headers=response.headers, content=response.content,
                              request=request)


def adapter(db, **transport_options):
    return HttpMockPaymentAdapter("http://127.0.0.1:4174", TOKEN,
        transport=LocalApiTransport(create_payment_app(db, TOKEN), **transport_options))


def test_provider_requires_auth_exact_order_and_approval_then_capture_is_durable(tmp_path):
    db = tmp_path / "provider.db"
    api = TestClient(create_payment_app(db, TOKEN))
    assert api.get("/health").json() == {"status": "ok", "mode": "http_mock"}
    local = order()
    body = payload(local)
    assert api.post("/v2/checkout/orders", json=body).status_code == 401
    headers = {**AUTH, "PayPal-Request-Id": local["id"]}
    created = api.post("/v2/checkout/orders", headers=headers, json=body)
    assert created.status_code == 201
    remote = created.json()
    path = f"/v2/checkout/orders/{remote['id']}"
    assert api.get(path).status_code == 401
    assert api.post(path + "/capture", headers=AUTH).status_code == 409
    assert api.post("/v2/checkout/orders", headers=headers, json=body).json() == remote
    changed = payload({**local, "amount_minor": 600})
    assert api.post("/v2/checkout/orders", headers=headers, json=changed).status_code == 409
    assert api.post(f"/mock/orders/{remote['id']}/approve", headers=AUTH).json()["status"] == "APPROVED"
    captured = api.post(path + "/capture", headers=AUTH).json()
    capture = captured["purchase_units"][0]["payments"]["captures"][0]
    assert captured["status"] == "COMPLETED" and capture["status"] == "COMPLETED"
    restarted = TestClient(create_payment_app(db, TOKEN))
    with ThreadPoolExecutor(max_workers=2) as pool:
        retries = list(pool.map(lambda _: restarted.post(path + "/capture", headers=AUTH).json(), range(2)))
    assert retries == [captured, captured]
    assert restarted.get(path, headers=AUTH).json() == captured
    assert restarted.post(f"/mock/orders/{remote['id']}/cancel", headers=AUTH).status_code == 409
    invalid = order()
    invalid_body = payload(invalid)
    invalid_body["purchase_units"][0]["amount"]["value"] = "0.001"
    assert api.post("/v2/checkout/orders", headers={**AUTH, "PayPal-Request-Id": invalid["id"]},
                    json=invalid_body).status_code == 422
    invalid_body = payload({**invalid, "merchant_id": "demo-template-shop"})
    assert api.post("/v2/checkout/orders", headers={**AUTH, "PayPal-Request-Id": invalid["id"]},
                    json=invalid_body).status_code == 422


def test_client_keeps_pending_uncaptured_and_cancellation_terminal_for_both_merchants(tmp_path):
    client = adapter(tmp_path / "provider.db")
    topup, purchase = order(), order("agent_purchase")
    pending = client.execute(topup, "pending")
    assert pending["status"] == "PENDING" and pending.get("capture_id") is None
    assert client.status(topup) == pending
    cancelled = client.execute(purchase, "cancel")
    assert cancelled["status"] == "CANCELLED" and cancelled.get("capture_id") is None
    assert client.execute(purchase, "complete") == cancelled
    completed = client.execute(topup, "complete")
    assert completed["status"] == "COMPLETED" and completed["capture_id"]
    assert {key: completed[key] for key in ("amount_minor", "currency", "merchant_id", "purpose")} == {
        key: topup[key] for key in ("amount_minor", "currency", "merchant_id", "purpose")}
    assert completed["reference"] == topup["id"]
    assert adapter(tmp_path / "provider.db").execute(topup, "complete") == completed


def test_ad_platform_payment_is_exact_durable_and_cannot_receive_service_funding(tmp_path):
    db = tmp_path / "ad-provider.db"
    client = adapter(db)
    ad_order = {**order("agent_purchase"), "merchant_id": "launchpad-ads-demo", "amount_minor": 3000}
    completed = client.execute(ad_order, "complete")
    assert completed["status"] == "COMPLETED"
    assert completed["merchant_id"] == "launchpad-ads-demo" and completed["amount_minor"] == 3000
    assert adapter(db).execute(ad_order, "complete") == completed
    api = TestClient(create_payment_app(db, TOKEN))
    for invalid in (
        {**order(), "merchant_id": "launchpad-ads-demo"},
        {**order("agent_purchase"), "merchant_id": "unknown-ad-seller"},
    ):
        with pytest.raises(AiclError) as rejected:
            client.execute(invalid, "complete")
        assert rejected.value.error == "provider_mismatch"
        response = api.post("/v2/checkout/orders", headers={**AUTH, "PayPal-Request-Id": invalid["id"]},
                            json=payload(invalid))
        assert response.status_code == 422


def test_capture_response_loss_recovers_same_receipt_without_duplicate_capture(tmp_path):
    db = tmp_path / "provider.db"
    client = adapter(db, lose_capture_once=True)
    local = order("agent_purchase")
    with pytest.raises(AiclError) as error:
        client.execute(local, "complete")
    assert error.value.error == "provider_unavailable"
    restarted = adapter(db)
    recovered = restarted.status(local)
    assert recovered["status"] == "COMPLETED" and recovered["capture_id"]
    assert restarted.execute(local, "complete") == recovered


def test_client_rejects_remote_urls_redirects_and_mismatched_provider_truth(tmp_path):
    for url in ("https://127.0.0.1:4174", "http://localhost:4174", "http://example.test:4174",
                "http://user:secret@127.0.0.1:4174", "http://127.0.0.1:4174/prefix",
                "http://127.0.0.1:4174/", "http://127.0.0.1:4174\n"):
        with pytest.raises(ValueError):
            HttpMockPaymentAdapter(url, TOKEN)
    local = order()
    truth = TestClient(create_payment_app(tmp_path / "provider.db", TOKEN)).post(
        "/v2/checkout/orders", headers={**AUTH, "PayPal-Request-Id": local["id"]}, json=payload(local)).json()
    truth["purchase_units"][0]["payee"]["merchant_id"] = "demo-template-shop"
    client = HttpMockPaymentAdapter("http://127.0.0.1:4174", TOKEN,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=truth)))
    with pytest.raises(AiclError) as mismatch:
        client.status(local)
    assert mismatch.value.error == "provider_mismatch"
    destinations = []

    def redirect(request):
        destinations.append(str(request.url))
        return httpx.Response(307, headers={"Location": "https://example.test/steal"})

    client = HttpMockPaymentAdapter("http://127.0.0.1:4174", TOKEN,
                                    transport=httpx.MockTransport(redirect))
    with pytest.raises(AiclError) as unavailable:
        client.execute(local, "complete")
    assert unavailable.value.error == "provider_unavailable"
    assert destinations == ["http://127.0.0.1:4174/v2/checkout/orders"]


def test_remembered_buyer_is_bound_to_one_order_and_never_grants_future_approval(tmp_path):
    db = tmp_path / "provider.db"
    api = TestClient(create_payment_app(db, TOKEN))
    local = {**order(), "buyer_id": "demo-buyer"}
    body = {**payload(local), "mock_buyer_id": local["buyer_id"]}
    headers = {**AUTH, "PayPal-Request-Id": local["id"]}
    created = api.post("/v2/checkout/orders", headers=headers, json=body)
    assert created.status_code == 201
    remote = created.json()
    assert remote["mock_buyer_id"] == "demo-buyer"
    assert api.post("/v2/checkout/orders", headers=headers, json=body).json() == remote
    changed = {**body, "mock_buyer_id": "demo-buyer-alt"}
    assert api.post("/v2/checkout/orders", headers=headers, json=changed).status_code == 409
    assert api.post("/v2/checkout/orders", headers=headers, json=payload(local)).status_code == 409
    assert api.post("/v2/checkout/orders", headers=headers,
                    json={**body, "mock_buyer_id": "unrecognized-buyer"}).status_code == 422
    completed = adapter(db).execute(local, "complete")
    assert completed["buyer_id"] == "demo-buyer" and completed["capture_id"]
    assert adapter(db).status(local) == completed

    # Remembering the buyer does not approve even another payment to the same merchant.
    next_order = {**order(), "buyer_id": "demo-buyer"}
    next_remote = api.post("/v2/checkout/orders", headers={**AUTH, "PayPal-Request-Id": next_order["id"]},
                          json={**payload(next_order), "mock_buyer_id": "demo-buyer"}).json()
    assert api.post(f"/v2/checkout/orders/{next_remote['id']}/capture", headers=AUTH).status_code == 409


def test_buyer_response_mismatch_is_rejected_before_provider_action(tmp_path):
    local = {**order("agent_purchase"), "buyer_id": "demo-buyer"}
    for reported_buyer in ("demo-buyer-alt", None):
        calls = []
        truth = {**payload(local), "id": f"MOCK-ORDER-{uuid.uuid4()}", "status": "CREATED"}
        if reported_buyer is not None:
            truth["mock_buyer_id"] = reported_buyer

        def response(request):
            calls.append(request.url.path)
            return httpx.Response(200, json=truth)

        client = HttpMockPaymentAdapter("http://127.0.0.1:4174", TOKEN,
                                        transport=httpx.MockTransport(response))
        with pytest.raises(AiclError) as mismatch:
            client.execute(local, "complete")
        assert mismatch.value.error == "provider_mismatch"
        assert calls == ["/v2/checkout/orders"]


def test_legacy_order_payload_remains_byte_identical_and_recovers_without_buyer(tmp_path):
    db = tmp_path / "provider.db"
    app = create_payment_app(db, TOKEN)
    local = order()
    legacy = json.dumps(payload(local), sort_keys=True, separators=(",", ":"))
    provider_id, capture_id = f"MOCK-ORDER-{uuid.uuid4()}", f"MOCK-CAPTURE-{uuid.uuid4()}"
    # Seed the exact representation written before remembered buyers existed.
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO payment_order(id,request_id,reference,payload_json,status,capture_id) "
                     "VALUES(?,?,?,?,?,?)", (provider_id, local["id"], local["id"], legacy,
                                             "COMPLETED", capture_id))
    client = adapter(db)
    assert client._payload({**local, "buyer_id": None}) == payload(local)
    recovered = client.status({**local, "buyer_id": None})
    assert recovered["provider_order_id"] == provider_id and recovered["capture_id"] == capture_id
    assert "buyer_id" not in recovered
    api = TestClient(app)
    replay = api.post("/v2/checkout/orders", headers={**AUTH, "PayPal-Request-Id": local["id"]},
                      json={**payload(local), "mock_buyer_id": None})
    assert replay.status_code == 200 and "mock_buyer_id" not in replay.json()
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT payload_json FROM payment_order").fetchone()[0] == legacy
