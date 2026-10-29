# Reviewing agent work

The Audit workspace reads both scheduled workflow records and durable agent
runtime records. The owner should not need to return to the creator to find a
saved result or reconstruct which run produced it.

## Review inbox

The selected work-review design is the **Review inbox**, available at `/work`.
It is the default signed-in home when the durable agent runtime is enabled.
Agents remain available at `/workspace` for setup, permissions, funding and work
controls. Legacy scheduled workflow results remain in Audit, linked from the inbox.

- A compact run list sits beside the selected report. Search covers agent names,
  goals and saved output names; agent, date, unseen, attention and saved filters
  narrow the list. Dates filter run start time in UTC. Cursor pagination reaches
  older runs without a fixed history cutoff, and the list scrolls independently.
- Report, Sources, Activity and Cost tabs keep the output and its provenance
  together. Reports render safe Markdown, retain earlier versions and partial
  drafts, and support links to a particular run and output. Original instructions
  stay available in a collapsed brief.
- **Seen** and **Saved** are explicit, reversible owner-specific marks. Seen tracks
  the run version, so a changed run becomes unseen again. Neither mark approves a
  result, resumes work, changes permissions or charges the owner.
- The collapsible assistant panel links to the existing agent assistant for future
  goals and settings. It does not imply that the assistant receives the selected
  historical report; report-specific conversation is not implemented.
- Browsing, filtering, refreshing and local log downloads do not dispatch model,
  search or page requests. Source references are inert until the owner opens a link.
  Raw HTML stays text and external images do not load.

The inbox uses authenticated owner/tenant scope and a consistent read snapshot.
Definition, checkpoint and artifact metadata is integrity-checked before search,
counts or display. Detail reads verify saved content; mark writes require CSRF and
the selected run version. Existing ledger projections supply recorded costs;
reservations, estimates and unavailable metering remain distinct. Setup and other
runs are excluded from a selected run's total. Activity labels distinguish writing
worker model decisions from additional research calls inside tool actions.

## Action details

Action names in workspace logs and inbox activity open a shared inspector; full
Audit provides the same **View request and result** control. The owner-only
`GET /api/audit/runs/{run_id}/steps/{step_id}` loads one action lazily, with its
saved model context or tool arguments, returned adapter payload, errors, usage,
costs and related research evidence. Complete JSON can be downloaded locally.
Records render as text, including HTML and URLs. Opening or downloading details
never calls the model, fetches a source, replays work or changes the ledger.

All referenced content is verified for owner, tenant, run, kind and digest inside
a consistent read snapshot. Responses use `Cache-Control: no-store`. Reused reads
are identified as reused evidence; missing responses stay pending or unknown.

New research runs retain planner context and parsed results, plus the approved
network request before dispatch and the broker's status/extracted evidence after
it returns. The request projection includes method, URL and approved public
headers; credential injection remains exclusively in the broker. These immutable
journals are never added to model context or used as execution authority. Receipt
storage failure after paid dispatch preserves the unknown-outcome reservation.

Historical gaps are explicit: older research runs retain source evidence and
planner usage but may lack the exact search query and planner input/output. Saved
adapter context is not a full provider HTTP body, and returned application payloads
are not raw HTTP responses. Authentication headers, raw provider response headers
and raw page HTML are not newly retained or reconstructed.

## Review flow

1. Select an agent and date range in Agent operations or any Audit tab. Those
   filters travel in the URL through tab changes and source-record drilldowns.
   Purchase and deliverable status choices are retained separately because their
   states have different meanings.
2. Open a completed output or saved draft from Saved outputs or Deliverables.
   Earlier versions remain accessible from the output's history. Cancelled runs
   retain saved drafts.
3. Follow the output to its source run to inspect model decisions, tool steps,
   recorded usage, plan progress, and run history. Actions combines the existing
   control audit with durable run events, steps, output saves, and setup usage
   in a table with date, agent, action, outcome, details and evidence links.
4. Use Costs & statistics to compare jobs, then inspect the individual resource
   entries behind a job total. Follow each entry to its source evidence.
   Refreshing or reviewing a record never dispatches work or modifies the
   accounting ledger.

The agent workspace keeps results and their run's **Actions and costs** together.
Saved Markdown is rendered with DOM elements for headings, lists, emphasis,
links, code, quotes, and tables; raw HTML stays text and images do not load.
The expandable log lists model and tool steps, recorded usage, and per-step
costs, with an owner-scoped audit link and a local JSON download. Its totals
reuse the audit ledger, separate reservations and estimates, and exclude setup
and other runs. Viewing or downloading the log does not execute work.

AG Studio renders the Operations tables and chart, the Costs & statistics job
rollup and ledger, Actions, source-job resource entries, and Campaigns performance
tables. Output previews remain reading views. All these grids use native sorting
and filters, with server-rendered audit tables available if the library fails
to load. A shared helper enables column resizing through the public AG Grid API
supplied by Studio's cell-renderer hook; AG Studio 3.0.0 otherwise disables resize
in its built-in grid. The vendor bundle and Studio's data path are unchanged.
Dragged widths survive updates for the current grid, but are not persisted by
Save layout or across page reloads/navigation. An empty grid initializes the
enhancement when its first rows arrive.

## Evidence and accounting

Durable run content is read through the repository's owner, tenant and integrity
checks. Audit reads use a consistent SQLite snapshot, so a concurrent worker
cannot produce a mixture of old checkpoints and newly saved output. The compact
Operations feed exposes output metadata and links, not output bodies or prompts.

Settled usage comes from `budget_usage` and its owned runtime holds. Setup costs
use the existing workspace attribution rules; pending, charged and waived costs
remain distinguishable. Unknown outcomes remain reservations, not settled spend.
Available service credit uses the same calculation as execution admission.
Current balances stay current while period spending and recorded work use the
selected dates. Funding, reservations, merchant payments and consumed service
credit are separate categories.

The cost view uses two levels: a job rollup for comparison and normalized source
entries for inspection. Each entry carries its resource component, accounting
kind, amount, status, coverage note and evidence reference. The shared projection
preserves the original amounts and references; a rollup is not a second charge.
Only recorded usage and runtime estimates contribute to the explicitly labelled
**Recorded + estimated** total. Reservations, funding, waived setup and merchant
payments remain separate. Setup and shared costs without a recorded job link
remain **Setup / unallocated work** at agent level instead of receiving a guessed
allocation.

Model, tools/network, compute, storage/data access and unknown resources can be
reported independently when the ledger supports that distinction. If a receipt
combines model tokens and search fees without separate prices, one **Model +
tools** entry preserves the full amount and is counted once. The view does not
reprice old calls to invent a split. **Not metered** means no separate charge is
recorded; it does not mean storage, data access or tool usage was free. These
coverage limits appear alongside the totals and entries.

An agent's completion claim and criterion assessments do not create owner
acceptance. Runtime outputs are read-only audit evidence, with links to the
existing agent workspace for guidance or further work. Legacy scheduled outputs
retain their existing accept/revision workflow. No synthetic acceptance,
backfilled usage, new charges, or replay of historical runs is introduced.

## Regression evidence

Focused coverage lives in `test_runtime_audit_projection.py`,
`test_studio_data.py`, `test_cost_breakdown.py`, and `test_audit_navigation.py`.
Shared grid and audit-table
tests run with `npm run test:studio-runtime`. The browser navigation
journey is `tests/browser/audit-navigation.spec.ts`. These exercise saved output
versions, exact accounting, unknown holds, owner isolation, concurrent reads,
tab/filter persistence, and read-only inspection. Local browser checks use
synthetic providers and a disposable database.

Action-detail checks in `test_runtime_action_details.py` cover owner boundaries,
pending receipts, scoped references, corruption and read-only API behavior.
`test_runtime_agent_research.py` checks request-before-dispatch journaling,
credential exclusion and preservation of unknown holds on receipt-write failure.

Inbox coverage is in `backend/tests/integration/test_work_review.py` and
`tests/work-review-ui.test.cjs`. It covers pagination across 45 runs, filters,
saved versions, owner isolation, integrity failures, exact costs, CSRF-scoped marks,
selection races, inert hostile content and mobile overflow. Live browser review
checks the existing saved report without dispatching another paid run.
