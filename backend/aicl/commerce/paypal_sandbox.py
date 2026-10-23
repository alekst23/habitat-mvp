"""Server-only PayPal Sandbox Orders v2 adapter; live payments are not supported.

Each receiving merchant uses its own REST app credentials. This is deliberately
not a partner/marketplace integration and never asserts authority for a third
party. Durable local claims, owner approval and settlement belong to the service.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import parse_qs, urlsplit
import uuid

import httpx

from aicl.control.errors import AiclError


_API = "https://api-m.sandbox.paypal.com"
_ID = re.compile(r"^[A-Z0-9]{1,36}$")
_AMOUNT = re.compile(r"^[0-9]+(?:\.[0-9]{1,2})?$")
_MERCHANTS = {"service_topup": {"habitat-demo"},
              "agent_purchase": {"demo-template-shop", "launchpad-ads-demo"}}


def _mismatch():
    return AiclError("provider_mismatch", "PayPal Sandbox did not match the approved order. Keep it for reconciliation.")


def _unavailable():
    return AiclError("provider_unavailable", "PayPal Sandbox could not confirm the result. Check this same order again.")


def _configured(value):
    return isinstance(value, str) and 0 < len(value) <= 4096 and not any(char.isspace() for char in value)


class PayPalSandboxAdapter:
    """Idempotent create/capture with exact recipient, purpose and money checks."""

    transport = "paypal_sandbox"

    def __init__(self, *, client_id: str, client_secret: str, merchant_id: str, public_base_url: str,
                 purchase_client_id: str = "", purchase_client_secret: str = "",
                 purchase_merchant_id: str = "", timeout_seconds: float = 10,
                 transport: httpx.BaseTransport | None = None):
        if not (_configured(client_id) and _configured(client_secret)
                and isinstance(merchant_id, str) and _ID.fullmatch(merchant_id)):
            raise ValueError("PayPal Sandbox service merchant credentials and merchant ID are required")
        purchase = (purchase_client_id, purchase_client_secret, purchase_merchant_id)
        if any(purchase) and not (all(_configured(value) for value in purchase)
                                  and _ID.fullmatch(purchase_merchant_id)):
            raise ValueError("PayPal Sandbox purchases require all three separate seller settings")
        try:
            url = urlsplit(public_base_url)
            if (not isinstance(public_base_url, str) or any(char.isspace() for char in public_base_url)
                    or not url.hostname or url.username is not None or url.password is not None
                    or url.query or url.fragment or url.path not in ("", "/")
                    or (url.scheme != "https" and not (url.scheme == "http" and url.hostname in
                                                       {"localhost", "127.0.0.1", "::1"}))):
                raise ValueError
            # Accessing .port also rejects malformed/out-of-range port values.
            if url.port is not None and not 1 <= url.port <= 65535:
                raise ValueError
        except (TypeError, ValueError, AttributeError):
            raise ValueError("PayPal return origin must be HTTPS or local HTTP, without a path or credentials") from None
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= 10):
            raise ValueError("PayPal Sandbox timeout must be between 0 and 10 seconds")
        self._service_credentials = (client_id, client_secret, merchant_id)
        self._purchase_credentials = purchase if all(purchase) else None
        self.supports_purchases = self._purchase_credentials is not None
        self.public_base_url = public_base_url.rstrip("/")
        self._timeout, self._transport = timeout_seconds, transport

    def merchant_id_for(self, order: dict) -> str:
        """Resolve the pinned payee locally, before the service reserves dispatch."""
        return self._credentials(order)[2]

    def _credentials(self, order):
        try:
            purpose = order["purpose"]
            if order["merchant_id"] not in _MERCHANTS.get(purpose, set()):
                raise ValueError
            credentials = self._service_credentials if purpose == "service_topup" else self._purchase_credentials
            if credentials is None:
                raise AiclError("provider_not_configured", "Configure the separate PayPal Sandbox seller before making agent purchases.")
            if order.get("provider_merchant_id") and order["provider_merchant_id"] != credentials[2]:
                raise ValueError
            return credentials
        except (KeyError, TypeError, ValueError, AttributeError):
            raise _mismatch() from None

    def _payload(self, order):
        merchant_id = self.merchant_id_for(order)
        try:
            reference, amount = order["id"], order["amount_minor"]
            if (not isinstance(reference, str) or str(uuid.UUID(reference)) != reference
                    or type(amount) is not int or not 1 <= amount <= 100_000_000
                    or order["currency"] != "USD"
                    or (order.get("provider_order_id") and not _ID.fullmatch(order["provider_order_id"]))):
                raise ValueError
            return {"intent": "CAPTURE", "purchase_units": [{
                "reference_id": reference, "custom_id": order["purpose"],
                "payee": {"merchant_id": merchant_id},
                "amount": {"currency_code": "USD", "value": f"{amount // 100}.{amount % 100:02d}"},
            }], "payment_source": {"paypal": {"experience_context": {
                "return_url": f"{self.public_base_url}/commerce/orders/{reference}/paypal-return",
                "cancel_url": f"{self.public_base_url}/commerce/orders/{reference}/paypal-cancel",
                "landing_page": "LOGIN", "user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING",
            }}}}
        except (KeyError, TypeError, ValueError, AttributeError):
            raise _mismatch() from None

    @staticmethod
    def _request_id(order, operation):
        # Separate UUID namespaces per operation; 36 ASCII characters, restart-stable.
        return str(uuid.uuid5(uuid.UUID(order["id"]), "paypal_sandbox:" + operation))

    def _session(self):
        return httpx.Client(base_url=_API, timeout=self._timeout, follow_redirects=False,
                            trust_env=False, transport=self._transport)

    def _authenticate(self, client, order):
        client_id, client_secret, _ = self._credentials(order)
        try:
            response = client.post("/v1/oauth2/token", data={"grant_type": "client_credentials"},
                                   auth=httpx.BasicAuth(client_id, client_secret),
                                   headers={"Accept": "application/json"})
            if response.status_code != 200:
                raise _unavailable()
            document = response.json()
            token = document["access_token"]
            if (document["token_type"].lower() != "bearer" or not _configured(token)):
                raise _unavailable()
            client.headers["Authorization"] = f"Bearer {token}"
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            # Never surface response bodies, credentials or bearer tokens.
            raise _unavailable() from None

    def _request(self, client, method, path, *, payload=None, request_id=None):
        headers = {"Prefer": "return=representation"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        try:
            response = client.request(method, path, json=payload, headers=headers)
        except httpx.HTTPError:
            raise _unavailable() from None
        if response.status_code not in (200, 201):
            raise _unavailable()
        try:
            document = response.json()
            if not isinstance(document, dict):
                raise ValueError
            return document
        except (TypeError, ValueError):
            raise _mismatch() from None

    @staticmethod
    def _same_amount(value, order):
        try:
            amount = value["value"]
            return (value["currency_code"] == order["currency"] and isinstance(amount, str)
                    and _AMOUNT.fullmatch(amount) is not None
                    and Decimal(amount) * 100 == order["amount_minor"])
        except (KeyError, TypeError, InvalidOperation):
            return False

    @staticmethod
    def _approval_url(document, provider_id):
        links = document.get("links", [])
        if not isinstance(links, list):
            raise ValueError
        approvals = [link for link in links if link.get("rel") in {"approve", "payer-action"}]
        if not approvals:
            return None
        if len(approvals) != 1:
            raise ValueError
        link = approvals[0]
        href = link["href"]
        url = urlsplit(href)
        if (not isinstance(href, str) or any(char.isspace() for char in href)
                or url.scheme != "https" or url.netloc != "www.sandbox.paypal.com" or url.path != "/checkoutnow"
                or url.username is not None or url.password is not None
                or url.fragment or link.get("method", "GET") != "GET"
                or parse_qs(url.query).get("token") != [provider_id]):
            raise ValueError
        return href

    def _normalized(self, document, order):
        try:
            provider_id, status, units = document["id"], document["status"], document["purchase_units"]
            if (not isinstance(provider_id, str) or not _ID.fullmatch(provider_id)
                    or document["intent"] != "CAPTURE" or not isinstance(units, list) or len(units) != 1
                    or (order.get("provider_order_id") and order["provider_order_id"] != provider_id)
                    or status not in {"CREATED", "SAVED", "PAYER_ACTION_REQUIRED", "APPROVED", "COMPLETED", "VOIDED"}):
                raise ValueError
            unit = units[0]
            if (unit["reference_id"] != order["id"] or unit["custom_id"] != order["purpose"]
                    or unit["payee"]["merchant_id"] != self.merchant_id_for(order)
                    or not self._same_amount(unit["amount"], order)):
                raise ValueError
            normalized_status = {"SAVED": "CREATED", "PAYER_ACTION_REQUIRED": "CREATED", "VOIDED": "CANCELLED"}.get(status, status)
            result = {"provider_order_id": provider_id, "status": normalized_status,
                      "reference": order["id"], "purpose": order["purpose"], "amount_minor": order["amount_minor"],
                      "currency": order["currency"], "merchant_id": order["merchant_id"],
                      "provider_merchant_id": self.merchant_id_for(order)}
            approval_url = self._approval_url(document, provider_id)
            if approval_url:
                result["approval_url"] = approval_url
            payments = unit.get("payments", {})
            if payments.get("authorizations") or payments.get("refunds"):
                raise ValueError
            captures = payments.get("captures", [])
            if not isinstance(captures, list) or len(captures) > 1:
                raise ValueError
            if captures:
                capture = captures[0]
                if (status not in {"APPROVED", "COMPLETED"} or not _ID.fullmatch(capture["id"])
                        or not self._same_amount(capture["amount"], order)):
                    raise ValueError
                if capture["status"] == "PENDING":
                    result["status"] = "PENDING"
                elif capture["status"] == "COMPLETED" and status == "COMPLETED":
                    result["capture_id"] = capture["id"]
                else:
                    raise ValueError
            elif status == "COMPLETED":
                raise ValueError
            return result
        except (KeyError, TypeError, ValueError, AttributeError):
            raise _mismatch() from None

    def _get(self, client, order):
        return self._normalized(self._request(client, "GET", f"/v2/checkout/orders/{order['provider_order_id']}"), order)

    def _current(self, client, order, payload):
        if order.get("provider_order_id"):
            return self._get(client, order)
        # PayPal stores create request IDs for six hours by default. Replaying a
        # lost response later could create a second order, so never do that.
        try:
            created_at = datetime.fromisoformat(order["created_at"].replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - created_at
            if created_at.tzinfo is None or not timedelta(0) <= age < timedelta(hours=6):
                raise ValueError
        except (KeyError, TypeError, ValueError, AttributeError):
            raise AiclError("provider_unavailable", "This order cannot be safely recreated. Reconcile its PayPal Sandbox status before creating a replacement.") from None
        document = self._request(client, "POST", "/v2/checkout/orders", payload=payload,
                                 request_id=self._request_id(order, "create"))
        if "purchase_units" not in document or "intent" not in document:
            # Some create responses remain minimal despite Prefer. Only the ID
            # locates the resource; authoritative GET must verify its full scope.
            try:
                provider_id = document["id"]
                if (not isinstance(provider_id, str) or not _ID.fullmatch(provider_id)
                        or document.get("intent", "CAPTURE") != "CAPTURE"):
                    raise ValueError
                approval_url = self._approval_url(document, provider_id)
            except (KeyError, TypeError, ValueError, AttributeError):
                raise _mismatch() from None
            current = self._get(client, {**order, "provider_order_id": provider_id})
            if approval_url and "approval_url" not in current and current["status"] in {"CREATED", "APPROVED"}:
                current["approval_url"] = approval_url
            return current
        return self._normalized(document, order)

    def status(self, order: dict) -> dict:
        payload = self._payload(order)
        with self._session() as client:
            self._authenticate(client, order)
            # Recovery may replay the original create, but never approve/capture.
            return self._current(client, order, payload)

    def execute(self, order: dict, outcome: str) -> dict:
        if outcome == "cancel":
            raise AiclError("invalid_transition", "Leaving checkout does not cancel a PayPal order. Check its payment status before releasing the reservation.")
        if outcome not in {"start", "complete"}:
            raise ValueError("unsupported PayPal Sandbox action")
        payload = self._payload(order)
        with self._session() as client:
            self._authenticate(client, order)
            current = self._current(client, order, payload)
            if outcome == "start":
                if current["status"] in {"CREATED", "APPROVED"} and not current.get("approval_url"):
                    raise _mismatch()
                return current
            bound = {**order, "provider_order_id": current["provider_order_id"]}
            if not order.get("provider_order_id"):
                current = self._get(client, bound)
            if current["status"] in {"COMPLETED", "PENDING", "CANCELLED"}:
                return current
            if current["status"] != "APPROVED":
                raise AiclError("invalid_transition", "Approve this payment on PayPal before completing it in Habitat.",
                                reason="payment_not_approved")
            try:
                self._request(client, "POST", f"/v2/checkout/orders/{current['provider_order_id']}/capture",
                              payload={}, request_id=self._request_id(order, "capture"))
            except AiclError as error:
                if error.error != "provider_unavailable":
                    raise
                # A lost response or concurrent capture can already have settled.
                observed = self._get(client, bound)
                if observed["status"] in {"COMPLETED", "PENDING"}:
                    return observed
                raise
            # Settlement trusts this authoritative GET, not the browser return or
            # a potentially partial capture response.
            return self._get(client, bound)
