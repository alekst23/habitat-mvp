"""Owner-scoped dashboard reads, layout saves and a bounded Studio AI adapter."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from aicl.control.csrf import require_csrf
from aicl.control.errors import AiclError
from aicl.studio.state import MAX_STATE_BYTES, StudioState, validate_json
from aicl.web.account import sidebar_context


async def _body(request, limit):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > limit:
            raise AiclError("validation_failed", "This dashboard request is too large.")
    try:
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise AiclError("validation_failed", "Supply a valid JSON object.") from None
    if not isinstance(value, dict):
        raise AiclError("validation_failed", "Supply a JSON object.")
    validate_json(value)
    return value


def studio_router(ctx):
    router = APIRouter()
    if not ctx.settings.workflow_enabled:
        return router
    from aicl.studio.ai import StudioAI
    from aicl.studio.data import StudioData
    from aicl.studio.pages import render_studio

    state, data, ai = StudioState(ctx), StudioData(ctx), StudioAI(ctx)
    csrf = require_csrf(ctx)

    def authenticated(request):
        auth = ctx.auth_provider.resolve(dict(request.cookies))
        if auth is None:
            raise AiclError("unauthenticated", "Sign in to view agent operations.")
        return auth

    def json_response(value):
        return JSONResponse(value, headers={"Cache-Control": "no-store"})

    @router.get("/audit/studio", response_class=HTMLResponse)
    def page(request: Request):
        auth = ctx.auth_provider.resolve(dict(request.cookies))
        if auth is None:
            return RedirectResponse("/", 303)
        return HTMLResponse(render_studio(ai_enabled=ctx.settings.studio_ai_enabled,
                             studio_license_key=ctx.settings.studio_license_key.get_secret_value(),
                             **sidebar_context(ctx, auth)), headers={"Cache-Control": "no-store"})

    @router.get("/audit/studio/data")
    def snapshot(request: Request, instance_id: str = "", date_from: str = "", date_to: str = "", timezone: str = "America/New_York"):
        return json_response(data.snapshot(authenticated(request), instance_id=instance_id,
                                           date_from=date_from, date_to=date_to, timezone=timezone))

    @router.get("/audit/studio/state")
    def layout(request: Request):
        return json_response(state.read(authenticated(request)))

    @router.put("/audit/studio/state")
    async def save_layout(request: Request, auth=Depends(csrf)):
        body = await _body(request, MAX_STATE_BYTES + 2048)
        if set(body) != {"state", "expected_version"}:
            raise AiclError("validation_failed", "Supply state and expected_version only.")
        return json_response(state.save(auth, body["state"], body["expected_version"]))

    @router.post("/audit/studio/ai")
    async def analyst(request: Request, auth=Depends(csrf)):
        if not ctx.settings.studio_ai_enabled:
            raise AiclError("unavailable", "The dashboard assistant is not configured. Filters and saved layouts remain available.")
        body = await _body(request, 64_000)
        if set(body) != {"request_id", "request"}:
            raise AiclError("validation_failed", "Supply request_id and the Studio request only.")
        return json_response(await ai.respond(auth, body["request_id"], body["request"]))

    return router
