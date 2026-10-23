"""Private HTTP control surface; only the AICL broker holds this bearer token."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import re
import secrets
from typing import Literal

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from browser_service.network import NetworkDenied, validate_url
from browser_service.runtime import BrowserError, SessionManager, Settings


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$")
    url: str = Field(min_length=1, max_length=8192)
    storage_state: dict | None = None
    mode: Literal["owner", "worker"] = "owner"
    ttl_seconds: int = Field(default=600, ge=30, le=900, strict=True)

    @model_validator(mode="after")
    def bounded_state(self):
        if self.storage_state is not None and len(json.dumps(self.storage_state).encode()) > 2_000_000:
            raise ValueError("Browser state exceeds the supported size.")
        return self


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["click", "text", "key", "scroll"]
    x: float | None = Field(default=None, ge=0, lt=1280, allow_inf_nan=False)
    y: float | None = Field(default=None, ge=0, lt=720, allow_inf_nan=False)
    text: str | None = Field(default=None, max_length=4096)
    key: str | None = Field(default=None, max_length=30)
    delta_y: float | None = Field(default=None, ge=-2000, le=2000, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_action(self):
        expected = {"click": {"x", "y"}, "text": {"text"}, "key": {"key"}, "scroll": {"delta_y"}}[self.type]
        present = {name for name in ("x", "y", "text", "key", "delta_y") if getattr(self, name) is not None}
        if present != expected:
            raise ValueError("Provide only the fields required by this input action.")
        if self.type == "key":
            ordinary = {"Enter", "Tab", "Backspace", "Delete", "Escape", "Space",
                        "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"}
            allowed = ordinary | {"Shift+" + key for key in ordinary} | {"ControlOrMeta+A"}
            if self.key not in allowed:
                raise ValueError("That keyboard action is not available.")
        return self


class Navigation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=8192)


def create_app(settings: Settings | None = None, *, engine=None, clock=None):
    settings = settings or Settings.from_env()
    manager = SessionManager(settings, engine=engine, clock=clock)

    @asynccontextmanager
    async def lifespan(app):
        await manager.start()
        async def reap():
            while True:
                await asyncio.sleep(5)
                await manager.expire()
        cleanup = asyncio.create_task(reap())
        app.state.browser_reaper = cleanup
        try:
            yield
        finally:
            cleanup.cancel()
            await asyncio.gather(cleanup, return_exceptions=True)
            await manager.close()

    app = FastAPI(title="Private browser runtime", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.browser_manager = manager

    @app.middleware("http")
    async def private_responses(request, call_next):
        if len(request.headers.get("content-length", "")) > 12:
            return JSONResponse({"error": "request_too_large"}, status_code=413)
        try:
            size = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if size > 2_100_000:
            return JSONResponse({"error": "request_too_large"}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(BrowserError)
    async def browser_error(request, exc):
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status)

    @app.exception_handler(NetworkDenied)
    async def network_error(request, exc):
        return JSONResponse({"error": "destination_denied", "message": str(exc)}, status_code=400)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Pydantic's usual response includes the rejected input, which could be
        # a password, cookie or login code. Never echo that payload.
        return JSONResponse({"error": "invalid_request", "message": "The browser request is invalid."}, status_code=422)

    def authenticated(request: Request):
        value = request.headers.get("authorization", "")
        if not secrets.compare_digest(value.encode(), ("Bearer " + settings.token).encode()):
            raise BrowserError("unauthenticated", "Service authentication is required.", 401)

    @app.get("/health/ready")
    def ready():
        if app.state.browser_reaper.done():
            raise BrowserError("browser_unavailable", "The browser session cleanup service is unavailable.", 503)
        return {"status": "ready", "test_mode": settings.test_mode}

    @app.post("/sessions", dependencies=[Depends(authenticated)])
    async def create(body: CreateSession):
        return await manager.create(**body.model_dump())

    @app.get("/sessions/{session_id}/frame", dependencies=[Depends(authenticated)])
    async def frame(session_id: str):
        return await manager.operate(session_id, "frame", mode="owner")

    @app.post("/sessions/{session_id}/input", dependencies=[Depends(authenticated)])
    async def input_action(session_id: str, body: Input):
        return await manager.operate(session_id, "input", mode="owner", argument=body.model_dump(exclude_none=True))

    @app.post("/sessions/{session_id}/navigate", dependencies=[Depends(authenticated)])
    async def navigate(session_id: str, body: Navigation):
        validate_url(body.url, settings.fixture_origin)
        return await manager.operate(session_id, "navigate", mode="worker", argument=body.url)

    @app.get("/sessions/{session_id}/page", dependencies=[Depends(authenticated)])
    async def page(session_id: str):
        return await manager.operate(session_id, "text", mode="worker")

    @app.post("/sessions/{session_id}/snapshot", dependencies=[Depends(authenticated)])
    async def snapshot(session_id: str):
        return await manager.operate(session_id, "snapshot")

    @app.delete("/sessions/{session_id}", dependencies=[Depends(authenticated)])
    async def close(session_id: str):
        await manager.delete(session_id)
        return {"closed": True}

    @app.delete("/session-keys/{idempotency_key}", dependencies=[Depends(authenticated)])
    async def cancel_unknown_session(idempotency_key: str):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", idempotency_key):
            raise BrowserError("invalid_request", "A valid session request key is required.", 422)
        await manager.cancel_key(idempotency_key)
        return {"closed": True}

    return app
