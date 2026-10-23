"""Owner-authenticated relay. Browser credentials never leave the broker."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from aicl.browser.factory import browser_broker
from aicl.browser.pages import render_browser
from aicl.control.csrf import require_csrf
from aicl.control.errors import AiclError
from aicl.web.account import sidebar_context


PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "same-origin",
                   "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff"}
PAGE_HEADERS = {**PRIVATE_HEADERS, "Content-Security-Policy":
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"}


def browser_router(ctx, owner_requests) -> APIRouter:
    from aicl.owner_requests.routes import request_url

    router, csrf = APIRouter(), require_csrf(ctx)
    broker = browser_broker(ctx, owner_requests)

    def version(form):
        value = str(form.get("expected_version", ""))
        if not value.isdigit() or len(value) > 12:
            raise AiclError("validation_failed", "Reload this request before continuing.")
        return int(value)

    def location(request_id):
        from urllib.parse import quote
        return "/requests/" + quote(request_id, safe="") + "/browser"

    @router.get("/requests/{request_id}/browser", response_class=HTMLResponse)
    def browser(request_id: str, request: Request):
        auth = ctx.auth_provider.resolve(dict(request.cookies))
        if auth is None:
            return RedirectResponse("/auth/sign-in", 303, headers=PRIVATE_HEADERS)
        item = owner_requests.get(auth, request_id)
        if item["kind"] != "authentication":
            raise AiclError("not_found", "Sign-in request not found.")
        state = broker.status(auth, request_id)
        return HTMLResponse(render_browser(r=item, browser=state,
            **sidebar_context(ctx, auth)), headers=PAGE_HEADERS)

    @router.post("/requests/{request_id}/browser/start")
    async def start(request_id: str, request: Request, auth=Depends(csrf)):
        form = await request.form()
        try:
            await run_in_threadpool(broker.start, auth, request_id, version(form))
        except AiclError as error:
            if error.error == "not_found":
                raise
            return RedirectResponse(request_url(request_id, error=error.message), 303, headers=PRIVATE_HEADERS)
        return RedirectResponse(location(request_id), 303, headers=PRIVATE_HEADERS)

    @router.post("/requests/{request_id}/browser/frame")
    async def frame(request_id: str, auth=Depends(csrf)):
        result = await run_in_threadpool(broker.frame, auth, request_id)
        return JSONResponse(result, headers=PRIVATE_HEADERS)

    @router.post("/requests/{request_id}/browser/input")
    async def browser_input(request_id: str, request: Request, auth=Depends(csrf)):
        # Keep input out of URLs, error messages and persistence. A bounded body
        # also prevents an owner from using the relay as an arbitrary upload.
        body = await request.body()
        if len(body) > 20_000:
            raise AiclError("validation_failed", "Browser input is too large.")
        try:
            import json
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise AiclError("validation_failed", "Invalid browser input.") from None
        if not isinstance(payload, dict):
            raise AiclError("validation_failed", "Invalid browser input.")
        result = await run_in_threadpool(broker.input, auth, request_id, payload)
        return JSONResponse(result or {"ok": True}, headers=PRIVATE_HEADERS)

    @router.post("/requests/{request_id}/browser/complete")
    async def complete(request_id: str, request: Request, auth=Depends(csrf)):
        form = await request.form()
        try:
            await run_in_threadpool(broker.complete, auth, request_id, version(form),
                                    str(form.get("continuation", "schedule")))
        except AiclError as error:
            if error.error == "not_found":
                raise
            return RedirectResponse(request_url(request_id, error=error.message), 303, headers=PRIVATE_HEADERS)
        return RedirectResponse(request_url(request_id, notice="session_provided"), 303, headers=PRIVATE_HEADERS)

    @router.post("/requests/{request_id}/browser/cancel")
    async def cancel(request_id: str, auth=Depends(csrf)):
        try:
            await run_in_threadpool(broker.cancel, auth, request_id)
        except AiclError as error:
            if error.error == "not_found":
                raise
            return RedirectResponse(request_url(request_id, error=error.message), 303, headers=PRIVATE_HEADERS)
        return RedirectResponse(request_url(request_id, notice="sign_in_cancelled"), 303, headers=PRIVATE_HEADERS)

    @router.post("/requests/{request_id}/browser/revoke")
    async def revoke(request_id: str, auth=Depends(csrf)):
        try:
            state = await run_in_threadpool(broker.status, auth, request_id)
            if state.get("id"):
                await run_in_threadpool(broker.revoke, auth, state["id"])
        except AiclError as error:
            if error.error == "not_found":
                raise
            return RedirectResponse(request_url(request_id, error=error.message), 303, headers=PRIVATE_HEADERS)
        return RedirectResponse(request_url(request_id, notice="session_revoked"), 303, headers=PRIVATE_HEADERS)

    return router
