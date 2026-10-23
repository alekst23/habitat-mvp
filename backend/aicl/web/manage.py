"""Management pages and form routes (aicl-experience/technical.md, owner E11-5).

Every page redirects an unauthenticated visitor to `/`; every POST uses the shared E11-1 `require_csrf` dependency
(urlencoded forms carry `csrf_token`, which `FormCsrfShim` copies into `X-CSRF-Token`). No route reads a tenant or
owner from the client. Mutation forms post the page's `expected_version` to the E11-2 `InstanceOperations`, then
redirect to the committed instance, or render the structured denial. `GET /workspace` is rendered by the E11-3
web router from `WorkspaceView`.
"""

from __future__ import annotations

from dataclasses import dataclass
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from markupsafe import Markup

from aicl.commerce.pages import FAILURES as COMMERCE_FAILURES, NOTICES as COMMERCE_NOTICES
from aicl.commerce.factory import commerce_service as build_commerce_service
from aicl.connections.models import CAPABILITY_SCOPES
from aicl.control.csrf import require_csrf
from aicl.control.errors import ERROR_HTTP_STATUS, AiclError
from aicl.creation.operations import LIMIT_FIELDS, SqliteInstanceOperations
from aicl.creation.service import validation_failed
from aicl.web.manage_pages import NOTICES, render
from aicl.web.views import SqliteProjectionService, format_usd, parse_usd


@dataclass(frozen=True)
class ManagementRoute:
    method: str
    path: str
    calls: str  # the existing operation the route delegates to


MANAGEMENT_ROUTES: tuple[ManagementRoute, ...] = (
    ManagementRoute("GET", "/instances/{instance_id}", "ProjectionService.instance_detail"),
    ManagementRoute("GET", "/connections", "ProjectionService.connections"),
    ManagementRoute("POST", "/instances/{instance_id}/lifecycle", "InstanceOperations.set_lifecycle"),
    ManagementRoute("POST", "/instances/{instance_id}/capabilities", "InstanceOperations.set_capability"),
    ManagementRoute("POST", "/instances/{instance_id}/limits", "InstanceOperations.set_limits"),
    ManagementRoute("POST", "/instances/{instance_id}/domains", "InstanceOperations.add_network_domain"),
    ManagementRoute("POST", "/instances/{instance_id}/domains/remove", "InstanceOperations.remove_network_domain"),
    ManagementRoute("POST", "/instances/{instance_id}/attachments", "InstanceOperations.attach_connection"),
    ManagementRoute("POST", "/instances/{instance_id}/attachments/detach", "InstanceOperations.detach_connection"),
    ManagementRoute("POST", "/instances/{instance_id}/resolve-gate", "InstanceOperations.resolve_gate"),
    ManagementRoute("POST", "/connections/{connection_id}/revoke", "ConnectionService.revoke_connection"),
)

LIFECYCLE_ACTIONS = {"draft": (("activate", "Activate"), ("archive", "Archive")),
                     "active": (("pause", "Pause"), ("archive", "Archive")),
                     "paused": (("resume", "Resume"), ("archive", "Archive")),
                     "archived": ()}
LIMIT_LABELS = (("inference_daily_micro_usd", "Inference daily"), ("inference_monthly_micro_usd", "Inference monthly"),
                ("compute_daily_micro_usd", "Compute daily"), ("compute_monthly_micro_usd", "Compute monthly"))


def manage_router(ctx) -> APIRouter:
    """`(AppContext) -> APIRouter` factory in the ROUTE_FACTORIES shape."""
    from aicl import wiring

    router = APIRouter()
    csrf = require_csrf(ctx)
    projections = SqliteProjectionService(ctx.db, ctx.clock, ctx.settings.hold_stale_seconds)
    operations = SqliteInstanceOperations(ctx.db, ctx.clock, ctx.settings.hold_stale_seconds)
    commerce_service = (build_commerce_service(ctx)
                        if ctx.settings.workflow_enabled else None)

    def signed_in(request: Request):
        return ctx.auth_provider.resolve(dict(request.cookies))

    def hidden_fields(auth, version: int | None = None) -> Markup:
        token = ctx.csrf_verifier.token_for(auth.session_id)
        fields = Markup('<input type="hidden" name="csrf_token" value="{}">').format(token)
        if version is not None:
            fields += Markup('<input type="hidden" name="expected_version" value="{}">').format(int(version))
        return fields

    def detail_page(auth, instance_id: str, status: int = 200, error: AiclError | None = None, notice: str = "",
                    posted: dict | None = None, commerce_feedback: dict | None = None) -> HTMLResponse:
        detail = projections.instance_detail(auth, instance_id)
        snap = detail.snapshot
        limits = {f: format_usd(getattr(snap.limits, f)) for f in LIMIT_FIELDS}
        limits.update(posted or {})
        rows = []
        for capability, enabled in snap.capabilities.items():
            spec = CAPABILITY_SCOPES.get(capability)
            if spec is None or not enabled:
                continue
            attached = next((a for a in snap.attachments if a.capability == capability), None)
            options = [] if attached else [c for c in projections.store.list_connections(auth)
                                           if c.provider == spec[0] and c.status == "active"]
            rows.append({"capability": capability, "attached": attached, "options": options})
        gate_guidance = {
            "budget_exhausted": "Adjust all four limits in Budget below. Saving re-checks the gate automatically; limits are not a funded balance.",
            "capability_disabled": "Enable the required capability below. Saving re-checks this gate automatically.",
            "connection_revoked": "Connect an account again and attach it to the affected capability below. Attaching re-checks this gate automatically.",
            "connection_unavailable": "Attach an active connection to the affected capability below. Attaching re-checks this gate automatically.",
            "connection_reauthorization_required": "Authorize the connection again, then attach it to the affected capability below.",
            "network_denied": "Review the HTTPS destination and allowed domains below. Saving an allowed domain re-checks this gate automatically.",
        }.get(snap.gated_reason, "Review the affected control and activity below. Correct the cause before re-checking this gate.")
        work_disabled = snap.lifecycle != "active" or snap.status == "gated" or not any(snap.capabilities.values())
        if snap.lifecycle != "active":
            work_guidance = {
                "draft": "Activate this draft in Purpose & controls before running a test. Set its budgets and permissions first.",
                "paused": "This agent is paused. Resume it in Purpose & controls before running another test.",
                "archived": "This agent is archived. Its history is available, but it cannot run again.",
            }[snap.lifecycle]
        elif snap.status == "gated":
            work_guidance = gate_guidance if snap.gated_reason else "An outstanding request is being reconciled. Review Activity; its reservation remains held."
        elif not any(snap.capabilities.values()):
            work_guidance = "Enable at least one capability below and save it before running a test."
        elif any(amount.available <= 0 for windows in detail.budget.windows.values() for amount in windows.values()):
            work_guidance = "A budget window has no available allowance. Set all four limits in Budget below, or run a control test to see the request denied."
        else:
            work_guidance = "Control test available. Every request still checks the selected capability, connections and all four budget windows."
        capability_guidance = {"inference": "Checks inference permission and compute limits; this test uses zero inference tokens.",
                               "network.fetch": "Enter an HTTPS destination to check against your network policy."}
        for row in rows:
            if not row["attached"] or row["attached"].connection_status != "active":
                capability_guidance[row["capability"]] = "Attach an active connection below before testing this capability."
            elif row["capability"] in ("gmail.send", "reddit.post"):
                capability_guidance[row["capability"]] = "This outbound control test requires your confirmation before it can proceed."
            else:
                capability_guidance[row["capability"]] = "Checks access through the attached connection."
        err = None if error is None else {"error": error.error, "message": error.message,
                                          "reason": error.extra.get("reason"),
                                          "current_version": error.extra.get("current_version"),
                                          "field_errors": error.extra.get("field_errors") or []}
        commerce = commerce_service.dashboard(auth, instance_id) if commerce_service else None
        if commerce and not snap.capabilities.get("inference") and not any(
                item["reason"] == "capability_disabled" for item in commerce["readiness"]["blockers"]):
            commerce["readiness"]["blockers"].append({"reason": "capability_disabled",
                                                       "message": "Enable inference before continuing."})
            commerce["readiness"]["ready"] = False
        html = render("instance", title=snap.name, d=detail, usd=format_usd, error=err, notice=notice,
                      commerce=commerce, commerce_feedback=commerce_feedback,
                      execution_mode=ctx.settings.workflow_execution_mode,
                      commerce_request_id=str(uuid.uuid4()),
                      work_disabled=work_disabled, work_guidance=work_guidance, gate_guidance=gate_guidance,
                      capability_guidance=capability_guidance, actions=LIFECYCLE_ACTIONS[snap.lifecycle], limit_fields=LIMIT_LABELS, limit_values=limits,
                      attach_rows=rows, hidden=hidden_fields(auth, snap.version),
                      csrf=ctx.csrf_verifier.token_for(auth.session_id))
        return HTMLResponse(html, status_code=status)

    @router.get("/instances/{instance_id}", response_class=HTMLResponse)
    def instance_page(instance_id: str, request: Request, notice: str = "", commerce_notice: str = "",
                      commerce_failure: str = "", commerce_section: str = "funding"):
        auth = signed_in(request)
        if auth is None:
            return RedirectResponse("/", status_code=303)
        feedback = {"notice": COMMERCE_NOTICES.get(commerce_notice, ""),
                    "failure": COMMERCE_FAILURES.get(commerce_failure, ""),
                    "section": commerce_section if commerce_section in ("budgets", "funding", "task") else "funding"}
        return detail_page(auth, instance_id, notice=NOTICES.get(notice, ""),
                           commerce_feedback=feedback if commerce_service else None)

    @router.get("/connections", response_class=HTMLResponse)
    def connections_page(request: Request, oauth: str = "", notice: str = ""):
        auth = signed_in(request)
        if auth is None:
            return RedirectResponse("/", status_code=303)
        key = oauth if oauth in ("connected", "denied") else notice
        return HTMLResponse(render("connections", title="Connections", view=projections.connections(auth),
                                   notice=NOTICES.get(key, ""), hidden=hidden_fields(auth),
                                   csrf=ctx.csrf_verifier.token_for(auth.session_id)))

    async def form_values(request: Request) -> tuple[dict, int]:
        form = await request.form()  # tenant_id / owner_id fields, if any, are never read
        values = {k: str(v) for k, v in form.multi_items()}
        try:
            version = int(values.get("expected_version", ""))
        except ValueError:
            raise validation_failed(("expected_version", "invalid")) from None
        return {"_multi": form.getlist("capabilities"), **values}, version

    def respond(auth, instance_id: str, action, notice: str = "saved", posted: dict | None = None):
        try:
            action()
        except AiclError as exc:
            if exc.error in ("not_found", "unauthenticated") or exc.error == "unavailable":
                raise
            return detail_page(auth, instance_id, ERROR_HTTP_STATUS[exc.error], error=exc, posted=posted)
        return RedirectResponse(f"/instances/{instance_id}?notice={notice}", status_code=303)

    @router.post("/instances/{instance_id}/lifecycle")
    async def lifecycle(instance_id: str, request: Request, auth=Depends(csrf)):
        values, version = await form_values(request)
        return respond(auth, instance_id, lambda: operations.set_lifecycle(
            auth, instance_id, version, values.get("action", "")))  # type: ignore[arg-type]

    @router.post("/instances/{instance_id}/capabilities")
    async def capabilities(instance_id: str, request: Request, auth=Depends(csrf)):
        values, version = await form_values(request)

        def apply() -> None:
            if "capability" in values:  # single toggle
                operations.set_capability(auth, instance_id, version, values["capability"],
                                          values.get("enabled", "") == "true")
                return
            wanted = set(values["_multi"])
            current = projections.instance_detail(auth, instance_id).snapshot
            expected = version
            for name, on in current.capabilities.items():
                if on != (name in wanted):
                    expected = operations.set_capability(auth, instance_id, expected, name, name in wanted).instance.version
        return respond(auth, instance_id, apply)

    @router.post("/instances/{instance_id}/limits")
    async def limits(instance_id: str, request: Request, auth=Depends(csrf)):
        from aicl.control.instances import Limits
        values, version = await form_values(request)
        parsed, errors = {}, []
        for field in LIMIT_FIELDS:
            usd_field = field.replace("_micro_usd", "_usd")
            try:
                parsed[field] = parse_usd(values.get(field) or values.get(usd_field, ""))
            except AiclError as exc:
                errors.append((field, exc.extra["field_errors"][0]["code"]))
        posted = {f: values.get(f) or values.get(f.replace("_micro_usd", "_usd"), "") for f in LIMIT_FIELDS}

        def apply() -> None:
            if errors:
                raise validation_failed(*errors)
            operations.set_limits(auth, instance_id, version, Limits(**parsed))
        return respond(auth, instance_id, apply, posted=posted)

    @router.post("/instances/{instance_id}/domains")
    async def add_domain(instance_id: str, request: Request, auth=Depends(csrf)):
        values, version = await form_values(request)
        return respond(auth, instance_id, lambda: operations.add_network_domain(
            auth, instance_id, version, values.get("host", "").strip().lower()))  # form input: trim and lowercase

    @router.post("/instances/{instance_id}/domains/remove")
    async def remove_domain(instance_id: str, request: Request, auth=Depends(csrf)):
        values, version = await form_values(request)
        return respond(auth, instance_id, lambda: operations.remove_network_domain(
            auth, instance_id, version, values.get("host", "")))

    @router.post("/instances/{instance_id}/attachments")
    async def attach(instance_id: str, request: Request, auth=Depends(csrf)):
        values, version = await form_values(request)
        return respond(auth, instance_id, lambda: operations.attach_connection(
            auth, instance_id, version, values.get("capability", ""), values.get("connection_id", "")))

    @router.post("/instances/{instance_id}/attachments/detach")
    async def detach(instance_id: str, request: Request, auth=Depends(csrf)):
        values, version = await form_values(request)
        return respond(auth, instance_id, lambda: operations.detach_connection(
            auth, instance_id, version, values.get("capability", "")))

    @router.post("/instances/{instance_id}/resolve-gate")
    async def resolve_gate(instance_id: str, request: Request, auth=Depends(csrf)):
        values, version = await form_values(request)
        return respond(auth, instance_id, lambda: operations.resolve_gate(auth, instance_id, version), "cleared")

    @router.post("/connections/{connection_id}/revoke")
    async def revoke(connection_id: str, auth=Depends(csrf)):
        wiring.connection_service(ctx).revoke_connection(auth, connection_id)
        return RedirectResponse("/connections?notice=revoked", status_code=303)

    return router
