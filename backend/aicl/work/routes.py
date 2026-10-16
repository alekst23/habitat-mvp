"""Simulated-work and confirmation routes, OAuth begin/callback and the fake provider page (owner E11-2)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aicl.connections.service import CALLBACK_PATH
from aicl.control.audit import AuditEvent, SqliteAuditLog
from aicl.control.budget import Estimate
from aicl.control.confirmation import SqliteConfirmationStore
from aicl.control.csrf import require_csrf
from aicl.control.errors import ERROR_HTTP_STATUS, AiclError
from aicl.creation.models import IDEMPOTENCY_KEY_PATTERN
from aicl.creation.routes import field_errors_from
from aicl.creation.tools import to_jsonable
from aicl.db import to_iso
from aicl.work.models import WorkRequest

CONNECTIONS_AREA = "/connections"


class EstimateBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    inference_input_tokens: int
    inference_output_tokens: int
    compute_minutes: int


class WorkRequestBody(BaseModel):
    """No tenant, owner or instance field: the instance comes from the path, identity from the session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    work_id: str = Field(pattern=IDEMPOTENCY_KEY_PATTERN)
    capability: str
    payload: dict[str, object] = {}
    estimate: EstimateBody | None = None
    destination_url: str | None = None


class BeginOAuthBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    capabilities: list[str]
    display_name: str | None = None


def _redirect(result: str) -> RedirectResponse:
    return RedirectResponse(f"{CONNECTIONS_AREA}?oauth={result}", status_code=303)


def router_factory(ctx) -> APIRouter:
    from aicl import wiring

    router = APIRouter()
    csrf = require_csrf(ctx)
    audit = SqliteAuditLog(ctx.clock)

    async def json_body(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            raise AiclError("validation_failed", "invalid body",
                            field_errors=[{"field": "body", "code": "invalid_json"}]) from None
        if not isinstance(body, dict):
            raise AiclError("validation_failed", "invalid body", field_errors=[{"field": "body", "code": "invalid"}])
        return body

    @router.post("/instances/{instance_id}/work-requests")
    async def work_request(instance_id: str, request: Request, auth=Depends(csrf)):
        body = await json_body(request)
        try:
            parsed = WorkRequestBody.model_validate(body)
        except ValidationError as exc:
            raise field_errors_from(exc) from None
        estimate = None if parsed.estimate is None else Estimate(
            parsed.estimate.inference_input_tokens, parsed.estimate.inference_output_tokens,
            parsed.estimate.compute_minutes)
        work = WorkRequest(instance_id=instance_id, work_id=parsed.work_id, capability=parsed.capability,
                           payload=parsed.payload, estimate=estimate, destination_url=parsed.destination_url)
        result = wiring.work_gate(ctx).authorize_and_dispatch(auth, work)
        payload = to_jsonable(result)
        if result.outcome == "denied":
            return JSONResponse({"error": "denied", "message": "work was denied", "reason": result.denial_reason,
                                 "pending_action_id": result.pending_action_id, "result": payload},
                                status_code=ERROR_HTTP_STATUS["denied"])
        return payload

    @router.post("/pending-actions/{pending_action_id}/confirm")
    def confirm(pending_action_id: str, auth=Depends(csrf)):
        store = SqliteConfirmationStore(ctx.settings.confirmation_ttl_seconds, ctx.clock)
        with ctx.db.transaction() as conn:
            existing = conn.execute("SELECT id FROM action_confirmation WHERE pending_action_id = ?",
                                    (pending_action_id,)).fetchone()
            confirmation = store.create_confirmation(conn, auth, pending_action_id)
            if existing is None:
                audit.append(conn, AuditEvent(
                    "confirmation.created", "owner", "committed", auth.tenant_id, auth.owner_id,
                    confirmation.instance_id, details={"confirmation_id": confirmation.id,
                                                       "capability": confirmation.capability}))
        return {"confirmation_id": confirmation.id, "pending_action_id": pending_action_id,
                "expires_at": to_iso(confirmation.expires_at)}

    @router.post("/connections/oauth/begin")
    async def begin_oauth(request: Request, auth=Depends(csrf)):
        try:
            parsed = BeginOAuthBody.model_validate(await json_body(request))
        except ValidationError as exc:
            raise field_errors_from(exc) from None
        return wiring.connection_service(ctx).begin_oauth(auth, parsed.provider, tuple(parsed.capabilities),
                                                          parsed.display_name)

    @router.get(CALLBACK_PATH)
    def oauth_callback(request: Request, state: str | None = None, code: str | None = None,
                       error: str | None = None):
        auth = ctx.auth_provider.resolve(dict(request.cookies))
        if auth is None:
            raise AiclError("unauthenticated", "sign in required")
        if error or not state or not code:
            return _redirect("denied")
        try:
            wiring.connection_service(ctx).complete_oauth(auth, state, code)
        except Exception:  # generic message: never echo the state, code or tokens
            return _redirect("denied")
        return _redirect("connected")

    if ctx.settings.environment in ("test", "development") and ctx.settings.provider_mode == "fake":
        @router.get("/fake-provider/authorize")
        def fake_authorize(state: str, scenario: str = "ok"):
            scenario = scenario if re.fullmatch(r"[a-z0-9-]{1,32}", scenario) else "ok"
            base = ctx.settings.public_base_url.rstrip("/")
            return RedirectResponse(f"{base}{CALLBACK_PATH}?state={state}&code=fake-code-{scenario}",
                                    status_code=303)

    return router
