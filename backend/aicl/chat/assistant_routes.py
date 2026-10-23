"""Authenticated assistant UI. Owner confirmations are separate CSRF-protected POSTs."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from aicl.chat.assistant_pages import render_assistant
from aicl.chat.assistant_service import AssistantService, identifier
from aicl.control.csrf import require_csrf
from aicl.web.account import sidebar_context
from aicl.control.errors import AiclError, ERROR_HTTP_STATUS


def assistant_router(ctx):
    router = APIRouter()
    service = AssistantService(ctx)
    csrf = require_csrf(ctx)

    def page(auth, session_id, *, status=200, error="", notice=""):
        view = service.view(auth, session_id)
        return HTMLResponse(render_assistant(**view, **sidebar_context(ctx, auth),
                                             request_id=str(uuid.uuid4()), error=error, notice=notice),
                            status_code=status, headers={"Cache-Control": "no-store"})

    @router.get("/chat", response_class=HTMLResponse)
    def chat_page(request: Request, session: str = "", notice: str = "", new: bool = False):
        auth = ctx.auth_provider.resolve(dict(request.cookies))
        if auth is None:
            return RedirectResponse("/", 303)
        if not session:
            latest = None
            if not new:
                with ctx.db.reader() as conn:
                    latest = conn.execute("SELECT id FROM assistant_session WHERE tenant_id=? AND owner_id=? "
                                          "ORDER BY updated_at DESC, rowid DESC LIMIT 1", (auth.tenant_id, auth.owner_id)).fetchone()
            session = latest["id"] if latest else service.new_session(auth)
            return RedirectResponse(f"/chat?session={session}", 303)
        # A missing/foreign conversation reveals no details and never creates a
        # model request merely because the browser followed a URL.
        try:
            return page(auth, session, notice="Your reviewed change was saved." if notice == "saved" else "")
        except AiclError as exc:
            if exc.error == "not_found":
                return RedirectResponse("/chat", 303)
            raise

    @router.post("/chat/messages")
    async def chat_message(request: Request, auth=Depends(csrf)):
        is_form = request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded")
        try:
            body = await request.form() if is_form else await request.json()
        except ValueError:
            raise AiclError("validation_failed", "Enter a message and conversation identifier.") from None
        if not hasattr(body, "get"):
            raise AiclError("validation_failed", "Enter a message and conversation identifier.")
        session_id = identifier(body.get("chat_session_id"))
        request_id = identifier(body.get("request_id"))
        try:
            result = await service.message(auth, session_id, request_id, body.get("text"))
        except AiclError as exc:
            if not is_form or exc.error == "not_found":
                raise
            return page(auth, session_id, status=ERROR_HTTP_STATUS[exc.error], error=exc.message or exc.error)
        if is_form:
            return RedirectResponse(f"/chat?session={session_id}", 303)
        return JSONResponse({**result, **service.view(auth, session_id)}, headers={"Cache-Control": "no-store"})

    @router.post("/chat/proposals/{proposal_id}/confirm")
    async def confirm(proposal_id: str, request: Request, auth=Depends(csrf)):
        is_form = request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded")
        try:
            body = await request.form() if is_form else await request.json()
        except ValueError:
            raise AiclError("validation_failed", "Review the proposal again before confirming.") from None
        if not hasattr(body, "get"):
            raise AiclError("validation_failed", "Review the proposal again before confirming.")
        session_id, proposal_id = identifier(body.get("chat_session_id")), identifier(proposal_id)
        version = body.get("version")
        if is_form and isinstance(version, str) and version.isascii() and version.isdigit() and len(version) < 10:
            version = int(version)
        if type(version) is not int or version < 1:
            raise AiclError("validation_failed", "Review the current proposal version before confirming.")
        try:
            result = service.confirm(auth, session_id, proposal_id, version)
        except AiclError as exc:
            if not is_form or exc.error == "not_found":
                raise
            return page(auth, session_id, status=ERROR_HTTP_STATUS[exc.error], error=exc.message or exc.error)
        if is_form:
            return RedirectResponse(f"/chat?session={session_id}&notice=saved", 303)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    return router
