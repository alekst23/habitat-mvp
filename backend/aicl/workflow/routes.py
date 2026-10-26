"""Owner-only, CSRF-protected workflow routes. Reads never dispatch work."""

from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from aicl.commerce.factory import commerce_service
from aicl.control.csrf import require_csrf
from aicl.web.account import sidebar_context
from aicl.control.errors import AiclError
from aicl.workflow.factory import workflow_service
from aicl.workflow.pages import render
from aicl.browser.task_config import BROWSER_SCENARIO, browser_purchase_preset


NOTICES = {
    "saved": "Configuration saved. Future scheduled jobs will use these goals and criteria.",
    "example_saved": "PocketPlan app marketing example saved. Review the goals and criteria, then set controls and funding before enabling the schedule.",
    "browser_example_saved": "Browser purchase workflow saved. Add your game details, review the website and budget, then enable the schedule. Sign-in is requested only when needed; checkout stays blocked.",
    "enabled": "Schedule enabled. The next occurrence is shown below.",
    "paused": "Schedule paused. Previous requests and deliverables remain available in Audit.",
    "advanced": "Scheduled occurrence processed. Review the jobs and outputs below.",
    "accepted": "Deliverable accepted. This version remains in your history.",
    "changes_requested": "Feedback saved. A revision is queued for the next eligible scheduled run.",
    "declined": "Purchase declined. No merchant payment was made.",
    "refreshed": "Proposal refreshed. Review the new quote before approving it.",
    "payment_completed": "Payment completed. Review the purchase status below; current controls still apply.",
    "continuation_saved": "Continuation choice saved. Current schedule and AICL controls still apply.",
}

STATUS_OPTIONS = {
    "purchases": [("", "All requests"), ("pending", "Pending decisions & payment"),
                  ("awaiting_approval", "Awaiting approval"), ("awaiting_checkout", "Checkout ready"),
                  ("payment_pending", "Payment pending"), ("paid", "Paid"),
                  ("declined", "Declined"), ("cancelled", "Cancelled"), ("expired", "Expired")],
    "deliverables": [("", "All outputs"), ("submitted", "Submitted for review"), ("accepted", "Accepted"),
                     ("needs_work", "Needs work"), ("changes_requested", "Changes requested"),
                     ("completed", "Earlier completed tasks")],
}


def _audit_filter(data: dict, view: str, status: str, date_from: str, date_to: str):
    """Filter visible read projections only; summary balances remain current/all-time."""
    choices = STATUS_OPTIONS.get(view, [])
    status = status if status in {key for key, _ in choices} else ""
    dates, error = [], ""
    for raw in (date_from, date_to):
        try:
            if raw and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                raise ValueError()
            dates.append(date.fromisoformat(raw) if raw else None)
        except ValueError:
            dates.append(None)
            error = "Enter dates in YYYY-MM-DD format."
    start, end = dates
    if start and end and start > end:
        error = "The start date must be on or before the end date."
    date_from, date_to = start.isoformat() if start else "", end.isoformat() if end else ""

    def in_range(row):
        if error or (not start and not end):
            return True
        try:
            created = datetime.fromisoformat(str(row.get("created_at") or row.get("occurred_at") or "").replace("Z", "+00:00"))
            day = created.astimezone(ZoneInfo("America/New_York")).date()
            return (not start or day >= start) and (not end or day <= end)
        except ValueError:
            return False

    result = {**data}
    for key in ("cost_rows", "events", "purchases", "deliverables", "campaigns"):
        result[key] = [row for row in data.get(key, []) if in_range(row)]
    if status and view == "purchases":
        def matches(row):
            state = "expired" if row.get("expired") else row["state"]
            return state in ("awaiting_approval", "awaiting_checkout", "payment_pending") if status == "pending" else state == status
        result["purchases"] = [row for row in result["purchases"] if matches(row)]
    elif status and view == "deliverables":
        result["deliverables"] = [row for row in result["deliverables"] if row["state"] == status]
    return result, status, date_from, date_to, error


def _integer(value: object) -> int:
    if not re.fullmatch(r"[0-9]{1,12}", str(value)):
        raise AiclError("validation_failed", "The form version is invalid. Reload and try again.")
    return int(str(value))


def _configuration(form) -> dict:
    names = form.getlist("deliverable_name")
    fields = {key: form.getlist("deliverable_" + key) for key in ("key", "description", "criteria")}
    if len(names) > 6 or any(len(values) != len(names) for values in fields.values()):
        raise AiclError("validation_failed", "Check the deliverable fields and try again.")
    specs = []
    for index, name in enumerate(names):
        name = str(name).strip()
        description = str(fields["description"][index]).strip()
        criteria = [line.strip() for line in str(fields["criteria"][index]).splitlines() if line.strip()]
        if not name and not description and not criteria:
            continue  # The optional extra deliverable remains empty until the owner supplies it.
        specs.append({
            "key": str(fields["key"][index]), "name": name, "description": description,
            "criteria": criteria, "purchase_required": form.get(f"purchase_required_{index}") == "on",
            "validation_scenario": str(form.get(f"validation_scenario_{index}", "pass")),
        })
    result = {"goal": str(form.get("goal", "")).strip(), "inputs": str(form.get("inputs", "")).strip(),
            "deliverables": specs, "cadence": str(form.get("cadence", "daily")),
            "timezone": str(form.get("timezone", "America/New_York")),
            "scenario": str(form.get("scenario", "generic"))}
    if result["scenario"] == "general":
        result["tools"] = [str(value) for value in form.getlist("tools")]
    if result["scenario"] == BROWSER_SCENARIO:
        raw_amount = str(form.get("browser_max_amount", "")).strip()
        if not re.fullmatch(r"[0-9]{1,5}(?:\.[0-9]{1,2})?", raw_amount):
            raise AiclError("validation_failed", "Enter a maximum purchase amount in USD, such as 25.00.")
        dollars, _, cents = raw_amount.partition(".")
        result["browser_task"] = {"service_url": str(form.get("browser_service_url", "")).strip(),
                                  "objective": str(form.get("browser_objective", "")).strip(),
                                  "max_amount_minor": int(dollars) * 100 + int(cents.ljust(2, "0")),
                                  "currency": "USD"}
    return result


def workflow_router(ctx) -> APIRouter:
    router = APIRouter()
    if not ctx.settings.workflow_enabled:
        return router

    local_controls = APIRouter()

    service = workflow_service(ctx)
    commerce = commerce_service(ctx)
    csrf = require_csrf(ctx)

    def authenticated(request: Request):
        return ctx.auth_provider.resolve(dict(request.cookies))

    def back(instance_id: str, *, notice: str = "", error: str = ""):
        query = urlencode({key: value for key, value in (("notice", notice), ("error", error)) if value})
        return RedirectResponse(f"/instances/{instance_id}/workflow" + ("?" + query if query else ""), 303)

    def audit_back(view: str, *, instance_id: str = "", notice: str = "", error: str = "", anchor: str = ""):
        query = urlencode({key: value for key, value in (("view", view), ("instance_id", instance_id), ("notice", notice), ("error", error)) if value})
        return RedirectResponse("/audit?" + query + ("#" + anchor if anchor else ""), 303)

    def workflow_page(auth, instance_id: str, *, notice: str = "", error: str = "", values: dict | None = None,
                      status_code: int = 200):
        cfg = {**service.config(auth, instance_id), "inference_mode": ctx.settings.inference_mode,
               "execution_mode": ctx.settings.workflow_execution_mode}
        overview = service.overview(auth, instance_id)
        from aicl.owner_requests.factory import owner_request_service
        pending_requests = owner_request_service(ctx).list(auth, instance_id=instance_id)
        agent = next((a for a in overview["agents"] if a["id"] == instance_id), {})
        if values is not None:
            cfg = {**cfg, **values}
        return HTMLResponse(render("workflow/config", title=agent.get("name", "Agent workflow"), cfg=cfg,
                                   pending_requests=pending_requests, agent_pending_count=len(pending_requests),
                                   agent=agent, overview=overview, notice=NOTICES.get(notice, ""), error=error,
                                   **sidebar_context(ctx, auth)), status_code=status_code)

    @router.get("/instances/{instance_id}/workflow", response_class=HTMLResponse)
    def configure_page(instance_id: str, request: Request, notice: str = "", error: str = ""):
        auth = authenticated(request)
        if auth is None:
            return RedirectResponse("/", 303)
        return workflow_page(auth, instance_id, notice=notice, error=error[:400])

    @router.post("/instances/{instance_id}/workflow/config")
    async def configure(instance_id: str, request: Request, auth=Depends(csrf)):
        service.config(auth, instance_id)  # Check ownership even when form validation fails.
        form = await request.form()
        values = None
        try:
            values = _configuration(form)
            service.save_config(auth, instance_id, values, _integer(form.get("expected_version", "")))
        except AiclError as exc:
            if exc.error == "not_found":
                raise
            return workflow_page(auth, instance_id, values=values, error=exc.message or "Check the configuration.",
                                 status_code=409 if exc.error == "conflict" else 422)
        return back(instance_id, notice="saved")

    @router.post("/instances/{instance_id}/workflow/example")
    async def use_example(instance_id: str, request: Request, auth=Depends(csrf)):
        cfg = service.config(auth, instance_id)
        form = await request.form()
        example = str(form.get("example", "pocketplan_ads"))
        try:
            if example not in ("pocketplan_ads", BROWSER_SCENARIO):
                raise AiclError("validation_failed", "Choose an available workflow example.")
            if cfg["saved"]:
                raise AiclError("conflict", "This agent already has a saved workflow. Create a new agent to try another workflow example.")
            from aicl.workflow.ad_scenario import pocketplan_preset
            preset = browser_purchase_preset() if example == BROWSER_SCENARIO else pocketplan_preset()
            service.save_config(auth, instance_id, preset, _integer(form.get("expected_version", "")))
        except AiclError as exc:
            if exc.error == "not_found":
                raise
            return back(instance_id, error=exc.message or "The example could not be saved.")
        return back(instance_id, notice="browser_example_saved" if example == BROWSER_SCENARIO else "example_saved")

    @router.post("/instances/{instance_id}/workflow/schedule")
    async def schedule(instance_id: str, request: Request, auth=Depends(csrf)):
        service.config(auth, instance_id)
        form = await request.form()
        enabled = str(form.get("enabled", ""))
        try:
            if enabled not in ("true", "false"):
                raise AiclError("validation_failed", "Choose whether to enable or pause the schedule.")
            service.schedule(auth, instance_id, enabled == "true",
                             expected_version=_integer(form.get("expected_version", "")),
                             expected_instance_version=_integer(form.get("expected_instance_version", "")))
        except AiclError as exc:
            if exc.error == "not_found":
                raise
            return back(instance_id, error=exc.message or "The schedule could not be updated.")
        return back(instance_id, notice="enabled" if enabled == "true" else "paused")

    @local_controls.post("/instances/{instance_id}/workflow/advance")
    async def advance(instance_id: str, request: Request, auth=Depends(csrf)):
        service.config(auth, instance_id)
        form = await request.form()
        try:
            await run_in_threadpool(service.advance, auth, instance_id, str(form.get("expected_due", "")))
        except AiclError as exc:
            if exc.error == "not_found":
                raise
            return back(instance_id, error=exc.message or "The scheduled occurrence could not be processed.")
        return back(instance_id, notice="advanced")

    @router.get("/audit", response_class=HTMLResponse)
    def audit_page(request: Request, view: str = "costs", instance_id: str = "", notice: str = "", error: str = "",
                   status: str = "", date_from: str = "", date_to: str = ""):
        auth = authenticated(request)
        if auth is None:
            return RedirectResponse("/", 303)
        view = view if view in ("costs", "actions", "purchases", "deliverables", "campaigns") else "costs"
        data = {**service.overview(auth, instance_id or None), "inference_mode": ctx.settings.inference_mode}
        data["has_general_agents"] = any(agent.get("scenario") == "general" for agent in data["agents"])
        agents = service.overview(auth)["agents"] if instance_id else data["agents"]
        pending_count = sum(p["state"] in ("awaiting_approval", "awaiting_checkout", "payment_pending") for p in data["purchases"])
        data, status, date_from, date_to, filter_error = _audit_filter(data, view, status, date_from, date_to)
        return HTMLResponse(render("workflow/audit", title="Audit", d=data, agents=agents, view=view,
                                   instance_id=instance_id, notice=NOTICES.get(notice, ""), error=filter_error or error[:400],
                                   status=status, status_options=STATUS_OPTIONS.get(view, []), date_from=date_from,
                                   date_to=date_to, filters_active=bool(status or date_from or date_to),
                                   pending_purchase_count=pending_count,
                                   **sidebar_context(ctx, auth)))

    @router.get("/audit/jobs/{run_id}", response_class=HTMLResponse)
    def job_page(run_id: str, request: Request):
        auth = authenticated(request)
        if auth is None:
            return RedirectResponse("/", 303)
        item = service.job(auth, run_id)
        return HTMLResponse(render("workflow/job", title=item["deliverable_name"], job=item,
                                   **sidebar_context(ctx, auth)))

    @router.get("/audit/deliverables/{deliverable_id}", response_class=HTMLResponse)
    def deliverable_page(deliverable_id: str, request: Request, notice: str = "", error: str = ""):
        auth = authenticated(request)
        if auth is None:
            return RedirectResponse("/", 303)
        item = service.deliverable(auth, deliverable_id)
        return HTMLResponse(render("workflow/deliverable", title=item["name"], item=item,
                                   notice=NOTICES.get(notice, ""), error=error[:400],
                                   **sidebar_context(ctx, auth)))

    @router.post("/audit/deliverables/{deliverable_id}/review")
    async def review(deliverable_id: str, request: Request, auth=Depends(csrf)):
        item = service.deliverable(auth, deliverable_id)
        form = await request.form()
        choice = str(form.get("decision", ""))
        try:
            service.review(auth, deliverable_id, choice, str(form.get("feedback", "")),
                           _integer(form.get("expected_version", "")))
        except AiclError as exc:
            if exc.error == "not_found":
                raise
            return RedirectResponse(f"/audit/deliverables/{deliverable_id}?" + urlencode({"instance_id": item["instance_id"], "error": exc.message or "Review could not be saved."}), 303)
        notice = "accepted" if choice == "accept" else "changes_requested"
        return RedirectResponse(f"/audit/deliverables/{deliverable_id}?" + urlencode({"instance_id": item["instance_id"], "notice": notice}), 303)

    @router.post("/audit/purchases/{purchase_id}/decision")
    async def decision(purchase_id: str, request: Request, auth=Depends(csrf)):
        purchase = commerce.purchase(auth, purchase_id)
        form = await request.form()
        choice = str(form.get("decision", ""))
        try:
            continuation = str(form.get("continuation", "schedule"))
            linked_job = service.job_for_purchase(auth, purchase_id)
            if choice == "approve" and linked_job and continuation not in ("now", "schedule"):
                raise AiclError("validation_failed", "Choose Run now or Resume on schedule.")
            result = commerce.decide_purchase(auth, purchase_id, choice, str(form.get("quote_digest", "")))
            # Exact quote authorization must succeed before a continuation can
            # execute paid work (including a stale approval form submitted again).
            if choice == "approve" and linked_job:
                service.set_continuation(auth, purchase_id, continuation)
        except AiclError as exc:
            if exc.error == "not_found":
                raise
            return audit_back("purchases", instance_id=purchase["instance_id"], error=exc.message or "The purchase decision could not be saved.", anchor="purchase-" + purchase_id)
        if choice == "approve" and result.get("order_id"):
            return RedirectResponse(f"/commerce/orders/{result['order_id']}", 303)
        return audit_back("purchases", instance_id=purchase["instance_id"], notice="declined", anchor="purchase-" + purchase_id)

    @router.post("/audit/purchases/{purchase_id}/refresh")
    def refresh(purchase_id: str, auth=Depends(csrf)):
        purchase = commerce.purchase(auth, purchase_id)
        try:
            service.refresh_purchase(auth, purchase_id)
        except AiclError as exc:
            if exc.error == "not_found":
                raise
            return audit_back("purchases", instance_id=purchase["instance_id"], error=exc.message or "The proposal could not be refreshed.")
        return audit_back("purchases", instance_id=purchase["instance_id"], notice="refreshed")

    @router.post("/audit/purchases/{purchase_id}/continuation")
    async def continuation(purchase_id: str, request: Request, auth=Depends(csrf)):
        purchase = commerce.purchase(auth, purchase_id)
        form = await request.form()
        try:
            service.set_continuation(auth, purchase_id, str(form.get("continuation", "schedule")))
        except AiclError as exc:
            if exc.error == "not_found":
                raise
            return audit_back("purchases", instance_id=purchase["instance_id"], error=exc.message or "The continuation could not be updated.", anchor="purchase-" + purchase_id)
        return audit_back("purchases", instance_id=purchase["instance_id"], notice="continuation_saved", anchor="purchase-" + purchase_id)

    if ctx.settings.workflow_execution_mode == "local":
        router.include_router(local_controls)
    return router
