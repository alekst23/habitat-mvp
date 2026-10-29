# Unified agent workspace

The general-agent form and owner assistant edit the same persisted draft. There
is one creation and management page, one publication boundary, and one execution
contract for manual and scheduled work. The local demo enables it with
`--chat openai --agent-runtime openai`.

## State and commands

`agent_workspace` owns a management conversation, optional instance, versioned
draft, reviewed publication, and the versions of underlying instance/configuration
records. Migration 0035 adds workspace, run-history and schedule records without
rewriting existing conversations, agents, payment receipts or reservations.

`WorkspaceService.open` imports legacy data once. `update_draft` is shared by the
form and assistant and requires the expected version. `apply` atomically writes
the existing creation, capability, domain, limit and workflow services. Only an
owner command can apply authority. A stale edit is rejected; explicit reload
can replace the draft from saved controls. Draft writes never dispatch or fund.

`/api/agent-workspaces/{id}/commands` is the authenticated, CSRF-protected owner
command adapter. The browser's optional `modelContext` tools call the same draft
command. The embedded assistant uses `WorkspaceAssistantTools` over the same
service and retains metered SDK requests, strict schemas and durable turn replay.
Both assistant adapters expose read, draft update and section navigation only.
Old cached chat POSTs are refused after their session or instance is imported,
preventing an old proposal confirmation from creating another agent.

Each embedded assistant turn receives a fresh, bounded workspace snapshot with
the current version, draft, capabilities and execution state. Ordinary fields,
including empty tool and domain lists, need no model-initiated reads. Oversized
fields are explicitly marked for paginated reading; optimistic version checks
still reject edits based on stale state.

The last of the five allowed model requests is reserved for a text reply.
Draft updates and successful tool receipts commit together. If the reply fails
after accepted work, a separate Habitat status message reports the saved state;
the turn stays failed or unknown, and uncertain provider charges remain held.
Accepted terminal outcomes return the refreshed workspace and clear the
composer. Retrying the same request returns its prior outcome before checking
the draft version, so a lost response cannot cause a second edit or paid turn.
Older failed turns receive the same status projection on reads without rewriting
conversation history or dispatching another model request.

## Execution and funding

`WorkspaceExecution` admits manual and due scheduled runs through the same
`RunDefinition`, registry, pricing/readiness and `AgentRuntime`. Published settings
are frozen into each run. Editing future settings cannot change the current run's
definition. Existing run recovery remains possible with unapplied draft changes.
Manual starts and scheduler ticks prevent overlap and use durable request keys.

AI processing is intrinsic to agents, not an optional permission. Creating or
applying a workspace grants inference; older `inference_enabled` draft fields
are ignored on reads and cannot be edited. Migration 0039 enables the required
grant for existing non-archived workspace agents without changing their budgets,
funding, web releases, lifecycle or schedules. Runtime AICL grant, funding and
spending checks remain mandatory. Pause the agent to stop work. The separate
metered setup conversation remains available to edit settings.

Permissions are presented as feature rows with native radio choices ordered
from more restrictive to less restrictive. Web access uses Off / Only selected
sites / All except selected sites / All public sites. Site lists and disclosure
review stay with the web row. Gmail and Reddit remain disabled with a
"Not yet available" status; their simulated legacy records do not make them
executable integrations. Selecting a radio never grants authority; owner Apply
and current AICL enforcement still govern access.

The shared draft has one `web_access` policy: `off`, `allowlist`, `blocklist`,
or `all`, with domains for the two list modes. Domains include subdomains. The
server derives the search/page grants; the assistant proposes policy instead of
configuring individual tool calls. Owner Apply acknowledges a digest binding the
visible goal, access level, provider/account/credential contract, and fixed public
planner recipient. Migration 0037 stores immutable, revocable releases; legacy
exact-query releases remain unchanged and require explicit selection and approval
to become broader policies. Private context is never part of this release.

Before private analysis, `PublicResearchService` builds a fresh planning context
from that release and public evidence only. The bounded research planner chooses
queries and pages; AICL seals and checks each exact request. Search results are
filtered by site policy before analysis or further planning, and page destinations
are independently checked. The broker rechecks authority before DNS and HTTP,
pins public addresses, and sends static contract headers. Redirects, cookies,
uploads, scripts, subresources and tracking headers are unavailable. Private
analysis receives the evidence but has no public web tools, including after
owner messages or resume. Editing private context cannot steer the public phase.

The public worker runs through an inspected Docker launch with an immutable
local image, no network, credentials, host mounts or capabilities, and a
read-only filesystem. The broker retains transport and provider credentials
outside that worker. Missing verified containment denies research; a configured
flag alone cannot enable it. This does not claim containment of the separate
private inference adapter or whole-application AICL compliance.

The optional raw Brave Search adapter requires its own operator-configured key
and account/credential binding; it does not reuse the OpenAI key. Its pinned fee
is $0.005 per search request. The canonical budget ledger reserves the entire
research maximum (two bounded planner calls, two searches, five pages) before
dispatch, and migration 0038 adds a durable one-shot dispatch
claim. Successful usage settles once. Partial or unknown outcomes keep the hold
and block continuation; no provider retry runs automatically. Live legacy hosted
search and direct page-tool paths are withdrawn. Their saved configurations,
receipts and holds remain, but cannot bypass a new reviewed release. See
[AICL public research](aicl-public-research.md) for configuration and limitations.

Owner restart binds the workspace and existing run versions and a durable
request key. A waiting, paused or blocked run can be cancelled and replaced with
the applied definition in one transaction; stale edits, dispatched steps with
unapplied receipts or uncertain outcomes, or failed funding admission leave the
original run intact. Prepared tools with no hold, usage or receipt can be safely
abandoned with their original run. Original
history and charges are retained in the original run. Replaying a successful restart returns the
same replacement before considering later versions. Applying settings alone
never widens the current run's tools or starts a replacement.

The worker checks enabled schedules before advancing queued runs. Hourly timing
uses UTC intervals; daily timing resolves the selected local time with `ZoneInfo`,
including DST. Failed admission retains the due occurrence and its reason. Missed
occurrences coalesce, and paused or waiting-owner runs are not resumed by schedule.
Automatic execution requires the local app process to remain running.

Funding uses the existing commerce order and checkout. The return destination is
derived from the owned saved order, never a client-provided URL. Pending orders
are reused. After checkout, readiness refreshes; the owner starts or resumes work.
The assistant displays only this workspace's setup cost. Its provider requests
are initially covered by the operator's bounded allowance, then attributed to
the agent's service credit at owner activation or work admission. Known pending
setup costs and unresolved reservations reduce available credit immediately;
converting pending costs into paid setup charges does not deduct them again.
Readiness shows service credit, pending and paid setup cost, and the balance
available for work after setup. Activation requires enough credit for setup;
starting work additionally requires the next bounded runtime estimate.

Migration 0036 adds append-only setup charge, waiver and reset records. Setup
usage is joined through the workspace's own conversation and owner scope. Each
provider attempt can be charged or waived only once. An explicit operator reset
waives identified uncharged settled attempts while retaining provider history,
the global spend ceiling, and all uncertain holds. It is not an assistant tool
or a customer control for obtaining repeated free setup. Unresolved setup usage
prevents paid work. An active setup reply prevents activation and new starts;
existing runs can continue within the credit remaining after setup reservations.
Fresh owner continuations settle pending setup when the assistant is idle.
For legacy conversations covering multiple agents, older unassigned usage stays
in operator accounting; only new workspace turns or existing immutable setup
receipts count toward the agent. Conversation and provider history are retained.

## Validation

Focused suites: `test_agent_workspace.py`, `test_workspace_execution.py`,
`test_workspace_assistant.py`, `test_workspace_routes.py`, `test_workspace_pages.py`,
`test_workspace_context.py`, `test_workspace_reply_recovery.py`, and the setup
accounting and activation integration suites.
They cover stale state, tenant scope, authority boundaries, preserved holds,
atomic publication, canonical manual/scheduled definitions, DST, unpaid due
recovery, SDK accounting and checkout return.

`test_research_policy.py`, `test_research_broker.py` and
`test_runtime_research_prelude.py` add adversarial disclosure and accounting
checks: changed queries/URLs/headers/accounts, private-context contamination,
revocation, redirect/DNS attacks, duplicate dispatch and partial outcomes.
`test_research_containment.py` is an opt-in test of an actual cached Docker image;
it verifies kernel-enforced network/privilege restrictions and hostile public
content handling without contacting a provider. Fixture tests alone do not
establish live containment.

`node --test tests/agent-workspace-ui.test.cjs` exercises the browser UI using
fixture responses: shared edits, conflicts, unavailable legacy tools, funding,
continued management after launch, responsive layout, collapse persistence,
interrupted replies and lost-response replay.
Full-stack fixture evidence lives under ignored `.ctx/workspace-verification/`;
no live model calls or real payments are required for these checks.
