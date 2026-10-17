"""`POST /app-tools/{name}` for same-origin authenticated callers (session cookie plus X-CSRF-Token)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from aicl.control.csrf import require_csrf
from aicl.control.errors import AiclError
from aicl.creation.service import validation_failed
from aicl.creation.tools import TOOL_REGISTRY


def field_errors_from(exc: ValidationError) -> AiclError:
    out: list[tuple[str, str]] = []
    for item in exc.errors():
        field = ".".join(str(p) for p in item["loc"]) or "body"
        code = "unknown_argument" if item["type"] == "extra_forbidden" else "invalid"
        out.append((field, code))
    return validation_failed(*(out or [("body", "invalid")]))


def tool_router(ctx) -> APIRouter:
    router = APIRouter()
    csrf = require_csrf(ctx)

    @router.post("/app-tools/{name}")
    async def call_tool(name: str, request: Request, auth=Depends(csrf)):
        tool = TOOL_REGISTRY.get(name)
        if tool is None:
            raise AiclError("not_found", "unknown tool")
        try:
            body = await request.json()
        except ValueError:
            raise validation_failed(("body", "invalid_json")) from None
        if not isinstance(body, dict):
            raise validation_failed(("body", "invalid"))
        try:
            payload = tool.input_model.model_validate(body)
        except ValidationError as exc:
            raise field_errors_from(exc) from None
        return tool.handler(auth, payload, ctx)

    return router
