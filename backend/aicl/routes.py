"""Route-factory extension point (E11-1): each ticket with routes adds one line."""

from __future__ import annotations

from typing import Callable

from aicl.creation.routes import tool_router

# Ordered tuple of `(AppContext) -> fastapi.APIRouter`.
ROUTE_FACTORIES: tuple[Callable[..., object], ...] = (tool_router,)
