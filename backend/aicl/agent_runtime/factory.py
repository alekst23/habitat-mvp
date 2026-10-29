"""Explicit local live-runtime composition; credentials stay in the adapter."""
from aicl.agent_runtime.accounting import RuntimeAccounting
from aicl.agent_runtime.adapters import ToolRegistry
from aicl.agent_runtime.coordinator import AgentRuntime
from aicl.agent_runtime.storage import Repository


def build_runtime(ctx):
    if ctx.settings.agent_runtime_mode == "off":
        return None
    from aicl.agent_runtime.openai_model import OpenAIDecisionModel
    repo = Repository(ctx.db, ctx.clock)
    api_key = ctx.settings.openai_api_key.get_secret_value()
    # Private analysis has no outbound network tools. Public evidence is admitted
    # by the control-plane prelude before its first model decision.
    tools = ToolRegistry().with_artifact_reader(repo)
    model = OpenAIDecisionModel(api_key, tool_specs=tools.specs())
    return AgentRuntime(ctx.db, ctx.clock, model, tools, environment=ctx.settings.environment, allow_live=True,
                        public_research=ctx.public_research,
                        accounting=RuntimeAccounting(ctx.db, ctx.clock, ctx.settings.inference_max_spend_micro_usd))
