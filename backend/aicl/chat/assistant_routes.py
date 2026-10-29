"""Authenticated assistant UI. Owner confirmations are separate CSRF-protected POSTs."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from aicl.chat.assistant_pages import render_assistant
from aicl.chat.assistant_service import AssistantService, identifier
from aicl.agent_runtime.chat_service import RuntimeChatService
from aicl.control.csrf import require_csrf
from aicl.web.account import sidebar_context
from aicl.control.errors import AiclError, ERROR_HTTP_STATUS
from aicl.commerce.factory import commerce_service


def assistant_router(ctx):
    router = APIRouter()
    service = AssistantService(ctx)
    sessions = RuntimeChatService(ctx)
    csrf = require_csrf(ctx)

    def legacy_guard(auth, session_id, instance_id=None):
        # A cached legacy page must not resurrect the old proposal/execution
        # flow after its conversation or agent has a canonical workspace.
        with ctx.db.reader() as conn:
            row = conn.execute("SELECT id FROM agent_workspace WHERE tenant_id=? AND owner_id=? "
                               "AND (session_id=? OR instance_id=?) LIMIT 1",
                               (auth.tenant_id, auth.owner_id, session_id, instance_id)).fetchone()
        if row:
            raise AiclError("conflict", "This agent now uses the shared workspace. Reload it to continue.",
                            workspace_url="/agent-workspaces/" + row["id"])

    def page(auth, session_id, *, status=200, error="", notice="", preferred_instance=""):
        view = service.view(auth, session_id)
        return HTMLResponse(render_assistant(**view, **sidebar_context(ctx, auth),
                                             request_id=str(uuid.uuid4()), error=error, notice=notice,
                                             preferred_instance=preferred_instance),
                            status_code=status, headers={"Cache-Control": "no-store"})

    @router.get("/chat", response_class=HTMLResponse)
    def chat_page(request: Request, session: str = "", notice: str = "", new: bool = False, instance: str = ""):
        auth = ctx.auth_provider.resolve(dict(request.cookies))
        if auth is None:
            return RedirectResponse("/", 303)
        if getattr(ctx, "agent_runtime", None) is not None:
            from aicl.agent_workspace.service import WorkspaceService
            if not session and not instance and not new:
                with ctx.db.reader() as conn:
                    latest = conn.execute("SELECT id FROM assistant_session WHERE tenant_id=? AND owner_id=? ORDER BY updated_at DESC,rowid DESC LIMIT 1",
                                          (auth.tenant_id, auth.owner_id)).fetchone()
                session = latest["id"] if latest else ""
            state = WorkspaceService(ctx).open(auth, instance_id=instance or None, session_id=session or None)
            return RedirectResponse("/agent-workspaces/" + state["id"] + ("?notice=funded" if notice == "funded" else ""), 303)
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
            notices = {"saved": "Your reviewed change was saved.",
                       "funded": "Payment completed. Review your controls, then start or resume your saved work."}
            return page(auth, session, notice=notices.get(notice, ""), preferred_instance=instance)
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
        legacy_guard(auth, session_id)
        try:
            result = await service.message(auth, session_id, request_id, body.get("text"),
                                           run_id=body.get("run_id") or None, question_id=body.get("question_id") or None)
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
        legacy_guard(auth, session_id)
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

    @router.get("/chat/runs/status")
    def runtime_status(request: Request, session_id: str):
        auth = ctx.auth_provider.resolve(dict(request.cookies))
        if auth is None:
            raise AiclError("unauthenticated", "Sign in to continue.")
        view = sessions.view(auth, identifier(session_id))
        return JSONResponse({"runtime_run": view["runtime_run"], "runtime_messages": view["runtime_messages"]},
                            headers={"Cache-Control": "no-store"})

    async def runtime_body(request):
        is_form = request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded")
        try:
            body = await request.form() if is_form else await request.json()
        except ValueError:
            raise AiclError("validation_failed", "Review the session controls and try again.") from None
        if not hasattr(body, "get"):
            raise AiclError("validation_failed", "Review the session controls and try again.")
        return is_form, body

    @router.post("/chat/funding")
    async def runtime_funding(request: Request, auth=Depends(csrf)):
        is_form, body = await runtime_body(request)
        session_id = identifier(body.get("chat_session_id"))
        instance_id = identifier(body.get("instance_id"))
        request_id = identifier(body.get("request_id"))
        legacy_guard(auth, session_id, instance_id)
        try:
            # Validate the conversation and selected agent before creating an
            # order. Funding never activates, starts or resumes the agent.
            with ctx.db.transaction() as conn:
                linked = sessions.linked(conn, auth, session_id)
                if linked:
                    eligible = linked["instance_id"] == instance_id
                else:
                    eligible = any(item["id"] == instance_id for item in sessions.candidates(conn, auth))
                if not eligible:
                    raise AiclError("not_found", "Agent not found in this conversation.")
                amount = str(body.get("amount_minor", ""))
                if amount not in {"500", "1000", "2000"}:
                    raise AiclError("validation_failed", "Choose a top-up of $5, $10 or $20.")
                payments = commerce_service(ctx)
                key = f"chat:{session_id}:{request_id}"
                replay = conn.execute("SELECT 1 FROM mock_commerce_order WHERE tenant_id=? "
                                      "AND purpose='service_topup' AND request_id=?", (auth.tenant_id, key)).fetchone()
                # A lost/pending payment outcome must be resolved on its saved
                # order before a fresh page can offer another top-up.
                pending = conn.execute("SELECT id FROM mock_commerce_order WHERE instance_id=? AND tenant_id=? "
                                       "AND owner_id=? AND purpose='service_topup' AND state IN ('created','pending') "
                                       "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                                       (instance_id, auth.tenant_id, auth.owner_id)).fetchone()
                order = (payments.order(auth, pending["id"]) if pending and not replay else
                         payments.create_topup(auth, instance_id, int(amount), key))
        except AiclError as exc:
            if not is_form or exc.error == "not_found":
                raise
            return page(auth, session_id, status=ERROR_HTTP_STATUS[exc.error], error=exc.message or exc.error,
                        preferred_instance=instance_id)
        return RedirectResponse(f"/commerce/orders/{order['id']}", 303)

    @router.post("/chat/runs/start")
    async def runtime_start(request: Request, auth=Depends(csrf)):
        is_form, body = await runtime_body(request)
        session_id = identifier(body.get("chat_session_id"))
        instance_id = identifier(body.get("instance_id"))
        legacy_guard(auth, session_id, instance_id)
        try:
            run = sessions.start(auth, session_id, instance_id, identifier(body.get("request_id")),
                                 list(body.getlist("tools")) if is_form else body.get("tools", []))
        except AiclError as exc:
            if not is_form or exc.error == "not_found":
                raise
            return page(auth, session_id, status=ERROR_HTTP_STATUS[exc.error], error=exc.message or exc.error,
                        preferred_instance=instance_id)
        if is_form:
            return RedirectResponse(f"/chat?session={session_id}", 303)
        return JSONResponse({"run_id": run["id"], **service.view(auth, session_id)}, headers={"Cache-Control": "no-store"})

    @router.post("/chat/runs/{run_id}/{action}")
    async def runtime_control(run_id: str, action: str, request: Request, auth=Depends(csrf)):
        is_form, body = await runtime_body(request)
        session_id = identifier(body.get("chat_session_id"))
        legacy_guard(auth, session_id)
        try:
            sessions.control(auth, session_id, identifier(run_id), action)
        except AiclError as exc:
            if not is_form or exc.error == "not_found":
                raise
            return page(auth, session_id, status=ERROR_HTTP_STATUS[exc.error], error=exc.message or exc.error)
        if is_form:
            return RedirectResponse(f"/chat?session={session_id}", 303)
        return JSONResponse(service.view(auth, session_id), headers={"Cache-Control": "no-store"})

    return router
