# General agents

## Unified local workspace

Start the local demo with `--chat openai --agent-runtime openai` and an
`OPENAI_API_KEY`, or the existing `--inference-key-file` option. **Create an agent**,
`/chat`, and existing general-agent setup links all open `/agent-workspaces/{id}`.
The editable form and collapsible assistant share one versioned saved draft.
The assistant can read and update it throughout execution. **Guide this run** is
a separate message control for the worker; ordinary conversation remains about
managing the agent. Unfinished drafts are listed on the workspace home.

Review **Apply settings**, then use the visible **Funding and readiness** panel.
Checkout returns to the same workspace. **Start work** remains unavailable until
permissions, budgets, provider limits and service credit pass preflight. Funding
does not start or resume a run. Pending checkout links remain available for recovery.

On-demand, hourly and daily work use the same approved definition, tool registry,
readiness checks and durable runtime. Daily work uses the saved local time and
IANA timezone. Enable its schedule explicitly after applying settings and funding.
The local worker runs due work independently of the browser while the server runs;
unfunded occurrences remain due, unfinished work prevents overlap, and missed
occurrences coalesce into one run. Saved plans, evidence and drafts survive restarts.

This runtime supports writing/analysis from supplied context and a separate public
research phase before private analysis. In **Web access**, choose one level:

- **Off:** no web search or page requests.
- **Only selected sites:** research uses the listed domains and their subdomains.
- **All except selected sites:** research excludes the listed domains and their subdomains.
- **All public sites:** research may use any public HTTPS site.

The agent chooses its searches and pages from the visible goal; there are no
query lists, source URL lists, or separate web-tool switches to configure. The
owner explicitly approves the goal for public research when applying access.
Context and inputs, files, conversation history and internal identifiers are
excluded from that research context. Goal, access or provider changes require
fresh approval. Private analysis can consume public evidence but cannot steer
new public requests. Old exact-query approvals retain their original scope until
the owner selects and applies a new level; they are never widened on migration.
Manual and scheduled runs share these controls. Existing runs require a restart
to use updated settings.

Public workers require a verified Docker container with an immutable local image,
no network, credentials or host mounts, and a read-only filesystem. The AICL
broker checks the exact request before DNS and HTTP, pins public addresses, and
suppresses redirects, cookies, uploads, scripts, subresources and tracking headers.
Private analysis receives public evidence but has no public web tools. Its
separate inference adapter is not claimed to have the public worker's isolation.
Missing containment or provider configuration makes the capability unavailable;
there is no direct-network fallback.

Configure the local worker with `--research-worker-image sha256:<local-image-id>`.
Search additionally needs `--search-key-file`, `--search-account` and
`--search-credential-binding`. The new agent-directed mode also requires the
configured inference connection. Legacy exact-page releases remain supported.
See [public research configuration and boundaries](design/aicl-public-research.md).
Rendered browsing remains unavailable. Runtime enablement is restricted to local
development/test while production storage remains deferred. Existing blocked
runs, conversations and charges are imported without dispatch or payment.
Legacy tool selections do not confer disclosure approval.

For an existing waiting, paused or blocked run, **Restart with updated settings**
replaces the old run only after saved settings and funding pass preflight. The
old run and all charges remain in history. Dispatched operations with unresolved
outcomes or unapplied receipts must be resolved before restart. Planned actions
that never reserved credit can be abandoned; retrying a restart cannot create a
second run.

Raw search has a pinned fee of **$0.005 per request**. Public research uses at
most two planning calls, two searches and five page reads per run. A complete
upper bound for planning tokens and search fees is reserved before the first
call; the displayed reservation is not the final charge. Actual measured usage
settles once. Unknown or partial outcomes keep the reservation and prevent
automatic replay. Private analysis is metered separately against the same agent
balance. Source text remains untrusted evidence and cannot change permissions.
The provider contract uses [Brave's raw search endpoint](https://api-dashboard.search.brave.com/api-reference/web/search/get)
and [published search pricing](https://api-dashboard.search.brave.com/documentation/pricing).

The optional WebMCP adapter exposes only workspace reading, draft editing and
section navigation; the embedded assistant calls the shared application services
directly and does not depend on browser WebMCP support.

See [shared workspace architecture](design/unified-agent-workspace.md).

## Legacy hosted and runtime-disabled flows

The remaining sections describe the separate legacy workflow engine used when
the local durable runtime is disabled, including existing hosted deployments.
They do not describe the unified local workspace's capability catalog or scheduler.
Its live hosted search path is withdrawn: existing search configurations fail
closed, and historical outputs, charges and unresolved reservations are retained.

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

`agent_tools.py` still recognizes these legacy configuration values:

- `tools: []`: analysis, planning and writing from the supplied context.
- `tools: ["web_search"]`: retained for historical configuration compatibility.
  Live dispatch is denied with `hosted_search_withdrawn`, including already saved
  jobs. This setting cannot activate the new AICL research phase.

To use public research, review a release in the unified workspace and start or
explicitly restart a run with those applied settings. Removing a tool does not
erase prior usage or permit retrying an uncertain operation. Historical source
links and tool traces remain evidence, never instructions or authority.

New tools require a server implementation, explicit permission semantics,
usage pricing and bounds, output validation, and durable execution records.
Adding a new research topic requires only a new brief. Sending messages,
publishing, arbitrary code execution, private-account access and purchases
are not offered by this general worker.

## Cost and recovery

Plain writing retains its 16,000-input / 2,000-output token estimate ($0.052).
Measured tokens are settled once, including unusable or interrupted outputs with
known usage; unused reservation is released on settlement. Unknown outcomes
retain the hold and are never blindly resent. Hosted worker replay reuses the
stored result. Instance budgets, service credit and the persistent server spend
ceiling still apply.

The former hosted-search token estimates do not authorize new searches. Preserve
their historical receipts and unresolved holds; do not reset or reinterpret them
as the new fixed-price Brave requests. The replacement research phase uses its
own approved provider contract and whole-batch reservation described above.

Owner text is never silently truncated. Oversized configurations are rejected
before saving; accumulated context that cannot fit parks the job until the
owner saves a shorter configuration for future runs. The hosted worker retains
its 180-second task timeout; substantial work may need separate agents.

## Compatibility

The legacy `generic` fixture, `pocketplan_ads` and `browser_purchase` keep their
existing execution paths. Old assistant proposals without a scenario remain
PocketPlan proposals. A legacy feed selection does not silently grant broader
web access; public research requires a reviewed release in the unified workspace.

Tests cover unrelated goals through the same adapter, tool permissions,
reservation and settlement, malformed output, owner questions, recurring work,
local execution and hosted result replay. A real paid-provider smoke test is
separate from these deterministic transport tests.
