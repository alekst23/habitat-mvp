"""Route-factory extension point (E11-1): each ticket with routes adds one line."""

from __future__ import annotations

from typing import Callable

from aicl.creation.routes import tool_router
from aicl.web.routes import web_router
from aicl.work.routes import router_factory as work_router

# Ordered tuple of `(AppContext) -> fastapi.APIRouter`.
ROUTE_FACTORIES: tuple[Callable[..., object], ...] = (tool_router, work_router, web_router)
