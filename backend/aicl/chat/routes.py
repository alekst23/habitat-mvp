"""`GET /chat` and `POST /chat/messages` (aicl-experience/technical.md, owner E11-4).

Contract stub. `chat_router` is NOT yet in `aicl.routes.ROUTE_FACTORIES`; the implementation phase adds that one
line (E11-1 extension point) and updates the composition test that pins the route-factory count. `GET /chat`
redirects an unauthenticated visitor to the landing page; `POST /chat/messages` uses the shared E11-1
`require_csrf` dependency and never reads a tenant or owner from the client. Replies are escaped plain text.
"""

from __future__ import annotations

from fastapi import APIRouter

from aicl.chat.ports import NOT_IMPLEMENTED


def chat_router(ctx) -> APIRouter:
    """`(AppContext) -> APIRouter` factory in the ROUTE_FACTORIES shape."""
    raise NotImplementedError(NOT_IMPLEMENTED)
