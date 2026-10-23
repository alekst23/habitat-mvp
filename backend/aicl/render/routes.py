"""Machine-only Render API. No owner, purchase-approval or payment endpoints."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from aicl.control.errors import AiclError
from aicl.render.service import RenderExecution
from aicl.workflow.factory import workflow_service


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_run_id: str = Field(min_length=1, max_length=200)


class Attempt(Task):
    attempt_id: str = Field(min_length=1, max_length=64)


class Completion(Attempt):
    validation: dict


def render_router(ctx):
    router = APIRouter(prefix="/internal/render", include_in_schema=False)
    if ctx.settings.workflow_execution_mode != "render":
        return router
    service = RenderExecution(workflow_service(ctx))

    def identity(secret):
        def check(request: Request):
            value = request.headers.get("authorization", "")
            expected = "Bearer " + secret.get_secret_value()
            if not secret.get_secret_value() or not secrets.compare_digest(value.encode(), expected.encode()):
                raise AiclError("unauthenticated", "Machine authentication required.")
        return check

    scheduler = identity(ctx.settings.scheduler_token)
    worker = identity(ctx.settings.worker_token)

    @router.post("/dispatch", dependencies=[Depends(scheduler)])
    def dispatch():
        return service.dispatch()

    @router.post("/dispatch/{dispatch_id}/submitted", dependencies=[Depends(scheduler)])
    def submitted(dispatch_id: str, body: Task):
        return service.submitted(dispatch_id, body.task_run_id)

    @router.post("/dispatch/{dispatch_id}/uncertain", dependencies=[Depends(scheduler)])
    def uncertain(dispatch_id: str):
        return service.uncertain(dispatch_id)

    @router.post("/jobs/{dispatch_id}/claim", dependencies=[Depends(worker)])
    def claim(dispatch_id: str, body: Task):
        return service.claim(dispatch_id, body.task_run_id)

    @router.post("/jobs/{dispatch_id}/generate", dependencies=[Depends(worker)])
    def generate(dispatch_id: str, body: Attempt):
        return service.generate(dispatch_id, body.task_run_id, body.attempt_id)

    @router.post("/jobs/{dispatch_id}/complete-attempt", dependencies=[Depends(worker)])
    def complete(dispatch_id: str, body: Completion):
        return service.complete_attempt(dispatch_id, body.task_run_id, body.attempt_id, body.validation)

    @router.post("/jobs/{dispatch_id}/finish", dependencies=[Depends(worker)])
    def finish(dispatch_id: str, body: Task):
        return service.finish(dispatch_id, body.task_run_id)

    return router
