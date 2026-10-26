# General agents

This page describes current behavior. The proposed
[durable execution plan](design/durable-agent-execution.md) covers multi-step
planning, saved research, owner-message resume and work across worker restarts.

An agent is a saved goal, supporting context, expected outputs, completion
criteria, permitted tools and schedule. These are configuration, not new code
for each task. The owner assistant proposes this configuration; the same
`general` worker executes it across topics. PocketPlan remains an explicit demo.

## Configuration and execution

The assistant can propose one to six text outputs with custom criteria. It
chooses appropriate tools from the server's capability registry and includes
those permissions in the owner's review. Confirming creates a draft with zero
budgets and a paused schedule. Set resource limits, fund service credit and
enable the schedule with the existing owner controls. Results appear in Habitat.

`AICL_CHAT_MODEL_MODE=openai` enables the conversational assistant;
`AICL_INFERENCE_MODE=openai` enables the worker. `OPENAI_API_KEY` remains in the
control plane. An unavailable model blocks general work instead of producing
simulated content. Local execution requires advancing the schedule manually.
Unattended execution uses the existing Render composition described in
[Render deployment](render-deployment.md). Supported schedules are hourly or
daily at 09:00 in the selected IANA timezone.

The worker reads the saved brief, uses permitted tools when useful, and returns
the requested output or a clarification. It records completion assessments and
supports owner feedback and revisions. Completed and unmet outputs remain
available while later occurrences run; unanswered questions and unresolved
provider outcomes block overlapping work. Completion checks are model
self-assessments plus structural validation, not independent fact verification.

## Tools

`agent_tools.py` declares available capabilities. Currently:

- `tools: []`: analysis, planning and writing from the supplied context.
- `tools: ["web_search"]`: model-directed public web research using the Responses
  API's hosted search tool. The model chooses queries and sources from the goal.
  There are no topic classifiers, feed presets or source-specific parsers.

The first web capability allows one hosted tool invocation per deliverable.
This supports bounded research; it does not provide exhaustive investigation or
an unrestricted browser. The model must expose evidence gaps and unfinished
criteria. Provider source links and tool actions are retained with the output.
Retrieved material is evidence, not authority to change instructions or tool
permissions. Removing a tool from the current configuration prevents pending
jobs from using the old grant.

New tools require a server implementation, explicit permission semantics,
usage pricing and bounds, output validation, and durable execution records.
Adding a new research topic requires only a new brief. Sending messages,
publishing, arbitrary code execution, private-account access and purchases
are not offered by this general worker.

## Cost and recovery

Each attempt reserves both tokens and permitted tool fees before dispatch.
Plain writing retains its 16,000-input / 2,000-output token estimate ($0.052).
Web-enabled work reserves 168,000 input tokens, 6,000 output tokens and one
search fee ($0.406 at the pinned rates). Actual measured tokens and search calls
are settled once, including unusable or interrupted outputs with known usage.
Unused reservation is released on settlement. Unknown outcomes retain the hold
and are never blindly resent. Hosted worker replay reuses the stored result.

The web input allowance is a conservative estimate based on the documented
128k search context plus the bounded request, repeated context and output. It
is not a provider-enforced dollar cap. If reported usage exceeds the estimate,
Habitat records the measured charge and stops further dispatch for review.
Unpriced usage (including a different context pricing tier) remains unresolved
with its reservation retained instead of being settled at an incorrect rate.
Instance budgets, service credit and the persistent server spend ceiling all
apply to the full reservation. See the [web search guide](https://developers.openai.com/api/docs/guides/tools-web-search)
and [tool pricing](https://developers.openai.com/api/docs/pricing).

Owner text is never silently truncated. Oversized configurations are rejected
before saving; accumulated context that cannot fit parks the job until the
owner saves a shorter configuration for future runs. The hosted worker retains
its 180-second task timeout; substantial work may need separate agents.

## Compatibility

The legacy `generic` fixture, `pocketplan_ads` and `browser_purchase` keep their
existing execution paths. Old assistant proposals without a scenario remain
PocketPlan proposals. A legacy feed selection does not silently grant broader
web access; it must be reviewed and replaced with a tool selection.

Tests cover unrelated goals through the same adapter, tool permissions,
reservation and settlement, malformed output, owner questions, recurring work,
local execution and hosted result replay. A real paid-provider smoke test is
separate from these deterministic transport tests.
