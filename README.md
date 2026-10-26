# Habitat — owner-controlled AI agents

Habitat's Configurable AI Control Layer lets an owner create and manage a Default
agent instance through a wizard or built-in chat. The owner controls capabilities,
daily/monthly inference and compute budgets, connections, network domains and
per-action confirmations. The application shows usage, gating and redacted history.

The original E11 implementation used scripted chat and simulated provider/work
adapters. Optional extensions below add a real interviewing assistant, model
inference, PayPal Sandbox and hosted scheduling. Gmail/Reddit actions and ad
delivery remain simulated.

## Current submission build

The application at `c0839a4` was deployed to
[Habitat on Render](https://habitat-aicl.onrender.com) on October 23, 2026.
The web app, scheduled dispatcher and registered `habitat_agent` Workflow are
deployed; health checks and existing-session access passed. The hosted app needs
a privately supplied access link. A complete hosted scheduled paid-work journey
has not yet been recorded, and the optional cloud-browser runtime is not enabled
on that deployment.

| Capability | Implemented behavior and demonstration boundary |
| --- | --- |
| Owner controls | Persisted capabilities, daily/monthly inference and compute limits, reservations, pause/resume and audit history |
| AI assistant and worker | Optional OpenAI Agents SDK assistant and GPT-6 Sol inference; a real model call and its usage settlement were verified locally |
| PayPal | Real Sandbox Orders API, hosted buyer consent and server-verified capture; separate $5 service funding and $30 seller purchase were verified with test money |
| Scheduling | Durable jobs and Render Workflows integration; deployment is verified separately from end-to-end hosted work execution |
| Owner Requests | Questions, scoped permissions, sign-in handoffs and exact purchase decisions; work waits durably for the owner |
| Audit | AG Grid history plus an AG Studio Agent Operations dashboard with linked costs/jobs, current owner requests and saved layouts. Studio AI is hard disabled; see [AG Studio setup](docs/ag-studio.md) |
| Advertising | Fixed merchant offers, creative, ad delivery and campaign metrics remain scenario fixtures; no real ads are placed |

The local demo below runs without provider credentials. To reproduce external
integrations, use your own OpenAI and PayPal Sandbox accounts with the linked
setup guides. Never use real payment credentials with this prototype.

The local [mock PayPal MVP](docs/mock-paypal-mvp.md) extends that baseline with a
funding → inference → exact purchase approval → buyer checkout → task-resume
journey. Payments, the merchant and model responses are local fixtures; balances,
policy checks, receipts and task state persist in SQLite.

The optional [PayPal Sandbox integration](docs/paypal-sandbox.md) uses PayPal-hosted
buyer checkout and server-verified captures for funding and approved purchases.
It runs separately on port 4180 with its own database and requires Sandbox app
credentials and test accounts. Real inference is an explicit option below; ad delivery remains simulated;
there is no live-payment mode. Both service funding and an owner-approved purchase
have completed PayPal-hosted Sandbox checkout and capture; the setup guide records
that evidence.

The [Render deployment](docs/render-deployment.md) adds unattended scheduled work
through Render Workflows and a cron dispatcher. AICL keeps credentials, reserves
inference and compute allowances, verifies outputs and preserves independent
purchase approval. The hackathon profile requires a private access link before
visitors can enter any email address and sign in immediately. The link opens a
browser-bound sign-in form for ten minutes. Each visitor gets an isolated temporary
workspace with a paused PocketPlan sample agent. No email is sent, verified or
stored, and the address cannot recover another browser session's workspace.
Shared operator-controlled inference and compute ceilings still apply. Configure
`AICL_ACCESS_LINK_TOKEN` and share the resulting access link privately as described
in the deployment guide. Local test helpers remain unavailable. The deployment
is live; its complete scheduled-work proof remains a separate verification step.

## Run locally

In the existing `habitat-ai` workspace, the canonical application checkout is
`habitat-mvp` on local `main`. The former `e11-epic-completion` path is a local
compatibility link. Use this checkout's own `.venv`; archived repositories are
not required for new launches. See the [consolidation record](docs/development/repository-consolidation.md)
for the preserved history and backup locations.

Use Python 3.12 from the repository root:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r backend/requirements.lock
PYTHONPATH=backend python -m aicl.demo_server
```

Open <http://127.0.0.1:4173>, request a sign-in link for `demo@example.test`, then
open <http://127.0.0.1:4173/__test__/last-magic-link?email=demo%40example.test>
and follow the captured link. Confirm sign-in to reach the workspace. This local
demo needs no SMTP account and keeps its database in `.ctx/mock-commerce/demo.db`
across restarts. The mock payment process uses port 4174; use `--port 4175` if
4173 is occupied, or choose distinct `--port` and `--payment-port` values.
The isolated automated-test
server remains available as `python -m aicl.test_server`.

For a short offline walkthrough:

1. Create an agent with **Inference** enabled. Open **Goals & schedule** and
   choose **Use app marketing example** before saving a custom workflow.
2. Set positive daily/monthly inference and compute limits, enable purchases
   with a $30 allowance, and add $5 service credit through mock checkout.
3. Enable the schedule, expand **Demo controls**, and advance one scheduled run.
   Review its campaign plan and the exact purchase request in **Requests**.
4. Approve that request and complete mock buyer checkout. Review the receipt,
   continuation and linked job in **Audit**. Pause the schedule to stop new work.

All payments, model output and advertising in this default walkthrough are
fixtures. The persisted authorization, accounting and task-state transitions are
real application behavior. For PayPal-hosted Sandbox checkout, follow
[the Sandbox guide](docs/paypal-sandbox.md); add the inference flags below for
real model output.

The [application guide](docs/aicl-mvp.md) covers the full demo, persistent local
configuration, routes, checks and operational limits.

### GPT-6 Sol inference for the PocketPlan demo

The scheduled PocketPlan workflow can call OpenAI's Responses API with the exact
model `gpt-6-sol` to write campaign plans and interpret performance reports from
saved goals, criteria and supplied evidence. Enable this explicitly:

```sh
PYTHONPATH=backend python -m aicl.demo_server \
  --inference openai --inference-key-file /absolute/path/to/private-openai.env
```

The private file contains `OPENAI_API_KEY=...`. It is read as literal text, never
executed or sent to the browser. An existing `OPENAI_API_KEY` environment variable
can be used instead by omitting `--inference-key-file`. API access and billing
must be enabled for this model on that key's account. The existing mock demo
remains the default and requires no OpenAI account. The same inference flags
work with `aicl.sandbox_server` to combine real inference with PayPal Sandbox.

AICL reserves at most **$0.052 per model request** (16,000 input and 2,000 output
tokens at the pinned standard rates) before dispatch. A separate **$1 total API
ceiling per database** includes unresolved reservations; mock or Sandbox funding
cannot enlarge it. Agent resource limits and service credit are also enforced.
Use `--inference-max-spend-micro-usd` to set a lower ceiling. Known usage settles
once; ambiguous provider outcomes retain their reservation and are not silently
retried. Restarting the server against the same database preserves this history.

Create or open a PocketPlan workflow, save its goals and criteria, fund service
credit, enable inference and the schedule, then advance the demo's scheduled
occurrence. Campaign plan/report details show the model, provider response ID,
token usage and cost. The completion gate checks the output structure and the
model's assessment of the saved criteria; the owner still reviews quality and
factual correctness. Nothing is generated by merely opening an Audit page.

Advertising metrics and delivery, the schedule clock, and quote-bound creative
remain fixtures. GPT-6 Sol interprets supplied metrics rather than claiming to
measure real advertising performance. The owner still approves the exact fixed
merchant offer. General workflows remain simulated. The owner assistant is a
separate opt-in below. This inference flag does not activate a background scheduler or buy ads.

Model and pricing reference: [GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol).
The request uses explicit prompt caching with no cache breakpoints to avoid
cache writes; see [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching).

### Interviewing and monitoring assistant

The owner assistant uses the OpenAI Agents SDK for Python and GPT-6 Sol. It asks
about outcomes, audience, inputs and completion criteria, then prepares a visible
agent proposal. It can inspect owned agents, spending, scheduled jobs, purchases
and deliverables, and prepare pause/resume proposals. Enable it with:

```sh
PYTHONPATH=backend python -m aicl.demo_server \
  --inference openai --chat openai \
  --inference-key-file /absolute/path/to/private-openai.env
```

Open **Assistant** in the sidebar. Review the saved proposal and click **Create
agent** to create its draft and workflow atomically. The draft has inference
permission, zero resource limits and a disabled schedule. Set controls and fund
it through the existing owner flow. The supported worker remains the reviewed
PocketPlan marketing example; the assistant does not create arbitrary executable
agents or claim that simulated advertising is real. Budget notes in a proposal
are informational; enforceable limits remain in the owner's controls.

Only owner-authenticated confirmation POSTs apply proposals. Confirmations bind
to the exact proposal version; schedule changes also recheck configuration and
policy versions. The model cannot confirm changes, approve purchases, fund work,
increase budgets or obtain credentials. Reads never dispatch scheduled work.

Assistant inference has a separate persistent **$1 operator-funded allowance per
database**, configurable with `--assistant-max-spend-micro-usd` or
`AICL_ASSISTANT_MAX_SPEND_MICRO_USD`. It does not spend a not-yet-created agent's
credit. Every request reserves $0.12 before dispatch, has a 2,000-token
output limit, and a chat turn is bounded to five model requests. The tool loop
uses escaped text, strict function schemas and bounded context. Requests have
durable replay keys; SDK/provider retries and exported tracing are disabled.
Unknown charges retain their hold and stop further requests until an operator
reconciles them against provider usage. Restarting does not replenish allowance.

For hosted configuration, set `AICL_CHAT_MODEL_MODE=openai` and `OPENAI_API_KEY` in
the control-plane server environment. The existing `fake` mode remains available
for deterministic tests and offline demonstrations.

## Implementation and acceptance

The current release adds the optional integrations and owner workflow described
above to the original E11 baseline. Its release candidate passed all eleven
mandatory jobs in
[pipeline 2983288088](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2983288088)
and was merged through
[MR !79](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/79).
The records below describe their named historical candidates, not every later
feature or the current deployment. GitLab evidence links may require access;
the source and local setup instructions are sufficient to run the offline demo.

E11-1 through E11-5 are integrated and verified at
`ca4e172241a484c174ce37e4a8642aabd511945a`. All eleven mandatory jobs passed in
[pipeline 2959718088](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2959718088),
with a separate [whole-epic review](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/issues/11#note_4036886044).
That pipeline records the five-ticket baseline before E11-6. The
[E11 evidence record](docs/plan/E11/completion.md) preserves the integration history.

The separately requested [E11-6 UI refinement](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/work_items/19)
was developed on `codex/e11-ui-polish`. It adds responsive navigation, workspace
cards and status summaries, grouped owner controls, readable activity, and explicit
pending/uncertain request feedback. Application source `419e77b` passed its separate
review and [pipeline 2960426331](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2960426331),
including 73 backend tests and four browser journeys. The combined stable-main
integration is tracked by [MR !45](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/45).
Its current pipeline records integration evidence; no deployment is implied.

Click anywhere on an agent card to open its details. **Budget** contains resource
limits and the separate purchase allowance; **Funding** contains service credit,
top-ups and payment history. **Task** runs the mocked purchase journey and explains
missing setup in a dialog. These sections share one page with **Capabilities** and
**Activity**. The separate **Simulated control test** exercises existing controls;
it does not generate model output or buy an asset. Known results refresh the page's
usage and controls; uncertain results ask you to review activity before retrying.

## Repository guide

- [Local mock PayPal MVP and walkthrough](docs/mock-paypal-mvp.md)
- [PayPal Sandbox setup, checkout and verification](docs/paypal-sandbox.md)
- [Stable baseline and itemized PayPal MVP updates](docs/paypal-mvp-backlog.md)
- [Current E11 scope and decisions](docs/plan/E11/_epic.md)
- [Design index and contracts](docs/design/README.md)
- [Application setup and operation](docs/aicl-mvp.md)
- [PayPal target demo script and implementation gaps](docs/hackathon-demo-script.md)
- [PayPal funding design for agent inference and resources](docs/design/paypal-funding/spec.md)
- [Agent purchases through PayPal](docs/design/agent-purchases/spec.md)
- [PayPal demo readiness and control rehearsal findings](docs/hackathon-demo-rehearsal.md)
- [Development and evidence workflow](docs/development/ctx-contract.md)
- [Historical marketing-agent proposal](docs/habitat-mvp.md)

This application was developed in the Transcend Hackathon Showcase workspace.
Earlier E2 plans and E11 acceptance records remain for traceability. Read this
README and the integration guides for current capabilities and limitations.

Cloud sign-in requests now support an owner-controlled private browser handoff,
encrypted access for the same agent's scheduled jobs, and a restricted worker
page-read tool. See [Cloud browser setup and rollout](docs/cloud-browser.md).
The browser runtime is optional and separate from the web app; the Render host's
Chromium sandbox support must be verified before enabling it.
