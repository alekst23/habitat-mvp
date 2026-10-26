# Agent Operations with AG Studio

Open **Audit → Agent operations** at `/audit/studio`. The page embeds the real
AG Studio 3.0.0 JavaScript library in Habitat's existing authenticated shell.
It supplies a starter dashboard with spending by agent, source-linked costs and
jobs, and a custom Needs attention widget leading to existing owner review pages.
Shared agent/date filters, refresh status, a rule-based **Spending without accepted
work** preset, and owner-specific saved layouts use persisted application records.
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
- Operator-funded setup is outside agent cost totals. Studio performs no model work.

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
into `backend/aicl/web/static/vendor/` and removes the retired model adapter asset.
The checked-in assets let the Python container serve the page without Node at
runtime or a CDN connection. Existing AG Grid Community Audit pages remain
available. Rebuild vendor assets after changing the dependency.

AG Studio is commercial software; the existing Community Grid licence does not
cover it. Set `AICL_STUDIO_LICENSE_KEY` to the vendor-issued trial/commercial key.
The vendor key is intentionally passed to the browser. Arrange licence coverage
through the judging period.
Local unlicensed evaluation displays the vendor's evaluation notices.
See the [AG Studio licence](https://www.ag-grid.com/studio/react/enterprise-licence/)
and [hackathon sponsor brief](https://paypalaihackathon.devpost.com/details/aggrid).

## Studio AI is hard disabled

The dashboard has no assistant UI, AI module registration, model adapter or
model-dispatch route. The legacy `/audit/studio/ai` endpoint unconditionally
denies requests with HTTP 403, and a nonzero legacy AI enable flag fails startup.
A model key, legacy page attribute or old runtime global cannot enable it. The official
vendor bundle remains unchanged, but Habitat only initializes its dashboard
features. Studio cannot dispatch model work outside AICL.

Historical `studio_ai_request` records remain available for audit; the application
has no writer for new Studio model requests.

Filters, charts, source links, custom widgets and saved layouts remain available.
The preset button uses a deterministic rule and is labelled as a preset.
Agent execution and owner decisions stay in their existing AICL-controlled flows.

## Verification and demonstration

```sh
PYTHONPATH=backend:backend/tests .venv/bin/python -m pytest backend/tests/integration/test_studio*.py -q
node --test tests/studio-runtime.test.cjs
PATH="$PWD/.venv/bin:$PATH" npx playwright test tests/browser/studio.spec.ts tests/browser/studio-ai.spec.ts --config .gitlab/ctx/playwright.config.ts --reporter=list
```

The negative AI browser check injects legacy enable attributes and an old runtime
global, then verifies there is no assistant UI, adapter use or AI request in view
or edit mode. No provider calls are made. Runtime checks compare the served vendor
bundle and licence byte-for-byte with the pinned package and confirm the model
adapter files are absent.

For the demo: select an agent/date range, inspect a cost's source job or receipt,
open the next owner request, review an output, return and refresh, rearrange a
widget, save and reload the layout. Use the preset to show agents with spending
but no accepted outputs.
Use explicit fixture/Sandbox labels and separately verify any claimed hosted
model/payment journey. Existing local demo samples do not establish live ROI.
