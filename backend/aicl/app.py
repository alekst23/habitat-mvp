"""create_app: the only composition root (technical.md AppComposition, owner E11-1)."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse

from aicl.control.auth import AuthContext, AuthProvider, FixedAuthProvider
from aicl.control.csrf import CsrfVerifier, FixedCsrfVerifier
from aicl.control.errors import ERROR_HTTP_STATUS, AiclError
from aicl.control.price_table import import_price_table
from aicl.db import Database
from aicl.hooks import STARTUP_HOOKS
from aicl.ports import Ports, build_ports
from aicl.routes import ROUTE_FACTORIES
from aicl.settings import Settings


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    db: Database
    clock: object
    auth_provider: AuthProvider
    csrf_verifier: CsrfVerifier
    ports: Ports


FIXTURE_OWNERS = {"owner-a": "00000000-0000-4000-8000-0000000000a1",
                  "owner-b": "00000000-0000-4000-8000-0000000000b2"}
FIXTURE_CSRF_TOKEN = "fixture-csrf-token"


def _register_test_routes(app: FastAPI, ctx: AppContext) -> None:
    """Test-composition only (both flags): seeded session and clock. No magic-link capture (E11-3)."""
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

    @router.get("/clock")
    def clock() -> dict:
        return {"now": ctx.clock.now().isoformat()}

    app.include_router(router)


def create_app(settings: Settings, ports: Ports | None = None) -> FastAPI:
    """Run migrations and the price import, build AppContext via build_ports(settings) (`ports` is a
    test-only override), start STARTUP_HOOKS in order and register ROUTE_FACTORIES routers."""
    db = Database(settings.database_url)
    db.migrate()
    with db.transaction() as conn:
        import_price_table(conn, Path(settings.price_table_path))
    built = ports if ports is not None else build_ports(settings)
    ctx = AppContext(settings, db, built.clock, FixedAuthProvider({}),
                     FixedCsrfVerifier(FIXTURE_CSRF_TOKEN, frozenset(), settings.public_base_url), built)
    app = FastAPI(title="Habitat AICL control plane")
    app.state.ctx = ctx

    @app.exception_handler(AiclError)
    async def aicl_error(_request, exc: AiclError) -> JSONResponse:
        return JSONResponse({"error": exc.error, "message": exc.message, **exc.extra},
                            status_code=ERROR_HTTP_STATUS[exc.error])

    for factory in ROUTE_FACTORIES:
        app.include_router(factory(ctx))
    if settings.test_mode and settings.environment == "test":
        _register_test_routes(app, ctx)
    for hook in STARTUP_HOOKS:
        hook(ctx)
    return app
