"""A durable, loopback-only payment fixture with a small PayPal-shaped HTTP API.

This is not PayPal Sandbox. The bearer token authenticates only this local mock;
no PayPal credentials, external network calls, or real payment instruments exist.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator


_MERCHANTS = {"service_topup": {"habitat-demo"},
              "agent_purchase": {"demo-template-shop", "launchpad-ads-demo"}}
_MOCK_BUYERS = {"demo-buyer", "demo-buyer-alt"}
_AMOUNT = re.compile(r"^(0|[1-9][0-9]{0,6})\.[0-9]{2}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Amount(_StrictModel):
    currency_code: StrictStr
    value: StrictStr

    @model_validator(mode="after")
    def valid_money(self):
        if self.currency_code != "USD" or not _AMOUNT.fullmatch(self.value):
            raise ValueError("USD amount must use exactly two decimal places")
        whole, fraction = self.value.split(".")
        if not 1 <= int(whole) * 100 + int(fraction) <= 100_000_000:
            raise ValueError("amount is outside the local mock range")
        return self


class _Payee(_StrictModel):
    merchant_id: StrictStr


class _PurchaseUnit(_StrictModel):
    reference_id: StrictStr
    custom_id: StrictStr
    payee: _Payee
    amount: _Amount

    @model_validator(mode="after")
    def valid_binding(self):
        if str(uuid.UUID(self.reference_id)) != self.reference_id:
            raise ValueError("reference_id must be a canonical UUID")
        if self.payee.merchant_id not in _MERCHANTS.get(self.custom_id, set()):
            raise ValueError("unknown mock merchant or purpose")
        return self


class _CreateOrder(_StrictModel):
    intent: StrictStr
    purchase_units: list[_PurchaseUnit] = Field(min_length=1, max_length=1)
    mock_buyer_id: StrictStr | None = None

    @model_validator(mode="after")
    def capture_only(self):
        if self.intent != "CAPTURE":
            raise ValueError("only CAPTURE intent is supported")
        if self.mock_buyer_id is not None and self.mock_buyer_id not in _MOCK_BUYERS:
            raise ValueError("unknown local mock buyer")
        return self


def create_payment_app(database_path: str | Path, token: str) -> FastAPI:
    """Create an isolated provider with its own durable SQLite store and token."""
    if not isinstance(token, str) or len(token) < 24 or any(char.isspace() for char in token):
        raise ValueError("AICL_MOCK_PAYMENT_TOKEN must contain at least 24 non-whitespace characters")
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def database(*, write=False):
        conn = sqlite3.connect(path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    with database(write=True) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS payment_order (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL UNIQUE,
            reference TEXT NOT NULL UNIQUE,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('CREATED','APPROVED','PENDING','COMPLETED','CANCELLED')),
            capture_id TEXT UNIQUE,
            CHECK((status = 'COMPLETED') = (capture_id IS NOT NULL))
        )""")

    app = FastAPI(title="Habitat local mock payment provider", docs_url=None,
                  redoc_url=None, openapi_url=None)

    def authenticated(authorization: str | None = Header(default=None)):
        supplied = (authorization or "").encode("utf-8")
        if not hmac.compare_digest(supplied, f"Bearer {token}".encode("utf-8")):
            raise HTTPException(401, "local_provider_authentication_required")

    def load(conn, provider_id):
        row = conn.execute("SELECT * FROM payment_order WHERE id = ?", (provider_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "mock_order_not_found")
        return row

    def document(row):
        result = json.loads(row["payload_json"])
        result.update(id=row["id"], status=row["status"])
        if row["capture_id"]:
            unit = result["purchase_units"][0]
            unit["payments"] = {"captures": [{"id": row["capture_id"], "status": "COMPLETED",
                                             "amount": dict(unit["amount"]), "final_capture": True}]}
        return result

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": "http_mock"}

    @app.post("/v2/checkout/orders", dependencies=[Depends(authenticated)])
    def create_order(body: _CreateOrder, request_id: str | None = Header(default=None, alias="PayPal-Request-Id")):
        reference = body.purchase_units[0].reference_id
        if request_id != reference:
            raise HTTPException(422, "request_id_must_match_local_reference")
        # Keep legacy orders byte-identical so old idempotency keys still recover.
        canonical = json.dumps(body.model_dump(exclude_none=True), sort_keys=True, separators=(",", ":"))
        with database(write=True) as conn:
            row = conn.execute("SELECT * FROM payment_order WHERE request_id = ?", (request_id,)).fetchone()
            if row is not None:
                if row["payload_json"] != canonical:
                    raise HTTPException(409, "idempotency_payload_conflict")
                return JSONResponse(document(row), status_code=200)
            provider_id = f"MOCK-ORDER-{uuid.uuid4()}"
            conn.execute("INSERT INTO payment_order(id,request_id,reference,payload_json,status) VALUES(?,?,?,?,?)",
                         (provider_id, request_id, reference, canonical, "CREATED"))
            return JSONResponse(document(load(conn, provider_id)), status_code=201)

    @app.get("/v2/checkout/orders/{provider_id}", dependencies=[Depends(authenticated)])
    def get_order(provider_id: str):
        with database() as conn:
            return document(load(conn, provider_id))

    def change(provider_id, target):
        with database(write=True) as conn:
            row = load(conn, provider_id)
            if row["status"] == target:
                return document(row)
            if row["status"] in ("COMPLETED", "CANCELLED"):
                raise HTTPException(409, "mock_order_is_terminal")
            if target == "COMPLETED":
                if row["status"] != "APPROVED":
                    raise HTTPException(409, "mock_buyer_approval_required")
                conn.execute("UPDATE payment_order SET status = ?, capture_id = ? WHERE id = ?",
                             (target, f"MOCK-CAPTURE-{uuid.uuid4()}", provider_id))
            else:
                conn.execute("UPDATE payment_order SET status = ? WHERE id = ?", (target, provider_id))
            return document(load(conn, provider_id))

    @app.post("/mock/orders/{provider_id}/approve", dependencies=[Depends(authenticated)])
    def approve(provider_id: str):
        return change(provider_id, "APPROVED")

    @app.post("/mock/orders/{provider_id}/pending", dependencies=[Depends(authenticated)])
    def pending(provider_id: str):
        return change(provider_id, "PENDING")

    @app.post("/mock/orders/{provider_id}/cancel", dependencies=[Depends(authenticated)])
    def cancel(provider_id: str):
        return change(provider_id, "CANCELLED")

    @app.post("/v2/checkout/orders/{provider_id}/capture", dependencies=[Depends(authenticated)])
    def capture(provider_id: str):
        return change(provider_id, "COMPLETED")

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Run Habitat's local HTTP mock payment provider; no real money")
    parser.add_argument("--db", default=".ctx/mock-commerce/payment-provider.db")
    parser.add_argument("--port", type=int, default=4174)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        app = create_payment_app(args.db, os.environ.get("AICL_MOCK_PAYMENT_TOKEN", ""))
    except ValueError as error:
        parser.error(str(error))
    print(f"Local mock payment API: http://127.0.0.1:{args.port} (simulated payments only)", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
