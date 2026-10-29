"""One owner command surface for the workspace and its browser tool adapter."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from aicl.agent_workspace.assistant import WorkspaceAssistantService
from aicl.agent_workspace.execution import WorkspaceExecution
from aicl.agent_workspace.pages import render_workspace
from aicl.agent_workspace.service import WorkspaceService
from aicl.chat.assistant_service import identifier
from aicl.commerce.factory import commerce_service
from aicl.control.csrf import require_csrf
from aicl.control.errors import AiclError
from aicl.web.account import sidebar_context


def instance_workspace_url(ctx, auth, instance_id):
    """Legacy general-agent links resolve to their canonical workspace."""
    if getattr(ctx, "agent_runtime", None) is None:
        return None
    service = WorkspaceService(ctx)
    with ctx.db.reader() as conn:
        service._instance(conn, auth, instance_id)
        config = service.workflow._config(conn, auth, instance_id)
    if config.get("scenario") not in {"generic", "general"}:
        return None
    return "/agent-workspaces/" + service.open(auth, instance_id=instance_id)["id"]


def workspace_router(ctx):
    router = APIRouter()
    if getattr(ctx, "agent_runtime", None) is None:
        return router
    service, execution = WorkspaceService(ctx), WorkspaceExecution(ctx)
    csrf = require_csrf(ctx)

    def authenticated(request):
        auth = ctx.auth_provider.resolve(dict(request.cookies))
        if auth is None:
            raise AiclError("unauthenticated", "Sign in to continue.")
        return auth

    def snapshot(auth, workspace_id):
        with ctx.db.reader() as conn:
            state = service.view(auth, workspace_id)
            state["execution"] = execution.view(auth, workspace_id)
            conversation = WorkspaceAssistantService(ctx, workspace_id).view(auth, state["session_id"])
        return {"state": state, "messages": conversation["messages"], "usage": conversation["usage"]}

    @router.get("/agent-workspaces/{workspace_id}")
    def page(workspace_id: str, request: Request, notice: str = ""):
        auth = ctx.auth_provider.resolve(dict(request.cookies))
        if auth is None:
            return RedirectResponse("/", 303)
        data = snapshot(auth, identifier(workspace_id))
        notices = {"funded": "Payment completed. Your credit is ready. Start or continue work below."}
        account = sidebar_context(ctx, auth)
        return HTMLResponse(render_workspace(**data, csrf=account["csrf"], account_name=account["account_name"], notice=notices.get(notice, "")),
                            headers={"Cache-Control": "no-store"})

    @router.get("/api/agent-workspaces/{workspace_id}")
    def read(workspace_id: str, request: Request):
        return JSONResponse(snapshot(authenticated(request), identifier(workspace_id)), headers={"Cache-Control": "no-store"})

    async def body(request):
        try:
            raw = await request.body()
            if len(raw) > 100_000:
                raise ValueError()
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError()
            identifier(data.get("request_id"))
            return data
        except (ValueError, TypeError):
            raise AiclError("validation_failed", "Submit a valid workspace request.") from None

    @router.post("/api/agent-workspaces/{workspace_id}/commands")
    async def command(workspace_id: str, request: Request, auth=Depends(csrf)):
        workspace_id = identifier(workspace_id)
        data = await body(request)
        name, args = data.get("command"), data.get("arguments", {})
        if not isinstance(args, dict):
            raise AiclError("validation_failed", "Use the documented command arguments.")
        # Resolve ownership before every operation, including UI-only navigation.
        state = service.view(auth, workspace_id)
        version, extra = data.get("expected_version"), {}
        if name == "update_draft":
            service.update_draft(auth, workspace_id, version, args.get("patch"), actor="owner")
        elif name == "apply":
            service.apply(auth, workspace_id, version,
                          approved_public_research_digest=args.get("approved_public_research_digest"))
        elif name == "reload":
            service.reload(auth, workspace_id, version)
        elif name == "start":
            with ctx.db.transaction():
                service._version(service.view(auth, workspace_id), version)
                execution.start(auth, workspace_id, data["request_id"])
        elif name == "restart":
            execution.restart(auth, workspace_id, identifier(args.get("run_id")), data["request_id"],
                              version, args.get("expected_run_version"))
        elif name in {"pause", "resume", "cancel", "advance"}:
            execution.control(auth, workspace_id, identifier(args.get("run_id")), name,
                              expected_run_version=args.get("expected_run_version"))
        elif name == "message_run":
            execution.message(auth, workspace_id, identifier(args.get("run_id")), data["request_id"],
                              args.get("text"), question_id=args.get("question_id"))
        elif name == "schedule":
            if type(args.get("enabled")) is not bool:
                raise AiclError("validation_failed", "Choose whether the schedule is enabled.")
            execution.schedule(auth, workspace_id, args["enabled"], version)
        elif name == "lifecycle":
            execution.lifecycle(auth, workspace_id, args.get("action"), version)
        elif name == "fund":
            if not state["instance_id"]:
                raise AiclError("invalid_state", "Apply settings before adding service credit.")
            amount = args.get("amount_minor")
            if type(amount) is not int or amount not in {500, 1000, 2000}:
                raise AiclError("validation_failed", "Choose a top-up of $5, $10 or $20.")
            with ctx.db.transaction() as conn:
                payments = commerce_service(ctx)
                key = f"workspace:{workspace_id}:{data['request_id']}"
                replay = conn.execute("SELECT 1 FROM mock_commerce_order WHERE tenant_id=? AND purpose='service_topup' AND request_id=?",
                                      (auth.tenant_id, key)).fetchone()
                pending = conn.execute("SELECT id FROM mock_commerce_order WHERE instance_id=? AND tenant_id=? AND owner_id=? "
                                       "AND purpose='service_topup' AND state IN ('created','pending') ORDER BY rowid DESC LIMIT 1",
                                       (state["instance_id"], auth.tenant_id, auth.owner_id)).fetchone()
                order = (payments.order(auth, pending["id"]) if pending and not replay else
                         payments.create_topup(auth, state["instance_id"], amount, key))
            extra["redirect_url"] = f"/commerce/orders/{order['id']}"
        elif name == "show_section":
            if args.get("section") not in {"outcome", "goal", "deliverables", "tools", "schedule", "limits", "funding", "work", "progress", "results"}:
                raise AiclError("validation_failed", "Unknown workspace section.")
            extra["focus_section"] = args["section"]
        else:
            raise AiclError("validation_failed", "Unknown workspace command.")
        return JSONResponse({**snapshot(auth, workspace_id), **extra}, headers={"Cache-Control": "no-store"})

    @router.post("/api/agent-workspaces/{workspace_id}/messages")
    async def message(workspace_id: str, request: Request, auth=Depends(csrf)):
        workspace_id = identifier(workspace_id)
        data = await body(request)
        state = service.view(auth, workspace_id)
        assistant = WorkspaceAssistantService(ctx, workspace_id, data.get("expected_version"))
        turn = await assistant.message(auth, state["session_id"], data["request_id"], data.get("text"))
        focus = assistant.tools_instance.focus_section if assistant.tools_instance else None
        return JSONResponse({**snapshot(auth, workspace_id), "focus_section": focus, "turn": turn}, headers={"Cache-Control": "no-store"})

    return router
