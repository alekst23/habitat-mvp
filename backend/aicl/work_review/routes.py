"""Authenticated owner browsing and CSRF-protected, non-authorizing UI marks."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from aicl.control.csrf import require_csrf
from aicl.control.errors import AiclError
from aicl.web.account import sidebar_context
from aicl.work_review.service import WorkReviewService


def work_review_router(ctx):
    router, service = APIRouter(), WorkReviewService(ctx)
    csrf = require_csrf(ctx)

    def authenticated(request):
        auth = ctx.auth_provider.resolve(dict(request.cookies))
        if auth is None:
            raise AiclError("unauthenticated", "Sign in to continue.")
        return auth

    def response(data):
        return JSONResponse(data, headers={"Cache-Control": "no-store"})

    @router.get("/work")
    def page(request: Request):
        from aicl.work_review.pages import render_review
        auth = ctx.auth_provider.resolve(dict(request.cookies))
        if auth is None:
            return RedirectResponse("/", 303)
        account = sidebar_context(ctx, auth)
        return HTMLResponse(render_review(csrf=account["csrf"], account_name=account["account_name"]),
                            headers={"Cache-Control": "no-store"})

    @router.get("/api/work-review")
    def listing(request: Request, q: str = "", view: str = "all", workspace_id: str = "",
                from_date: str = "", to_date: str = "", cursor: str = "", limit: int = 25):
        return response(service.list(authenticated(request), q=q, view=view, workspace_id=workspace_id,
                                     from_date=from_date, to_date=to_date, cursor=cursor, limit=limit))

    @router.get("/api/work-review/{run_id}")
    def detail(run_id: str, request: Request):
        return response(service.detail(authenticated(request), run_id))

    @router.post("/api/work-review/{run_id}/marks")
    async def mark(run_id: str, request: Request, auth=Depends(csrf)):
        try:
            if len(await request.body()) > 1000:
                raise ValueError
            data = await request.json()
        except (ValueError, TypeError):
            raise AiclError("validation_failed", "Supply a small JSON object of inbox marks.") from None
        return response(service.mark(auth, run_id, data))

    return router
