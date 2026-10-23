"""Route-factory extension point (E11-1): each ticket with routes adds one line."""

from __future__ import annotations

from typing import Callable

from aicl.chat.routes import chat_router
from aicl.commerce.routes import commerce_router
from aicl.creation.routes import tool_router
from aicl.web.manage import manage_router
from aicl.web.routes import web_router
from aicl.work.routes import router_factory as work_router
from aicl.workflow.routes import workflow_router
from aicl.render.routes import render_router
from aicl.owner_requests.routes import owner_requests_router

# Ordered tuple of `(AppContext) -> fastapi.APIRouter`.
ROUTE_FACTORIES: tuple[Callable[..., object], ...] = (tool_router, work_router, web_router, chat_router,
                                                          manage_router, commerce_router, workflow_router, render_router,
                                                          owner_requests_router)
