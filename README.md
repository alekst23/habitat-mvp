# Habitat owner-control MVP

Habitat's Configurable AI Control Layer lets an owner create and manage a Default
agent instance through a wizard or built-in chat. The owner controls capabilities,
daily/monthly inference and compute budgets, connections, network domains and
per-action confirmations. The application shows usage, gating and redacted history.

This E11 implementation is a control-plane prototype: chat is scripted, OAuth
providers and work execution are simulated, and no model call or Gmail/Reddit
action is performed. That original E11 scope excluded PayPal, a running autonomous
agent and deployment; the payment extension below adds PayPal Sandbox.

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
in the deployment guide. Local test helpers remain unavailable. A live Render
deployment and its scheduled execution proof are still required.

## Run locally

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
across restarts. Use `--port 4174` if 4173 is occupied. The isolated automated-test
server remains available as `python -m aicl.test_server`.

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
merchant offer. General workflows and the chat creation assistant remain
simulated. This integration does not activate a background scheduler or buy ads.

Model and pricing reference: [GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol).
The request uses explicit prompt caching with no cache breakpoints to avoid
cache writes; see [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching).

## Implementation and acceptance

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

This repository is the Transcend Hackathon Showcase workspace. The earlier E2
PayPal/marketing proposal remains for traceability; it is not the implemented
E11 scope.
