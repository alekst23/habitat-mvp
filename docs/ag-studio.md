# Agent Operations with AG Studio

Open **Audit → Agent operations** at `/audit/studio`. The page embeds the real
AG Studio 3.0.0 JavaScript library in Habitat's existing authenticated shell.
It supplies a starter dashboard with spending by agent, source-linked costs and
jobs, and a custom Needs attention widget leading to existing owner review pages.
Shared agent/date filters, refresh status, a rule-based **Spending without accepted
work** preset, and owner-specific saved layouts work without a model connection.
The page opens in view mode; **Edit layout** enables arrangement on wider
screens. Mobile stacks widgets and preserves the desktop arrangement when saving.

The page reads persisted records. Opening or filtering it never schedules work,
places an order, changes a budget, approves a request, or calls a model.
Dashboard editing changes presentation; approval and execution remain in their
existing owner flows.

## Data semantics

- Current service credit, held funds, budget headroom and pending attention ignore
  the date range. They respect the selected agent.
- Period spending uses recorded timestamps; merchant payments use capture receipt
  timestamps. Jobs use their scheduled timestamp. Bounds are inclusive local
  calendar dates in America/New_York.
- Accepted counts use the latest output review state of period-selected jobs.
  They are not a count of reviews performed during the period.
- Service funding, resource consumption and purchase reservations are separate.
  Funding plus usage would double-count the same money. Merchant payments are
  distinct from service funding; compute values are recorded runtime estimates.
- Shared compute dispatches remain at agent level when they cannot be attributed
  to one job. The dashboard does not invent a per-job allocation.
- Each cost/job carries provenance: fixture, PayPal Sandbox, provider-reported,
  runtime estimate, application record, or mixed. A table name containing `mock`
  is not sufficient to determine provenance; the payment/attempt records decide.
- Operator-funded setup and dashboard assistants are outside agent cost totals.

The read API is `/audit/studio/data`, with `instance_id`, `date_from`, `date_to`
and `timezone`. It derives tenant and owner identity from authentication and
reads one SQLite snapshot. It exposes no provider credentials or output bodies.
Layout reads/saves use `/audit/studio/state`; saves require CSRF and the current
version, so another tab's saved layout is not silently overwritten.

## Assets and licensing

```sh
npm ci
npm run build:studio
```

The build copies the pinned official UMD bundle and its licence from `ag-studio`
into `backend/aicl/web/static/vendor/`. It also copies the small Habitat adapter.
The checked-in assets let the Python container serve the page without Node at
runtime or a CDN connection. Existing AG Grid Community Audit pages remain
available. Rebuild vendor assets after changing the runtime adapter or dependency.

AG Studio is commercial software; the existing Community Grid licence does not
cover it. Set `AICL_STUDIO_LICENSE_KEY` to the vendor-issued trial/commercial key.
The vendor key is intentionally passed to the browser. Use a key with AI
entitlement for the analyst and arrange coverage through the judging period.
Local unlicensed evaluation displays the vendor's evaluation notices.
See the [AG Studio licence](https://www.ag-grid.com/studio/react/enterprise-licence/)
and [hackathon sponsor brief](https://paypalaihackathon.devpost.com/details/aggrid).

## Optional Studio analyst

```text
AICL_STUDIO_AI_ENABLED=1
AICL_STUDIO_AI_MAX_SPEND_MICRO_USD=1000000
OPENAI_API_KEY=<server-side key>
```

Studio's native Agent Framework uses Habitat's adapter at `/audit/studio/ai`.
The adapter maps native text and client function calls to the existing fixed
`gpt-6-sol` Responses model. Model credentials stay server-side. It does not
accept provider URLs, images, remote files or provider-hosted tools. The supplied
Studio tools operate on loaded dashboard data and presentation, not owner powers.

Each model request reserves its maximum before dispatch against a separate
operator-funded database allowance (default $1). Usage is settled from the
provider response before any tool instructions reach the browser. Request IDs
replay saved responses; there are no automatic provider retries. Uncertain
charges remain reserved and block further model requests until reconciled.
This allowance does not spend agent service credit or increase agent limits.

With AI disabled, the page explicitly says it is unavailable. The preset button
uses a deterministic rule and is labelled as a preset, not an AI response.

## Verification and demonstration

```sh
PYTHONPATH=backend:backend/tests .venv/bin/python -m pytest backend/tests/integration/test_studio*.py -q
node --test tests/studio-runtime.test.cjs
PATH="$PWD/.venv/bin:$PATH" npx playwright test tests/browser/studio.spec.ts tests/browser/studio-ai.spec.ts --config .gitlab/ctx/playwright.config.ts --reporter=list
```

The assistant browser check uses the real Studio agent harness and schema tool
with scripted responses, then validates the captured requests through the backend
mapper. It incurs no provider charges and does not establish live model quality.

For the demo: select an agent/date range, inspect a cost's source job or receipt,
open the next owner request, review an output, return and refresh, rearrange a
widget, save and reload the layout. With the analyst enabled, ask it to show
agents with spending but no accepted outputs and visibly create/update a widget.
Use explicit fixture/Sandbox labels and separately verify any claimed hosted
model/payment journey. Existing local demo samples do not establish live ROI.
