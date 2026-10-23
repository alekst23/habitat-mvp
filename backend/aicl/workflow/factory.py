"""Use the same controls, payment transport and accounting as owner checkout."""

from aicl.commerce.factory import commerce_service
from aicl.workflow.service import MockWorkflowService
from aicl.settings import Settings


def workflow_service(ctx):
    settings = Settings.model_validate(ctx.settings.model_dump())
    inference = None
    if settings.inference_mode == "openai":
        from aicl.workflow.openai_inference import OpenAIInferenceAdapter

        inference = OpenAIInferenceAdapter(api_key=settings.openai_api_key.get_secret_value())
    return MockWorkflowService(ctx.db, ctx.clock, commerce=commerce_service(ctx),
                               inference=inference,
                               execution_mode=settings.workflow_execution_mode,
                               render_max_spend_micro_usd=settings.render_max_spend_micro_usd,
                               render_max_dispatches=settings.render_max_dispatches,
                               inference_max_spend_micro_usd=settings.inference_max_spend_micro_usd)
