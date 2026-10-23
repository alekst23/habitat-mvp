"""`GET /chat` and `POST /chat/messages` (aicl-experience/technical.md, owner E11-4).

`GET /chat` redirects an unauthenticated visitor to the landing page; `POST /chat/messages` uses the shared E11-1
`require_csrf` dependency and never reads a tenant or owner from the client. A JSON body `{"text", "chat_session_id"?}`
returns the reply as JSON; a urlencoded form post (the no-JavaScript page) redirects back to the transcript. All
message text is untrusted: the page is autoescaped and the JSON carries it as plain strings.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from aicl.chat.service import SqliteChatOrchestrator
from aicl.control.csrf import require_csrf
from aicl.web.account import sidebar_context
from aicl.control.errors import ERROR_HTTP_STATUS, AiclError
from aicl.creation.service import validation_failed
from aicl.web.pages import render


def chat_router(ctx) -> APIRouter:
    """`(AppContext) -> APIRouter` factory in the ROUTE_FACTORIES shape."""
    router = APIRouter()
    csrf = require_csrf(ctx)
    orchestrator = SqliteChatOrchestrator(ctx.db, ctx.clock, ctx.ports.chat_model)

    def page(auth, session_id: str | None, status: int = 200, error: str = "") -> HTMLResponse:
        messages = orchestrator.transcript(auth, session_id)
        return HTMLResponse(render("chat", title="Create with chat", messages=messages, session_id=session_id or "",
                                   error=error, **sidebar_context(ctx, auth)),
                            status_code=status)

    @router.get("/chat", response_class=HTMLResponse)
    def chat_page(request: Request, session: str = ""):
        auth = ctx.auth_provider.resolve(dict(request.cookies))
        if auth is None:
            return RedirectResponse("/", status_code=303)
        try:
            return page(auth, session or None)
        except AiclError as exc:
            if exc.error != "not_found":
                raise
            return RedirectResponse("/chat", status_code=303)  # unknown or foreign session: start a new chat

    @router.post("/chat/messages")
    async def chat_message(request: Request, auth=Depends(csrf)):
        content_type = request.headers.get("content-type", "")
        is_form = content_type.startswith("application/x-www-form-urlencoded")
        if is_form:
            form = await request.form()  # tenant_id / owner_id fields, if any, are never read
            text, session_id = form.get("text", ""), form.get("chat_session_id") or None
        else:
            try:
                body = await request.json()
            except ValueError:
                raise validation_failed(("body", "invalid_json")) from None
            if not isinstance(body, dict):
                raise validation_failed(("body", "invalid"))
            text, session_id = body.get("text", ""), body.get("chat_session_id") or None
        if not isinstance(text, str) or (session_id is not None and not isinstance(session_id, str)):
            raise validation_failed(("body", "invalid"))
        try:
            reply = orchestrator.handle_message(auth, session_id, text)
        except AiclError as exc:
            if not is_form:
                raise
            status = ERROR_HTTP_STATUS[exc.error]
            try:
                return page(auth, session_id, status, error=exc.message or exc.error)
            except AiclError:
                return page(auth, None, status, error=exc.message or exc.error)
        if is_form:
            return RedirectResponse(f"/chat?session={reply.chat_session_id}", status_code=303)
        return JSONResponse({"chat_session_id": reply.chat_session_id, "turn": reply.turn, "text": reply.text,
                             "instance_id": reply.instance_id,
                             "instance_url": "/workspace" if reply.instance_id else None})

    return router
