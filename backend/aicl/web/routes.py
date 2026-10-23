"""Landing, sign-in, logout, workspace shell and wizard routes (E11-3). Routes call `create_instance` and the
shared `require_csrf` dependency; they never accept a tenant or owner from the client."""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from aicl.auth.session import GENERIC_LINK_SENT, SESSION_COOKIE
from aicl.auth.judge_demo import (ENTRY_COOKIE, ENTRY_TTL_SECONDS, accept_access_link, valid_entry_token,
                                  verify_entry, start_workspace)
from aicl.control.csrf import require_csrf
from aicl.web.account import sidebar_context
from aicl.control.errors import AiclError
from aicl.control.instances import CATALOG_CAPABILITIES
from aicl.creation.models import TEMPLATE_ID_DEFAULT, CreateInstanceRequest
from aicl.creation.routes import field_errors_from
from aicl.creation.service import create_instance
from aicl.web.pages import render
from aicl.web.views import SqliteProjectionService
from aicl.workflow.factory import workflow_service


class FormCsrfShim:
    """O-1: lets a server-rendered form carry the token as a `csrf_token` field. For urlencoded POSTs without
    an `X-CSRF-Token` header it copies the field into the header; `require_csrf` still does all verification."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        if b"x-csrf-token" in headers or not headers.get(b"content-type", b"").startswith(
                b"application/x-www-form-urlencoded"):
            return await self.app(scope, receive, send)
        chunks, more = [], True
        while more:
            message = await receive()
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(chunks)
        token = parse_qs(body.decode("utf-8", "replace")).get("csrf_token", [""])[0]
        if token:
            scope = {**scope, "headers": [*scope["headers"], (b"x-csrf-token", token.encode())]}
        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        return await self.app(scope, replay, send)


def _page(template: str, status: int = 200, /, **context: object) -> HTMLResponse:
    return HTMLResponse(render(template, **context), status_code=status)


def web_router(ctx) -> APIRouter:
    router = APIRouter()
    csrf = require_csrf(ctx)
    service = ctx.sign_in
    secure = not ctx.settings.test_mode
    commerce_enabled = ctx.settings.workflow_enabled

    def signed_in(request: Request):
        return ctx.auth_provider.resolve(dict(request.cookies))

    def access_required():
        response = _page("access_required", 403, title="Private access link required")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def judge_entry(request: Request, status: int = 200, error: str | None = None):
        if signed_in(request) is not None:
            return RedirectResponse("/workspace", status_code=303,
                                    headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        token = request.cookies.get(ENTRY_COOKIE)
        if not valid_entry_token(ctx, token):
            return access_required()
        response = _page("judge_entry", status, title="Sign in", csrf=token, error=error)
        response.headers["Cache-Control"] = "no-store"
        # HTML form POSTs need their same-origin Origin header for entry CSRF checks.
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @router.get("/", response_class=HTMLResponse)
    def landing(request: Request):
        if ctx.settings.judge_demo_mode:
            return judge_entry(request)
        return _page("landing", title="Habitat")

    @router.get("/auth/sign-in", response_class=HTMLResponse)
    def sign_in_page(request: Request):
        if ctx.settings.judge_demo_mode:
            return judge_entry(request)
        return _page("sign_in", title="Sign in")

    if ctx.settings.judge_demo_mode:
        @router.get("/auth/access")
        def access_link(token: str = ""):
            proof = accept_access_link(ctx, token)
            if proof is None:
                return access_required()
            # Exchange the private URL for browser-bound proof before showing the form.
            response = RedirectResponse("/auth/sign-in", status_code=303,
                                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
            # Lax carries the proof through a top-level redirect from another site;
            # the form POST still requires a signed nonce and the exact Origin.
            response.set_cookie(ENTRY_COOKIE, proof, max_age=ENTRY_TTL_SECONDS, path="/",
                                httponly=True, samesite="lax", secure=True)
            return response

        @router.post("/judge/start")
        async def judge_start(request: Request):
            form = await request.form()
            token = str(form.get("csrf_token", ""))
            verify_entry(ctx, token, request.cookies.get(ENTRY_COOKIE), request.headers.get("origin"),
                         request.headers.get("sec-fetch-site"))
            email = str(form.get("email", "")).strip()
            if not email or len(email) > 254:
                return judge_entry(request, 422, "Enter an email using 254 characters or fewer.")
            # Keep only a display username; the full address never becomes an identity key.
            result = start_workspace(ctx, token, request.cookies.get(SESSION_COOKIE), email.split("@", 1)[0])
            response = RedirectResponse("/workspace", status_code=303,
                                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
            response.set_cookie(SESSION_COOKIE, result.cookie_value, max_age=result.max_age_seconds, path="/",
                                httponly=True, samesite="lax", secure=True)
            return response

    @router.post("/auth/magic-link", response_class=HTMLResponse)
    async def request_link(request: Request):
        if ctx.settings.judge_demo_mode:
            raise AiclError("not_found", "Page not found.")
        form = await request.form()
        client_ip = request.client.host if request.client else "unknown"
        service.request_link(str(form.get("email", "")), client_ip)
        return _page("link_sent", 202, title="Check your email", message=GENERIC_LINK_SENT)

    @router.get("/auth/verify", response_class=HTMLResponse)
    def verify_page(token: str = ""):
        if ctx.settings.judge_demo_mode:
            raise AiclError("not_found", "Page not found.")
        return _page("verify", title="Confirm sign-in", token=token)

    @router.post("/auth/verify")
    async def verify(request: Request):
        if ctx.settings.judge_demo_mode:
            raise AiclError("not_found", "Page not found.")
        public = urlsplit(ctx.settings.public_base_url)
        expected_origin = f"{public.scheme}://{public.netloc}"
        # A valid link proves email ownership, not that this browser intended to sign in.
        # Require the same-origin confirmation form, including before a session exists.
        if (request.headers.get("origin") != expected_origin
                or request.headers.get("sec-fetch-site") == "cross-site"):
            raise AiclError("denied", "same-origin sign-in confirmation required", reason="check_unavailable")
        form = await request.form()
        result = service.verify(str(form.get("token", "")), request.cookies.get(SESSION_COOKIE))
        if result is None:
            return _page("invalid", 400, title="Link invalid")
        response = RedirectResponse("/workspace", status_code=303)
        response.set_cookie(SESSION_COOKIE, result.cookie_value, max_age=result.max_age_seconds, path="/",
                            httponly=True, samesite="lax", secure=secure)
        return response

    @router.post("/auth/logout")
    def logout(auth=Depends(csrf)):
        service.logout(auth)
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(ENTRY_COOKIE, path="/")
        return response

    @router.get("/workspace", response_class=HTMLResponse)
    def workspace(request: Request):
        auth = signed_in(request)
        if auth is None:
            return RedirectResponse("/", status_code=303)
        view = SqliteProjectionService(ctx.db, ctx.clock, ctx.settings.hold_stale_seconds).workspace(auth)
        workflow = workflow_service(ctx).overview(auth) if commerce_enabled else None
        pending_requests = []
        if commerce_enabled:
            from aicl.owner_requests.factory import owner_request_service
            pending_requests = owner_request_service(ctx).list(auth)
        return _page("workspace", title="Your workspace", instances=view.instances,
                     judge_demo_mode=ctx.settings.judge_demo_mode,
                     commerce_enabled=commerce_enabled, workflow=workflow,
                     pending_count=len(pending_requests), pending_requests=pending_requests[:3],
                     agent_request_counts={i.id: sum(r["instance_id"] == i.id for r in pending_requests)
                                           for i in view.instances},
                     **sidebar_context(ctx, auth))

    def wizard_form(auth, status=200, **values):
        defaults = {"name": "", "instructions": "", "selected": [], "errors": []}
        return _page("wizard", status, title="Create with wizard", key="wiz_" + uuid.uuid4().hex,
                     commerce_enabled=commerce_enabled,
                     **sidebar_context(ctx, auth), capabilities=CATALOG_CAPABILITIES,
                     **{**defaults, **values})

    @router.get("/agents/new", response_class=HTMLResponse)
    def wizard(request: Request):
        auth = signed_in(request)
        if auth is None:
            return RedirectResponse("/", status_code=303)
        return wizard_form(auth)

    @router.post("/agents/new", response_class=HTMLResponse)
    async def wizard_create(request: Request, auth=Depends(csrf)):
        form = await request.form()  # tenant_id / owner_id fields, if any, are never read
        name = str(form.get("name", ""))
        # Browsers serialize textarea newlines as CRLF. The canonical contract
        # accepts LF and still rejects other control characters, including bare CR.
        instructions = str(form.get("instructions", "")).replace("\r\n", "\n")
        selected = [str(c) for c in form.getlist("capabilities")]
        try:
            built = CreateInstanceRequest(
                idempotency_key=str(form.get("idempotency_key", "")), template_id=TEMPLATE_ID_DEFAULT, name=name,
                instructions=instructions, enabled_capabilities=frozenset(selected))
            result = create_instance(auth, built, surface="wizard", clock=ctx.clock)
        except ValidationError as exc:
            error = field_errors_from(exc)
            return wizard_form(auth, 422, name=name, instructions=instructions, selected=selected,
                               errors=error.extra["field_errors"])
        except AiclError as exc:
            if exc.error != "validation_failed":
                raise
            return wizard_form(auth, 422, name=name, instructions=instructions, selected=selected,
                               errors=exc.extra["field_errors"])
        return _page("created", title="Agent created", instance=result.instance, commerce_enabled=commerce_enabled,
                     **sidebar_context(ctx, auth))

    return router
