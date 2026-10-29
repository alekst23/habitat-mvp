"""create_app: the only composition root (technical.md AppComposition, owner E11-1)."""

from __future__ import annotations

import secrets
import sqlite3
import uuid
from dataclasses import dataclass, replace
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse

from aicl.auth.composite import CompositeAuthProvider, CompositeCsrfVerifier
from aicl.auth.csrf import HmacCsrfVerifier
from aicl.auth.session import SessionAuthProvider, SqliteSignInService
from aicl.control.audit import SqliteAuditLog
from aicl.control.auth import AuthContext, AuthProvider, FixedAuthProvider
from aicl.control.csrf import CsrfVerifier, FixedCsrfVerifier
from aicl.control.errors import ERROR_HTTP_STATUS, AiclError
from aicl.control.price_table import import_price_table
from aicl.db import Database
from aicl.hooks import STARTUP_HOOKS
from aicl.ports import Ports, build_ports
from aicl.routes import ROUTE_FACTORIES
from aicl.settings import Settings
from aicl.web.routes import FormCsrfShim


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    db: Database
    clock: object
    auth_provider: AuthProvider
    csrf_verifier: CsrfVerifier
    ports: Ports
    sign_in: object = None
    agent_runtime: object = None
    public_research: object = None


FIXTURE_OWNERS = {"owner-a": "00000000-0000-4000-8000-0000000000a1",
                  "owner-b": "00000000-0000-4000-8000-0000000000b2"}
FIXTURE_CSRF_TOKEN = "fixture-csrf-token"


def _register_test_routes(app: FastAPI, ctx: AppContext) -> None:
    """Test-composition only (both flags): seeded session, clock and the captured magic link."""
    router = APIRouter(prefix="/__test__")

    @router.post("/seed-session")
    def seed_session(body: dict) -> JSONResponse:
        owner_id = FIXTURE_OWNERS.get(str(body.get("fixture")))
        if owner_id is None:
            return JSONResponse({"error": "validation_failed", "message": "unknown fixture"}, status_code=422)
        cookie = secrets.token_urlsafe(24)
        auth = AuthContext(owner_id, owner_id, f"fixture-{uuid.uuid4()}", ctx.clock.now() + timedelta(seconds=ctx.settings.session_ttl_seconds))
        ctx.auth_provider.contexts[cookie] = auth
        ctx.csrf_verifier.fixture_session_ids = ctx.csrf_verifier.fixture_session_ids | {auth.session_id}
        response = JSONResponse({"owner_id": owner_id, "csrf_token": FIXTURE_CSRF_TOKEN})
        response.set_cookie("aicl_session", cookie, httponly=True, samesite="lax")
        return response

    @router.get("/last-magic-link")
    def last_magic_link(email: str = "") -> PlainTextResponse:
        normalized = ctx.sign_in.normalize_email(email)
        link = ctx.ports.magic_link_sender.last_for(normalized) if normalized else None
        if link is None:
            return PlainTextResponse("no link captured", status_code=404)
        return PlainTextResponse(link)

    @router.get("/clock")
    def clock() -> dict:
        return {"now": ctx.clock.now().isoformat()}

    app.include_router(router)


def create_app(settings: Settings, ports: Ports | None = None) -> FastAPI:
    """Run migrations and the price import, build AppContext via build_ports(settings) (`ports` is a
    test-only override), start STARTUP_HOOKS in order and register ROUTE_FACTORIES routers."""
    # model_copy is deliberately non-validating in Pydantic. Recheck profile guards
    # before any migrations, service composition or route registration.
    settings = Settings.model_validate(settings.model_dump())
    db = Database(settings.database_url)
    db.migrate()
    with db.transaction() as conn:
        import_price_table(conn, Path(settings.price_table_path))
    built = ports if ports is not None else build_ports(settings)
    sign_in = SqliteSignInService(
        db, built.clock, SqliteAuditLog(built.clock), built.magic_link_sender,
        identity_key=settings.identity_hmac_key, public_base_url=settings.public_base_url,
        link_ttl_seconds=settings.magic_link_ttl_seconds, session_ttl_seconds=settings.session_ttl_seconds)
    ctx = AppContext(
        settings, db, built.clock,
        CompositeAuthProvider(SessionAuthProvider(sign_in), FixedAuthProvider({})),
        CompositeCsrfVerifier(HmacCsrfVerifier(settings.session_secret, settings.public_base_url),
                              FixedCsrfVerifier(FIXTURE_CSRF_TOKEN, frozenset(), settings.public_base_url)),
        built, sign_in)
    from aicl.agent_runtime.factory import build_runtime
    from aicl.network.research_service import build_public_research
    from aicl.agent_runtime.worker import LocalRuntimeWorker
    ctx = replace(ctx, public_research=build_public_research(ctx))
    ctx = replace(ctx, agent_runtime=build_runtime(ctx))
    runtime_worker = LocalRuntimeWorker(ctx.agent_runtime) if ctx.agent_runtime else None

    @asynccontextmanager
    async def lifespan(_app):
        if runtime_worker:
            runtime_worker.start()
        try:
            yield
        finally:
            if runtime_worker:
                runtime_worker.stop()

    app = FastAPI(title="Habitat AICL control plane", lifespan=lifespan)
    app.add_middleware(FormCsrfShim)
    app.state.ctx = ctx
    app.state.runtime_worker = runtime_worker
    if settings.workflow_enabled:
        from fastapi.staticfiles import StaticFiles

        app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")

    @app.get("/health/live", include_in_schema=False)
    def liveness() -> dict:
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    def readiness() -> JSONResponse:
        try:
            with db.reader() as conn:
                conn.execute("SELECT version FROM schema_migration LIMIT 1").fetchone()
        except (sqlite3.Error, OSError):
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    @app.exception_handler(AiclError)
    async def aicl_error(_request, exc: AiclError) -> JSONResponse:
        return JSONResponse({"error": exc.error, "message": exc.message, **exc.extra},
                            status_code=ERROR_HTTP_STATUS[exc.error])

    for factory in ROUTE_FACTORIES:
        app.include_router(factory(ctx))
    if settings.test_mode and settings.environment == "test" and not settings.private_entry_enabled:
        _register_test_routes(app, ctx)
    for hook in STARTUP_HOOKS:
        hook(ctx)
    return app
