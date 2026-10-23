"""Bounded HTTP client for Habitat's local mock; never a PayPal credential client."""

from __future__ import annotations

import re
import uuid

import httpx

from aicl.control.errors import AiclError


_MERCHANTS = {"service_topup": {"habitat-demo"},
              "agent_purchase": {"demo-template-shop", "launchpad-ads-demo"}}
_MOCK_BUYERS = {"demo-buyer", "demo-buyer-alt"}
_STATUSES = {"CREATED", "APPROVED", "PENDING", "COMPLETED", "CANCELLED"}
_ORDER_ID = re.compile(r"^MOCK-ORDER-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CAPTURE_ID = re.compile(r"^MOCK-CAPTURE-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _mismatch():
    return AiclError("provider_mismatch", "The local payment provider did not match this order. Keep the order for reconciliation.")


def _unavailable():
    return AiclError("provider_unavailable", "The local payment provider could not confirm the result. Check this same order again.")


class HttpMockPaymentAdapter:
    """Idempotent creates/actions, explicit approval, and verified provider receipts."""

    transport = "http_mock"

    def __init__(self, base_url: str, token: str, *, timeout_seconds: float = 3.0,
                 transport: httpx.BaseTransport | None = None):
        try:
            url = re.fullmatch(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})", base_url)
            valid = url is not None and int(url[1]) <= 65535
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("mock payment API must be http://127.0.0.1:port with no credentials or path")
        if not isinstance(token, str) or len(token) < 24 or any(char.isspace() for char in token):
            raise ValueError("local mock payment token must contain at least 24 non-whitespace characters")
        if isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= 10:
            raise ValueError("mock payment timeout must be between 0 and 10 seconds")
        self.base_url = base_url
        self._token, self._timeout, self._transport = token, timeout_seconds, transport

    def _session(self):
        return httpx.Client(base_url=self.base_url, timeout=self._timeout, follow_redirects=False,
                            trust_env=False, headers={"Authorization": f"Bearer {self._token}"},
                            transport=self._transport)

    def _payload(self, order):
        try:
            reference, amount, purpose = order["id"], order["amount_minor"], order["purpose"]
            buyer = order.get("buyer_id")
            if (not isinstance(reference, str) or str(uuid.UUID(reference)) != reference
                    or type(amount) is not int or not 1 <= amount <= 100_000_000
                    or order["currency"] != "USD" or order["merchant_id"] not in _MERCHANTS.get(purpose, set())
                    or (buyer is not None and buyer not in _MOCK_BUYERS)):
                raise ValueError
            payload = {"intent": "CAPTURE", "purchase_units": [{"reference_id": reference,
                    "custom_id": purpose, "payee": {"merchant_id": order["merchant_id"]},
                    "amount": {"currency_code": "USD", "value": f"{amount // 100}.{amount % 100:02d}"}}]}
            if buyer is not None:
                payload["mock_buyer_id"] = buyer
            return payload
        except (KeyError, TypeError, ValueError, AttributeError):
            raise _mismatch() from None

    def _normalized(self, document, order, payload):
        try:
            provider_id, status = document["id"], document["status"]
            units = document["purchase_units"]
            if (document["intent"] != "CAPTURE" or not _ORDER_ID.fullmatch(provider_id)
                    or status not in _STATUSES or not isinstance(units, list) or len(units) != 1
                    or document.get("mock_buyer_id") != payload.get("mock_buyer_id")
                    or (order.get("provider_order_id") and order["provider_order_id"] != provider_id)):
                raise ValueError
            unit, expected = units[0], payload["purchase_units"][0]
            if any(unit[key] != expected[key] for key in ("reference_id", "custom_id", "payee", "amount")):
                raise ValueError
            result = {"provider_order_id": provider_id, "status": status, "reference": unit["reference_id"],
                      "purpose": unit["custom_id"], "amount_minor": order["amount_minor"],
                      "currency": order["currency"], "merchant_id": order["merchant_id"]}
            if payload.get("mock_buyer_id") is not None:
                result["buyer_id"] = payload["mock_buyer_id"]
            captures = unit.get("payments", {}).get("captures", [])
            if status == "COMPLETED":
                if not isinstance(captures, list) or len(captures) != 1:
                    raise ValueError
                capture = captures[0]
                if (not _CAPTURE_ID.fullmatch(capture["id"]) or capture["status"] != "COMPLETED"
                        or capture["amount"] != expected["amount"] or capture.get("final_capture") is not True):
                    raise ValueError
                result["capture_id"] = capture["id"]
            elif captures:
                raise ValueError
            return result
        except (KeyError, TypeError, ValueError, AttributeError):
            raise _mismatch() from None

    def _request(self, client, method, path, order, payload, *, create=False):
        try:
            response = client.request(method, path, json=payload if create else None,
                                      headers={"PayPal-Request-Id": order["id"]})
        except httpx.HTTPError:
            raise _unavailable() from None
        if 400 <= response.status_code < 500:
            raise _mismatch()
        if response.status_code not in (200, 201):
            raise _unavailable()
        try:
            document = response.json()
        except ValueError:
            raise _mismatch() from None
        return self._normalized(document, order, payload)

    def _ensure(self, client, order, payload):
        return self._request(client, "POST", "/v2/checkout/orders", order, payload, create=True)

    def status(self, order: dict) -> dict:
        payload = self._payload(order)
        with self._session() as client:
            current = self._ensure(client, order, payload)
            bound = {**order, "provider_order_id": current["provider_order_id"]}
            return self._request(client, "GET", f"/v2/checkout/orders/{current['provider_order_id']}", bound, payload)

    def execute(self, order: dict, outcome: str) -> dict:
        if outcome not in ("complete", "pending", "cancel"):
            raise ValueError("unsupported local payment outcome")
        payload = self._payload(order)
        with self._session() as client:
            current = self._ensure(client, order, payload)
            if current["status"] in ("COMPLETED", "CANCELLED"):
                return current
            provider_id = current["provider_order_id"]
            bound = {**order, "provider_order_id": provider_id}
            if outcome in ("pending", "cancel"):
                return self._request(client, "POST", f"/mock/orders/{provider_id}/{outcome}", bound, payload)
            if current["status"] != "APPROVED":
                self._request(client, "POST", f"/mock/orders/{provider_id}/approve", bound, payload)
            return self._request(client, "POST", f"/v2/checkout/orders/{provider_id}/capture", bound, payload)
