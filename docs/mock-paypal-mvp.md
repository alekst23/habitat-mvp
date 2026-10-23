# Local mock PayPal MVP

This implementation exercises Habitat's two payment roles without external accounts
or credentials. **All payments, merchant responses, model usage and output are
local simulations.** It is neither PayPal Sandbox nor a live PayPal integration.

The application controls are real: owner authentication and CSRF, SQLite records,
funding and usage accounting, purchase policy, exact transaction approval,
idempotency, receipts and durable task state. The demonstration now connects the
payment workflow to a **separate local mock payment API over HTTP**. That provider
keeps its own durable orders and captures in a separate SQLite database. Seller
delivery and inference remain in-process fixtures. Development and test
environments expose the demo; production does not expose its routes.

## Run locally

Use the normal Python 3.12 environment and locked backend dependencies from the
[application guide](aicl-mvp.md), then run from the repository root:

```sh
PYTHONPATH=backend python -m aicl.demo_server
```

The launcher starts both services, waits for the payment API to be ready, and
prints both addresses and database locations:

| Service | Address | Persistent database |
| --- | --- | --- |
| Habitat | `http://127.0.0.1:4173` | `.ctx/mock-commerce/demo.db` |
| Mock payment provider | `http://127.0.0.1:4174` | `.ctx/mock-commerce/demo-payments.db` |

Both listen only on loopback. A generated shared token is saved in the ignored,
owner-only `.ctx/mock-commerce/.mock-payment-token` file and passed to the child
process without printing it. Stop the launcher with Ctrl-C to stop both services.
It refuses to attach to or stop an unrelated process on the payment port. If
another preview is running, choose two free ports and a separate application DB:

```sh
PYTHONPATH=backend python -m aicl.demo_server --port 4183 --payment-port 4184 --database .ctx/mock-commerce/rehearsal.db
```

Open the printed address and request sign-in for `demo@example.test`. No email is
sent. Open `/__test__/last-magic-link?email=demo%40example.test` on the same address,
follow the returned link, and confirm sign-in. Restart with the same database and
port to retain agents, credits, purchases and receipts. The fixed local test keys
and captured-mail routes are for this loopback demonstration only.

The existing private preview runner `.ctx/ui-demo/serve.py` uses the same process
manager with its preserved `.ctx/ui-demo/aicl.db`, separate
`.ctx/ui-demo/aicl-payments.db`, and existing local demo sign-in. Run it as
`PYTHONPATH=backend python .ctx/ui-demo/serve.py`; optional positional app and
payment ports default to 4173 and 4174. Do not launch it concurrently on the same
ports as `aicl.demo_server`.

## Payment API boundary

Funding and purchase actions use the same server-side payment adapter. Habitat
owns the agent, exact approval, spending holds, service-credit ledger and task
state. The mock provider owns payment orders and captures. Habitat checks the
returned order identity, merchant, amount, currency and capture status before
crediting an agent or delivering its purchase. A pending payment cannot fund work
or trigger delivery. Retrying uses the same durable order rather than creating
another payment.

The HTTP API is a small Orders-shaped fixture for integration testing, not a
complete emulation of PayPal. Its buyer-consent controls are mock endpoints;
it does not implement PayPal OAuth, Sandbox, webhook signing or a real wallet.
The final payment controls carry a small “Demo checkout — no real charges” note.
Repeated environment banners and mock/simulated labels are removed from the
normal journey; this is a presentation change only. Payment transport
failures must leave the workflow waiting for a confirmed provider result rather
than recording a successful payment. The boundary exposes order creation and
lookup at `/v2/checkout/orders`, capture at
`/v2/checkout/orders/{id}/capture`, and fixture-only approval, pending and cancel
actions below `/mock/orders/{id}`. Payment endpoints require the local bearer
token. `GET /health` reports readiness without order or credential details.

Normal application configuration selects the HTTP adapter with
`AICL_MOCK_PAYMENT_API_URL=http://127.0.0.1:4174` and an
`AICL_MOCK_PAYMENT_TOKEN` of at least 24 non-whitespace ASCII characters. Only the exact loopback URL form with an explicit port
is accepted: no path, credentials, query, fragment, redirects or environment
proxy. The mode is prohibited in production. The provider CLI is
`python -m aicl.commerce.payment_api --db PATH --port 4174` and reads the same token
from its environment; prefer the managed demo launcher so lifecycle and token
setup stay together.

When the URL is absent, existing tests and local fixtures retain the inline
payment adapter. New demo orders use HTTP. An order retains its original
transport so upgrading a preserved demo database does not reinterpret old
inline orders as provider-created orders. No real PayPal credentials are needed
or accepted by this mock configuration.

## Scheduled owner workflow

### PocketPlan app marketing example

The app-marketing example uses a fictional mobile planner, **PocketPlan**, and a
fictional seller, **LaunchPad Ads**. All campaign delivery, attributed installs,
payments and inference remain local fixtures. No advertising platform is contacted.

Create a new agent with inference enabled, open its Goals & schedule page, and
choose **Use app marketing example**. Existing configured agents retain their
work and history. Set inference/compute limits, add $5 of service credit, and
enable purchases with a $50 cumulative allowance. The allowance is permission
to request purchases, not payment or blanket approval. Enable the daily schedule
and use Demo controls to advance the next scheduled occurrence.

The first job prepares a campaign plan and ad creative before any advertising
purchase. Its separate proposal requests a $30 prepaid, three-day test, capped
at $10 per campaign day. Review the audience, creative, destination, rationale,
alternative and decline outcome alongside the supporting job. Approve the exact
proposal, select the continuation, and complete its separate mock PayPal checkout.

Payment funds the campaign; it does not prove ads ran or produced installs.
Subsequent eligible demo days record bounded delivery and performance reports.
The optional $15 broader-audience test is a separate approval. Declining it
preserves the original campaign and its reports. Declining the original campaign
preserves the plan and allows an organic-only report without advertising charges.

Audit separates inference credit/usage, prepaid advertising funds, consumed ad
spend and remaining advertising credit. Consuming prepaid funds is not another
PayPal payment. Reports link back to their source jobs, retain review/version
history, and distinguish completion checks from marketing performance targets.
The fixed scenario is a bounded demonstration, not an arbitrary campaign generator.

The 2026-10-22 browser rehearsal created **PocketPlan Marketing Agent**
(`5098b3ef-d24f-4439-9665-3963390856a3`) and completed $5 service funding,
the exact $30 campaign checkout, three scheduled campaign days, a declined
$15 expansion and an accepted day-two report. The final report reconciles
$30 consumed, $0 remaining, 106 clicks and 23 attributed installs (aggregate
CPI $1.30), and requires fresh approval for another campaign. These are scenario
figures, not measured advertising results. The Campaigns tab uses AG Grid for
daily metrics and links each row to its source job.

The backend suite passed **167 tests**: 165 in the main run and the two loopback
process tests separately while the preview port was free. This is local
verification, not CI or real PayPal verification.

The workspace now opens **Goals & schedule** for each agent. Audit is a separate
navigation destination. Normal work has no manual Start task step.

1. Save the agent goal, context, deliverable names/content, and one completion
   criterion per line. Existing saved briefs or agent instructions prefill the
   goal. Add more deliverables if needed; mark only work that requires a purchased
   resource. Configuration is versioned and copied into each job.
2. Review AICL controls and funding. Enable inference and set daily/monthly
   inference and compute limits (for example $1/$10). If resources will be
   purchased, enable purchases and set a separate cumulative purchase limit.
3. Add service credit with PayPal. The amount, recipient and agent carry into
   checkout. Choose a fixture buyer the first time; future orders remember that
   owner-level choice. Every payment still requires separate checkout consent.
4. Select hourly or daily scheduling and a timezone. Daily runs are at 9 AM local
   time; hourly runs use the next UTC hour boundary. **Enable schedule** activates
   a draft or paused agent through the existing controls. Saving configuration
   does not run work. Old Enable forms cannot override a later Pause.
5. Expand **Demo controls** and choose **Advance to next scheduled run**. This
   explicitly simulates the next occurrence; there is no background cron worker.
   Only the schedule clock advances. Authentication, payment expiry, accounting
   and budget periods retain the application clock. Duplicate occurrence requests
   do not create duplicate jobs or charges.
6. Open Audit independently. Work without a purchase can submit an output while
   other work waits for approval. The purchase inbox includes prior runs and
   legacy requests. Each scheduled purchase shows the deliverable it supports,
   its scheduled occurrence, saved output scope and configured resource dependency.
   **View source job** opens the original brief and criteria, all quotes for that
   job (including expired replacements), and its output versions. Editing the
   agent configuration does not rewrite this history. Approval is bound to the
   exact quote. Choose **Run now** or
   **Resume on schedule**, then complete the mock PayPal checkout. The latter
   resumes the waiting job at its next eligible simulated occurrence. Run now
   continues only after confirmed payment/delivery and current control checks.
7. Open **Deliverables** to read the output and its configured criteria. Each
   scheduled output links back to its source job; completed purchases link directly
   to the resulting deliverable. The
   **Need a correction before submission** scenario fails one fixture check and
   leaves the candidate Needs work. A later occurrence produces the corrected
   version. These are deterministic scenario checks, not model-based validation.
8. **Accept deliverable** records owner acceptance of that exact version.
   **Request changes** requires feedback and queues a revision at the next
   eligible scheduled occurrence. Earlier versions, criteria and decisions remain
   available. Old results from the manual-task demo are preserved as read-only
   history, without claiming retroactive validation.
9. Inspect the **Costs & statistics** dashboard, backed by locally bundled AG Grid
   Community. Sort/filter the ledger and inspect summary statistics. Top-up
   funding, remaining service credit, inference usage, merchant spending and
   purchase holds remain distinct. Reading or filtering starts no work.
10. Pause the schedule to stop future occurrences. Existing outputs and purchase
    decisions remain accessible in Audit.

The demo permits up to six deliverable specifications, twelve criteria per
specification and five versions per job. The same pending deliverable is not
regenerated every tick, but unrelated configured work may proceed. An accepted
job closes; a later occurrence can create fresh work. Previously delivered fixture
resources can be reused. Declined/cancelled requests remain in history; a later
occurrence can create eligible work without reopening their approvals.

The selected buyer is a remembered fixture, not a real PayPal connection, vault
token or permission to charge. It is reused across that owner's agents, while
agent balances and approvals remain separate. Changing the remembered preference
does not change pending or completed orders. Fixture IDs are `demo-buyer` and
`demo-buyer-alt`; neither is a real PayPal identity.

Old `/instances/{id}/commerce` bookmarks still redirect to Funding. Funding
returns to the agent controls; payment for a scheduled job returns to Audit.
The read-only `/audit/jobs/{id}` page links job requirements, requests and outputs
within the signed-in owner's account. Checkout retains the source-job link.
Pending payments stay at the same checkout. Advanced Gmail/Reddit confirmations
and control diagnostics remain on the AICL controls page, outside the normal
scheduled-work journey.

## Failure paths to demonstrate

- Missing credit, exhausted limits, paused lifecycle and denied capabilities block
  execution before the associated inference charge. Enabling a schedule does not
  override a control gate; eligibility is rechecked on every simulated step.
- Approval alone never pays or executes. Pending/unknown payments retain the
  same order and allowance hold until reconciled. A repeated completion or a
  concurrent continuation/tick cannot duplicate that job's output or charge.
- Decline/cancel releases the applicable unpaid purchase hold while preserving
  incurred inference usage. A remembered buyer never substitutes for consent.
- Expired quotes need **Refresh proposal** and fresh exact approval. Refreshing
  keeps the old proposal and does not rerun paid planning. Uncertain payment
  outcomes must be reconciled before refreshing. There is no background expiry
  worker in this mock.
- Failed criteria prevent submission. Stale review forms cannot accept a new
  version, and stale schedule forms cannot undo a later pause.
- A blocked paid continuation keeps its reason visible. Resolve the control, then
  use the explicit continuation choice or next eligible scheduled occurrence.

## Deliberate simplifications

This iteration mocks all workflow execution. Configured text shapes deterministic
brief/copy/checklist fixtures; there is no semantic interpretation of arbitrary
instructions or actual model assessment of completion criteria. Paid resources
come from one local merchant/catalog. The payment transport crosses a real
loopback HTTP boundary; no PayPal service is contacted.

Service credit is allocated directly to an agent; there is no owner wallet or
transfer system. Purchase limits are cumulative, not daily/monthly merchant
limits. Each illustrative inference step costs $0.002 with a maximum reservation
of $0.004. All four existing inference/compute budget windows remain enforced,
even though these fixtures use zero compute minutes. Advancing demo time does not
claim to implement production budget-period rollover.

A durable background scheduler, browser-independent execution authority,
production concurrency, real inference/validation, real PayPal Sandbox/live APIs,
webhooks, refunds and cloud deployment remain follow-on work. The
[change plan](design/owner-workflow-change-plan.md) separates those items from
this mock workflow. The [funding design](design/paypal-funding/spec.md) and
[purchase design](design/agent-purchases/spec.md) remain the external integration
target. No MCP server is required for these internal mock service calls.

## Earlier local verification

The records below describe earlier manual-task/payment iterations. Current
scheduled-workflow evidence is recorded in the
[demo rehearsal notes](hackathon-demo-rehearsal.md).


The subsequent presentation cleanup passed **29 focused integration checks**.
A browser check confirmed the funding page has no environment banner or repeated
mock/simulated labels; checkout keeps only the small “Demo checkout — no real
charges” note beside the final payment controls. Pending controls are collapsed
under Payment options. Existing saved results display without former boilerplate,
while their stored content and payment identities remain unchanged. Cancellation
was verified through the renamed control. These changes do not enable real PayPal
or inference adapters.

The remembered-buyer and direct-return journey passed **60 focused backend
checks** on the 2026-10-20 working tree, including owner isolation, CSRF, concurrent
first selections, stale account-choice rejection, preservation of a newer owner
preference when an older order completes, immutable provider buyer binding, and
legacy receipt recovery. Two unchanged process-launch checks were excluded from
this run; this is not a full-suite or CI result.

A real browser walkthrough created **Remembered PayPal buyer verification**,
saved a Cedar Studio brief, selected the demo buyer while funding $5, resolved a
pending payment, and returned automatically to the same agent's setup. Purchase
approval opened the prepared $1 checkout directly with the buyer remembered.
Changing the account changed only the selection; authorizing payment returned to
the exact task with delivery and explicit resume. A later purchase was declined,
releasing its hold. Both processes were restarted: the buyer, brief, receipts,
$4.994 service credit, $1 merchant spend, and $0 hold persisted. Both completed
orders had matching buyer-bound capture receipts in the separate provider database.
Existing agents and legacy receipts were preserved.

The browser regression specification `tests/browser/mock-commerce.spec.ts` was
updated, but its CLI runner was not executed for this change; the browser evidence
above comes from the interactive walkthrough. The results below describe earlier
working trees.

The earlier mock-commerce baseline passed 84 backend tests and all five browser journeys,
including the complete mobile funding/purchase/resume flow. The commerce tests
cover capture identity and amount checks, owner isolation, CSRF, quota contention,
expiry and cancellation, replay, durable state, and production route exclusion.
Its independent code review found no blocking issues. Those results describe that
baseline, not the subsequent owner-journey changes. The focused HTTP acceptance
file `backend/tests/integration/test_owner_journey_pages.py` covers the structured
brief, setup checklist, active task and history, separate consent, explicit resume,
recovery, and escaped output. Run the current checks before treating a changed
candidate as verified. Local results are not CI, release, deployment, or real PayPal
execution evidence.

The owner-journey HTTP tests and existing commerce integration tests passed
together on the 2026-10-20 working tree: **14 passed**. That focused run also proves
the new brief endpoint rejects missing CSRF, missing sessions and another owner's
instance. The focused owner-journey, commerce, manage-page, composition and wiring checks
then passed together: **30 tests**, including the loopback server smoke test run
separately while port 4173 was free. This is a focused regression check, not a
claim that the full suite below ran on this refactor.

A real browser walkthrough on the same working tree created a separate
**Journey UX verification** agent and checked saved custom inputs, unsaved-edit
blocking, all setup controls, a $5 mock top-up, exact $1 approval, pending checkout,
capture, explicit resume and brief-specific output. A second attempt was declined;
it released its hold, preserved the brief and left the completed task in collapsed
history. The final balances were $4.994 service credit, $1 merchant spend and $0
held. A 390px mobile viewport had no horizontal overflow and displayed the current
step visibly. Existing demo agents and their records were preserved.

Readiness distinguishes starting a new task from continuing the current one. An
existing purchase hold does not require another dollar of allowance, and a paid
purchase does not require purchase permission to run its final inference step.
Lifecycle, inference permission, resource budgets and service credit still apply.

The HTTP mock configuration and process-lifecycle checks are in
`backend/tests/integration/test_mock_payment_config.py`. They cover local-only
configuration, production exclusion, masked credentials, refusing an occupied
port, private token persistence, stopping the owned child after an application
error, and restarting on the same port. These three tests passed on the
2026-10-20 working tree using a temporary provider database and ephemeral loopback
port; this does not represent Sandbox or live PayPal verification.

The HTTP mock integration passed **49 focused backend checks** on 2026-10-20,
including payment contract validation, lost-response recovery, unresolved hold
protection, ownership and CSRF, transport binding, page rendering, and existing
workflow regressions. The two loopback process checks ran separately with the
preview stopped. This is not a full-suite or CI result.

A browser walkthrough created a separate **Mock API workflow verification** agent:
$5 funding, pending status, status lookup, payment completion, a separately
approved $1 template purchase, and explicit task resume. Both payments reached
the independent HTTP provider database with distinct capture receipts. Restarting
both processes preserved the completed task and receipts, $4.996 service credit,
$1 merchant spend, $1 remaining purchase allowance, and $0 held. Existing demo
agents were preserved. Inference and merchant fulfillment remain deterministic
fixtures; this verification makes no Sandbox or live payment claim.

```sh
PYTHONPATH=backend:backend/tests:scripts python -m pytest backend/tests -p ctx_pytest_ac -q
npx playwright test --config .gitlab/ctx/playwright.config.ts --reporter=list
```

Stop an existing preview before these checks: the test server and browser runner
each require exclusive use of port 4173. Run them sequentially. Activate the same
backend virtual environment first so `python` resolves to its locked dependencies.
