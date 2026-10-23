"""Owner-only commerce actions for mock payments and PayPal Sandbox."""

from __future__ import annotations

import re
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from aicl.commerce.pages import FAILURES, NOTICES, render
from aicl.commerce.factory import commerce_service
from aicl.commerce.buyers import DEMO_BUYERS
from aicl.control.csrf import require_csrf
from aicl.web.account import sidebar_context
from aicl.control.errors import AiclError
from aicl.db import to_iso
from aicl.workflow.factory import workflow_service


def _integer(value: str) -> int:
    if not re.fullmatch(r"[0-9]{1,12}", value):
        raise AiclError("validation_failed", "Enter a valid whole number.")
    return int(value)


def _minor_usd(value: str) -> int:
    match = re.fullmatch(r"([0-9]{1,8})(?:\.([0-9]{1,2}))?", value.strip())
    if match is None:
        raise AiclError("validation_failed", "Enter USD with at most two decimal places.")
    return int(match[1]) * 100 + int((match[2] or "").ljust(2, "0") or "0")


def commerce_router(ctx) -> APIRouter:
    router = APIRouter()
    # Hosted owner payment forms do not enable test authentication or scheduler bypasses.
    if not ctx.settings.workflow_enabled:
        return router

    local_controls = APIRouter()

    service = commerce_service(ctx)
    workflow = workflow_service(ctx)
    csrf = require_csrf(ctx)

    def authenticated(request: Request):
        return ctx.auth_provider.resolve(dict(request.cookies))

    def back(instance_id: str, *, notice: str = "", failure: str = "", section: str = "funding", run_id: str = ""):
        suffix = urlencode({k: v for k, v in (("commerce_notice", notice), ("commerce_failure", failure)) if v})
        if suffix:
            suffix += "&" + urlencode({"commerce_section": section})
        anchor = f"run-{run_id}" if run_id else section
        return RedirectResponse(f"/instances/{instance_id}" + ("?" + suffix if suffix else "") + f"#{anchor}", 303)

    def failed(instance_id: str, exc: AiclError, section: str = "funding"):
        if exc.error == "not_found":
            raise exc
        reason = str(exc.extra.get("reason") or exc.error)
        return back(instance_id, failure=reason if reason in FAILURES else "action_failed", section=section)

    def payment_destination(auth, order):
        if order["state"] == "completed":
            if order.get("purchase_id"):
                job = workflow.payment_completed(auth, order)
                return RedirectResponse(
                    "/requests?" + urlencode({"selected": "purchase:" + order["purchase_id"],
                                              "notice": "payment_completed"}), 303)
            return back(order["instance_id"], notice="funding_completed", section="setup")
        return RedirectResponse(f"/commerce/orders/{order['id']}", 303)

    def checkout_failure(order_id, exc):
        if exc.error == "not_found":
            raise exc
        reason = str(exc.extra.get("reason") or exc.error)
        return RedirectResponse(f"/commerce/orders/{order_id}?" + urlencode({
            "failure": reason if reason in FAILURES else "action_failed"}), 303)

    @router.get("/instances/{instance_id}/commerce", response_class=HTMLResponse)
    def dashboard(instance_id: str, request: Request, notice: str = "", failure: str = ""):
        auth = authenticated(request)
        if auth is None:
            return RedirectResponse("/", 303)
        service.dashboard(auth, instance_id)  # Authenticate ownership before redirecting the legacy URL.
        return back(instance_id, notice=notice if notice in NOTICES else "",
                    failure=failure if failure in FAILURES else "")

    @router.post("/instances/{instance_id}/commerce/settings")
    async def configure(instance_id: str, request: Request, auth=Depends(csrf)):
        form = await request.form()
        try:
            service.configure(auth, instance_id, form.get("enabled") == "on",
                              _minor_usd(str(form.get("purchase_limit", ""))),
                              _integer(str(form.get("expected_version", ""))))
        except AiclError as exc:
            return failed(instance_id, exc, "budgets")
        return back(instance_id, notice="settings_saved", section="budgets")

    @router.post("/instances/{instance_id}/commerce/topups")
    async def topup(instance_id: str, request: Request, auth=Depends(csrf)):
        form = await request.form()
        try:
            order = service.create_topup(auth, instance_id, _integer(str(form.get("amount_minor", ""))),
                                         str(form.get("request_id", "")))
        except AiclError as exc:
            return failed(instance_id, exc)
        return RedirectResponse(f"/commerce/orders/{order['id']}", 303)

    @router.post("/instances/{instance_id}/commerce/brief")
    async def save_brief(instance_id: str, request: Request, auth=Depends(csrf)):
        form = await request.form()
        try:
            service.save_brief(auth, instance_id,
                               {key: str(form.get(key, "")).replace("\r\n", "\n")
                                for key in ("product_name", "audience", "goal")},
                               _integer(str(form.get("expected_version", ""))))
        except AiclError as exc:
            return failed(instance_id, exc, "task")
        return back(instance_id, notice="brief_saved", section="task")

    def render_checkout(auth, order_id: str, *, failure: str = "", paypal_return: str = ""):
        order = service.order(auth, order_id)
        purchase = service.purchase(auth, order["purchase_id"]) if order.get("purchase_id") else None
        workflow_job = workflow.job_for_purchase(auth, purchase["id"]) if purchase else None
        return HTMLResponse(render(
            "checkout", title="Checkout", order=order, purchase=purchase,
            run=service.run(auth, purchase["run_id"]) if purchase else None,
            workflow_job=workflow_job,
            request_url=("/requests?" + urlencode({"selected": "purchase:" + purchase["id"]})) if purchase else "",
            buyer_choices=DEMO_BUYERS,
            paypal_return=paypal_return,
            paypal_approval_expired=bool(order.get("is_paypal_sandbox") and purchase
                                         and purchase["expires_at"] <= to_iso(ctx.clock.now())),
            **sidebar_context(ctx, auth), failure=FAILURES.get(failure, "")))

    @router.get("/commerce/orders/{order_id}", response_class=HTMLResponse)
    def checkout_page(order_id: str, request: Request, failure: str = ""):
        auth = authenticated(request)
        if auth is None:
            return RedirectResponse("/", 303)
        return render_checkout(auth, order_id, failure=failure)

    def require_sandbox(order):
        if order.get("payment_transport") != "paypal_sandbox":
            raise AiclError("invalid_transition", "This order does not use PayPal Sandbox.")

    @router.post("/commerce/orders/{order_id}/paypal-start")
    async def paypal_start(order_id: str, auth=Depends(csrf)):
        order = service.order(auth, order_id)
        try:
            require_sandbox(order)
            result = await run_in_threadpool(service.begin_paypal_checkout, auth, order_id)
        except AiclError as exc:
            return checkout_failure(order_id, exc)
        # Only the adapter's verified PayPal approval URL can leave this application.
        if result.get("approval_url") and result["state"] not in ("completed", "cancelled"):
            return RedirectResponse(result["approval_url"], 303)
        return payment_destination(auth, result)

    def paypal_return_page(order_id: str, request: Request, token: str, *, cancelled: bool):
        auth = authenticated(request)
        if auth is None:
            return RedirectResponse("/", 303)
        order = service.order(auth, order_id)
        try:
            require_sandbox(order)
            if not token or token != order.get("provider_order_id"):
                raise AiclError("validation_failed", "The return does not match this order.",
                                reason="paypal_return_mismatch")
        except AiclError as exc:
            return checkout_failure(order_id, exc)
        # A redirect is not a payment result. GET never captures, credits, or cancels.
        return render_checkout(auth, order_id, paypal_return="cancelled" if cancelled else "returned")

    @router.get("/commerce/orders/{order_id}/paypal-return", response_class=HTMLResponse)
    def paypal_return(order_id: str, request: Request, token: str = ""):
        return paypal_return_page(order_id, request, token, cancelled=False)

    @router.get("/commerce/orders/{order_id}/paypal-cancel", response_class=HTMLResponse)
    def paypal_cancel_return(order_id: str, request: Request, token: str = ""):
        return paypal_return_page(order_id, request, token, cancelled=True)

    @router.post("/commerce/orders/{order_id}/paypal-complete")
    async def paypal_complete(order_id: str, request: Request, auth=Depends(csrf)):
        order = service.order(auth, order_id)
        form = await request.form()
        try:
            require_sandbox(order)
            result = await run_in_threadpool(service.complete_paypal_checkout, auth, order_id,
                                            provider_order_id=str(form.get("provider_order_id", "")),
                                            renew_approval=form.get("renew_approval") == "true",
                                            quote_digest=str(form.get("quote_digest", "")) or None)
        except AiclError as exc:
            return checkout_failure(order_id, exc)
        return payment_destination(auth, result)

    @router.post("/commerce/orders/{order_id}/paypal-cancel")
    async def paypal_cancel(order_id: str, auth=Depends(csrf)):
        order = service.order(auth, order_id)
        try:
            require_sandbox(order)
            result = await run_in_threadpool(service.cancel_paypal_checkout, auth, order_id)
        except AiclError as exc:
            return checkout_failure(order_id, exc)
        return payment_destination(auth, result)

    @router.post("/commerce/orders/{order_id}/buyer")
    async def select_buyer(order_id: str, request: Request, auth=Depends(csrf)):
        order = service.order(auth, order_id)
        form = await request.form()
        try:
            if order.get("payment_transport") == "paypal_sandbox":
                raise AiclError("invalid_transition", "Choose the buyer within PayPal checkout.")
            service.select_payment_buyer(auth, order_id, str(form.get("buyer_id", "")),
                                         expected_current_buyer_id=str(form.get("expected_buyer_id", "")) or None)
        except AiclError as exc:
            return checkout_failure(order_id, exc)
        return RedirectResponse(f"/commerce/orders/{order_id}", 303)

    @router.post("/commerce/orders/{order_id}/checkout")
    async def checkout(order_id: str, request: Request, auth=Depends(csrf)):
        # Resolve the authenticated order before any redirect or error. IDs never grant ownership.
        order = service.order(auth, order_id)
        form = await request.form()
        outcome = str(form.get("outcome", ""))
        buyer_id = str(form.get("buyer_id", "")) or None
        try:
            if order.get("payment_transport") == "paypal_sandbox":
                raise AiclError("invalid_transition", "Use the PayPal Sandbox checkout for this order.")
            if buyer_id and not order["buyer_id"] and outcome in ("complete", "pending"):
                service.select_payment_buyer(auth, order_id, buyer_id, expected_current_buyer_id=None)
            result = await run_in_threadpool(service.checkout, auth, order_id, outcome,
                                            expected_buyer_id=buyer_id if outcome != "cancel" else None)
        except AiclError as exc:
            return checkout_failure(order_id, exc)
        return payment_destination(auth, result)

    @router.post("/commerce/orders/{order_id}/reconcile")
    def reconcile_payment(order_id: str, auth=Depends(csrf)):
        service.order(auth, order_id)
        try:
            result = service.reconcile_payment(auth, order_id)
        except AiclError as exc:
            return checkout_failure(order_id, exc)
        return payment_destination(auth, result)

    @local_controls.post("/instances/{instance_id}/commerce/runs")
    async def start(instance_id: str, request: Request, auth=Depends(csrf)):
        form = await request.form()
        try:
            # Old callers may omit the brief; browser forms send the reviewed,
            # saved fields explicitly. Ownership is always derived from auth.
            brief = ({key: str(form.get(key, "")).replace("\r\n", "\n")
                      for key in ("product_name", "audience", "goal")}
                     if any(key in form for key in ("product_name", "audience", "goal")) else None)
            run = service.start_run(auth, instance_id, str(form.get("request_id", "")), brief=brief)
        except AiclError as exc:
            return failed(instance_id, exc, "task")
        return back(instance_id, notice="run_started", section="task", run_id=run["id"])

    @router.post("/commerce/purchases/{purchase_id}/decision")
    async def decision(purchase_id: str, request: Request, auth=Depends(csrf)):
        purchase = service.purchase(auth, purchase_id)
        form = await request.form()
        choice = str(form.get("decision", ""))
        try:
            result = service.decide_purchase(auth, purchase_id, choice, str(form.get("quote_digest", "")))
        except AiclError as exc:
            return failed(purchase["instance_id"], exc, "task")
        if choice == "approve" and result.get("order_id"):
            return RedirectResponse(f"/commerce/orders/{result['order_id']}", 303)
        return back(purchase["instance_id"], notice="purchase_declined",
                    section="task", run_id=purchase["run_id"])

    @local_controls.post("/commerce/runs/{run_id}/resume")
    def resume(run_id: str, auth=Depends(csrf)):
        run = service.run(auth, run_id)
        try:
            service.resume_run(auth, run_id)
        except AiclError as exc:
            return failed(run["instance_id"], exc, "task")
        return back(run["instance_id"], notice="run_completed", section="task", run_id=run_id)

    if ctx.settings.workflow_execution_mode == "local":
        router.include_router(local_controls)
    return router
