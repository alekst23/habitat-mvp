"""Owner-only request inbox. Agent proposals never share the owner response API."""
from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from aicl.control.csrf import require_csrf
from aicl.web.account import sidebar_context
from aicl.control.errors import AiclError
from aicl.owner_requests.factory import owner_request_service
from aicl.owner_requests.pages import render


def request_url(request_id: str = "", *, instance_id: str = "", notice: str = "", error: str = "") -> str:
    return "/requests?" + urlencode({k: v for k, v in (
        ("selected", request_id), ("instance_id", instance_id), ("notice", notice), ("error", error)
    ) if v})


def owner_requests_router(ctx) -> APIRouter:
    router = APIRouter()
    if not ctx.settings.workflow_enabled:
        return router
    service = owner_request_service(ctx)
    workflow = service.workflow
    commerce = workflow.commerce
    csrf = require_csrf(ctx)

    def authenticated(request):
        return ctx.auth_provider.resolve(dict(request.cookies))

    @router.get("/requests/summary")
    def summary(request: Request):
        auth = authenticated(request)
        if auth is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401,
                                headers={"Cache-Control": "no-store"})
        return JSONResponse({"pending_count": service.pending_count(auth)},
                            headers={"Cache-Control": "no-store"})

    @router.get("/requests", response_class=HTMLResponse)
    def inbox(request: Request, selected: str = "", instance_id: str = "", status: str = "pending",
              kind: str = "", notice: str = "", error: str = ""):
        auth = authenticated(request)
        if auth is None:
            return RedirectResponse("/auth/sign-in", 303)
        if status not in ("pending", "all") or kind not in ("", "purchase", "authentication", "clarification", "permission"):
            raise AiclError("validation_failed", "Choose an available request filter.")
        items = service.list(auth, instance_id=instance_id or None, status=status, kind=kind or None)
        item = service.get(auth, selected) if selected else (items[0] if items else None)
        # Validate selected records independently of list filters; a resolved request
        # remains visible after its response removes it from the pending list.
        agents = workflow.overview(auth)["agents"]
        notices = {
            "session_provided": "Browser session saved. The worker must check access before continuing; spending still needs separate approval.",
            "sign_in_cancelled": "Sign-in cancelled. The browser is closed and the request remains pending.",
            "session_revoked": "Saved browser access revoked. The agent will need a new sign-in if access is required again.",
            "responded": "Your response was saved. Continuation remains subject to the agent's controls.",
            "declined": "Request declined. The agent cannot use this request to proceed.",
            "payment_completed": "Payment confirmed. The saved continuation choice still applies.",
            "approved": "Purchase approved. Complete its payment authorization to continue.",
            "proposal_approved": "Proposal approved. No payment was made; this workflow stops before checkout.",
            "proposal_declined": "Proposal declined. No payment was made.",
        }
        return HTMLResponse(render("requests/inbox", title="Requests", requests=items, selected=item,
            agents=agents, status=status, kind=kind, instance_id=instance_id,
            pending_count=service.pending_count(auth), counts={}, commerce_enabled=True,
            **sidebar_context(ctx, auth), notice=notices.get(notice, ""), error=error[:400]),
            headers={"Cache-Control": "no-store"})

    @router.post("/requests/{request_id}/respond")
    async def respond(request_id: str, request: Request, auth=Depends(csrf)):
        item = service.get(auth, request_id)
        if item["kind"] == "purchase":
            raise AiclError("invalid_transition", "Review the exact purchase before authorizing it.")
        form = await request.form()
        try:
            raw_version = str(form.get("expected_version", ""))
            if not raw_version.isdigit() or len(raw_version) > 12:
                raise AiclError("validation_failed", "Reload the request before responding.")
            await run_in_threadpool(service.respond, auth, request_id, int(raw_version),
                                    answer=str(form.get("answer", "")), decision=str(form.get("decision", "")),
                                    continuation=str(form.get("continuation", item.get("continuation", "now"))))
        except AiclError as exc:
            if exc.error == "not_found":
                raise
            return RedirectResponse(request_url(request_id, error=exc.message), 303)
        notice = "declined" if form.get("decision") == "decline" else "responded"
        return RedirectResponse(request_url(request_id, notice=notice), 303)

    @router.post("/requests/{request_id}/decision")
    async def purchase_decision(request_id: str, request: Request, auth=Depends(csrf)):
        item = service.get(auth, request_id)
        if item["kind"] != "purchase":
            raise AiclError("invalid_transition", "This request does not authorize a purchase.")
        form = await request.form()
        choice = str(form.get("decision", ""))
        if item.get("proposal"):
            try:
                raw_version = str(form.get("expected_version", ""))
                if not raw_version.isdigit() or len(raw_version) > 12:
                    raise AiclError("validation_failed", "Reload the proposal before responding.")
                service.browser_proposals.decide(auth, item["proposal"]["id"], choice, int(raw_version))
            except AiclError as exc:
                if exc.error == "not_found":
                    raise
                return RedirectResponse(request_url(request_id, error=exc.message), 303)
            return RedirectResponse(request_url(request_id, notice="proposal_approved" if choice == "approve" else "proposal_declined"), 303)
        purchase_id = item["purchase_id"]
        try:
            continuation = str(form.get("continuation", "schedule"))
            linked_job = workflow.job_for_purchase(auth, purchase_id)
            if choice == "approve" and linked_job and continuation not in ("now", "schedule"):
                raise AiclError("validation_failed", "Choose Run now or Resume on schedule.")
            with ctx.db.transaction():
                current = service.get(auth, request_id)
                if str(form.get("expected_version", "")) != current["version"]:
                    raise AiclError("conflict", "This request changed. Review its latest state before responding.")
                result = commerce.decide_purchase(auth, purchase_id, choice, str(form.get("quote_digest", "")))
                if choice == "approve" and linked_job:
                    workflow.set_continuation(auth, purchase_id, continuation)
        except AiclError as exc:
            if exc.error == "not_found":
                raise
            return RedirectResponse(request_url(request_id, error=exc.message), 303)
        if choice == "approve" and result.get("order_id"):
            return RedirectResponse(f"/commerce/orders/{result['order_id']}", 303)
        return RedirectResponse(request_url(request_id, notice="declined"), 303)

    from aicl.browser.routes import browser_router
    router.include_router(browser_router(ctx, service))
    return router
