# Habitat owner workflow change plan

**Implemented locally — October 22, 2026.** Habitat now supports the agreed owner
journey with **mocked execution throughout**: saved goals and completion criteria,
scheduled occurrences, validation before submission, independent purchase review,
payment-gated continuation, versioned deliverable review and an AG Grid Audit
dashboard. Configuration, state changes and owner decisions persist in SQLite.
Use **Demo controls → Advance to next scheduled run** to exercise the schedule;
there is no real background cron, model workflow or external payment execution.

Local verification passed **140 backend tests and five browser journeys**. The
[current demo script](../hackathon-demo-script.md) targets **2:50**; a new video
has not been recorded. See the [rehearsal status](../hackathon-demo-rehearsal.md)
for the current verification and historical recordings.

Updated 2026-10-22 for the owner's confirmed decisions and implementation. This plan
supersedes the delivery order and execution scope in the earlier
[workflow review](owner-workflow-review.md), including its concurrency assumptions.
The baseline below preserves the gaps that motivated this work; the change
packages record the implemented mock scope. Production execution remains deferred.

## Agreed workflow

The [simplified owner journey](../../../docs/diagrams/habitat-owner-journey-deliverables-overview-2026-10-21.png)
has three independently accessible areas:

1. **Set up and fund:** configure agent goals, deliverables and completion criteria;
   configure AICL controls; add PayPal funding.
2. **Review and enable:** review agents, choose an hourly or daily schedule, then
   enable scheduled work. Normal runs start at scheduled times, without a manual
   Start task step.
3. **Audit:** monitor costs and statistics in an AG Grid dashboard, inspect actions,
   review purchase requests from past runs, and view/review job deliverables.
   The owner can enter Audit at any time.

The agent checks configured completion criteria before submitting work. A failed
check leaves the work **Needs work**, with the failed criteria visible. Only
validated outputs become **Submitted for review**. The owner then chooses
**Accept** or **Request changes**. Requested revisions run on the next eligible
scheduled occurrence, preserving prior versions and review feedback.

After approving a purchase, the owner can choose **Run now** or **Resume on
schedule** (the default). That choice concerns the waiting work associated with
that purchase. Exact purchase approval remains separate from buyer checkout
consent. Continuation occurs only after the mock payment and resource delivery
succeed and current controls permit it.

## Pre-change implementation baseline — October 21, 2026

| Area | Existing foundation | Required change |
| --- | --- | --- |
| Configuration | Agent instructions and a saved product/audience/goal brief | One configuration for goals, expected deliverables and explicit completion criteria; snapshot it per run. |
| AICL and funding | Capabilities, connections, budgets, reservations, service-credit records and local mock checkout | Reuse controls and remembered buyer; show setup readiness and the reason work is blocked. |
| Execution | Manually started task, fixed launch-kit output, mandatory purchase | Mock scheduled runs with optional purchase dependencies and pre-submission validation. |
| Scheduling | Lifecycle activation exists; schedules do not | Save hourly/daily settings, next run and enable/pause state; simulate due occurrences deterministically. |
| Purchase review | Exact approve/decline, checkout, pending-payment recovery and receipts inside task cards | Independent inbox spanning past runs, stable request links, and a continuation choice. |
| Deliverables | Completed text is stored inside task/history cards | Dedicated output list/detail, criteria results, owner review, revision feedback and versions. |
| Audit | Usage, balances, receipts and append-only events exist in separate sections | AG Grid dashboard for cost/statistics monitoring, readable activity and links to requests/results. |
| Agent list | Names, lifecycle and gate reasons | Goal, schedule, next run, pending requests, latest output and a useful next action. |

### Constraints identified before this iteration

- `start_run` always requests a fresh fixed-price template purchase. A timer around
  that function would reproduce the wrong flow. Mock scenarios must also support
  useful work without a purchase and reuse of an already delivered resource.
- Missing brief inputs fall back to an example. Every simulated run must load the
  saved configuration and retain its version; hidden browser fields must not be
  the source of scheduled job inputs.
- The current service rejects any new run while one is unfinished. The mock model
  must distinguish a purchase-dependent waiting job from other eligible work,
  so requests from past runs can remain pending independently. Repeated ticks
  must never duplicate a waiting request. Production concurrency is deferred.
- Quote expiry currently sends the owner back to starting a new run. Independent
  Audit needs an expired state and refreshed proposal with fresh exact approval.
- Current result history is tied to a limited run projection. Deliverable and
  purchase lists need their own access to historical records.

## Mock scope and behavior

Keep the current server-rendered app, SQLite, a bounded set of reviewed job
examples, and the local mock payment API. Mock outputs should reflect saved goals
and deliverable requirements through deterministic scenarios. Free-form goals
must not imply that arbitrary real agent programs are being executed.

Persist configuration, schedules, run states, purchase decisions, deliverable
versions and review feedback so navigating away or reloading does not reset the
journey. Use scenario fixtures for inference, checks, delivery and costs. Their
results must be identifiable as demo data; no claim of actual model validation or
real payment. Keep the existing brief final-step demo disclosure unobtrusive.

Use a controllable demo clock/advance mechanism to exercise scheduled occurrences
without waiting an hour. This is a demo control, separate from the normal product
workflow. Enabling a schedule shows its next occurrence; advancing the clock to
that time creates eligible work. Do not add a general manual Start task button.

Simulate pause, budget exhaustion, insufficient credit and blocked dependencies.
Record why a run did not proceed. Preserve existing owner checks, payment
idempotency, reservations and accounting behavior when reusing those services.
Mock execution does not justify weakening existing safeguards.

Real cron infrastructure, background authorization, production job concurrency,
real inference/validation, PayPal Sandbox/live integrations and cloud deployment
are follow-on work. They are not prerequisites for this demo.

## Implemented mock workflow packages

### 1. Save goals, deliverables and completion criteria once

Unify agent setup and the existing task brief. Each deliverable specification
contains its name/type, expected content and explicit completion criteria. For
example, a launch-copy deliverable might require a headline, audience-specific
benefit and call to action. The owner configures the desired work; it is not a
hard-coded product feature named “Prepare a marketing launch kit.”

Store a configuration version. Each simulated run snapshots the goal, inputs,
deliverables and criteria it uses. Later configuration edits apply to future work
without rewriting old results, review records or receipts. Revisions retain their
original criteria and owner feedback unless the owner explicitly changes scope.

Reuse AICL and funding forms. Keep entered data when returning from checkout, and
use the remembered buyer rather than asking for the same information twice.

**Acceptance:** configure once, reload, review setup and see the same values;
subsequent runs use the saved configuration; old outputs retain their original
requirements after an edit.

### 2. Model scheduled work and validation with deterministic fixtures

Add saved hourly/daily schedule settings, timezone, next occurrence and
Enable/Pause. A simulated due occurrence creates a run from its configuration
snapshot. Give each occurrence a stable identity so repeated clock advances or
page refreshes cannot duplicate work or mock costs.

Model these paths:

- Work requiring no purchase produces candidate outputs and validates them.
- Work needing a resource creates one purchase request and waits on that request.
- Failed validation keeps the candidate as Needs work with criterion-level
  reasons; a later eligible tick can simulate a corrected version.
- Passing all required criteria submits a version to the deliverables review list.
- Request changes queues a revision for the next eligible scheduled occurrence.

A purchase blocks only its dependent work. Other eligible mocked work can proceed;
there is no need to build a real parallel worker system. Keep outstanding requests
linked to the originating run, and do not recreate them on later ticks. Reuse
already delivered resources where appropriate to the scenario.

Prioritize an eligible continuation or requested revision over creating fresh
work for the same job. While a version awaits review, do not generate duplicate
copies of that same deliverable. Other distinct scheduled work remains eligible.
Use bounded correction scenarios, with visible simulated usage, rather than an
unlimited automatic validation/retry loop.

**Acceptance:** an enabled agent runs only when its simulated schedule is due;
pause and budget/credit limits block it; duplicate ticks do not duplicate work;
a failed criterion prevents submission; a successful output is reviewable.

### 3. Build the independent purchase inbox and continuation choice

Audit's Purchase requests list includes all approval-ready requests from past
runs, with agent, originating job, item, amount, reason and status. Filtering or
pausing an agent must not erase history. Declined, expired, paid and unresolved
requests remain discoverable through status filters.

Reuse exact approve/decline and mock checkout. On approval, offer:

- **Resume on schedule:** after payment and delivery succeed, continue the waiting
  job at its next eligible scheduled occurrence.
- **Run now:** after payment and delivery succeed, continue that job immediately
  if the agent is enabled and its current controls allow it.

The choice can be presented during approval, but is a stored preference until
checkout and fulfillment complete. Pending, unknown, cancelled or failed payment
must not start work. A blocked continuation shows a reason and an explicit next
action. Choosing Run now does not unpause an agent, bypass a budget, create a new
job, or change its recurring schedule. If a job has more than one dependency, all
required resources must be available before continuation.

This is a one-time choice for the waiting job. Show the expected continuation
time and update it when the schedule changes. Re-enabling resumes from the next
eligible occurrence without replaying accumulated missed work.

Continuation claims the waiting job once, including when payment recovery and a
scheduled tick arrive together. Resume on schedule continues that existing job;
it does not rerun its completed planning or buy the same resource again.

Decline releases the applicable purchase hold and records the decision while
preserving already incurred usage. Expiry offers Refresh proposal, retaining the
old quote and requiring new approval. Pending-payment recovery retains its order
identity. Keep service funding separate from purchase payments.

**Acceptance:** find two requests from different past runs without starting work;
approve one and decline another; exercise both continuation choices; prove a
pending/cancelled checkout cannot resume work and repeated callbacks cannot
resume it twice.

### 4. Make Audit and deliverable review first-class destinations

Add independent navigation to Audit, with **Dashboard**, **Actions**,
**Purchase requests** and **Deliverables**. The dashboard uses **AG Grid** for
cost and statistics tables, with summary totals and agent/date/status filters.
Include simulated inference usage, service-credit consumption, merchant spending,
reserved amounts, run outcomes and deliverable counts. Keep funding top-ups,
usage, holds and purchase spending distinct so totals do not double-count money.
Aggregate existing records and mock events rather than introducing a second ledger.
Grid navigation, sorting and filtering are read-only. Row actions use the existing
authenticated services and refresh from server state, preserving filter context.

Actions use readable descriptions and links to the affected run, request, payment
or deliverable. Lists support historical access beyond the current latest-runs
projection. Reading Audit must cause no execution or charges.

Deliverables are the clear output of work, with a dedicated list and detail view.
Show the actual content prominently, alongside goal, agent/job, version, criteria
results, submission time and owner-review status. Purchased input templates are
resources, not the job's completed deliverables.

Use **Submitted for review → Accepted** or **Changes requested**. Request changes
captures feedback and schedules a revision; the next submitted version preserves
all earlier versions and decisions. Feedback and review decisions bind to a
specific version, so an old Accept action cannot accept newer work accidentally.
Needs work is an internal validation state, visible for diagnosis but outside the
submitted-for-review queue. Safe text previews are sufficient for this iteration.

Workspace cards link to relevant Audit filters and show schedule/next run,
waiting or blocked reason, pending requests and latest deliverable. Owner review
and purchase approval must be independent actions; neither is a mandatory next
screen after every run.

**Acceptance:** open Audit directly; filter AG Grid costs/stats; inspect a prior
request and output; accept a version; request changes on another and see its
scheduled revision with retained history. Existing owner isolation still holds.

### 5. Verify the mock journey and rebuild the demo

Use focused tests for actual state transitions: configuration snapshots,
due-occurrence deduplication, criteria gating, version-specific review, request
continuation, owner isolation and existing accounting/recovery invariants. Do not
add real scheduler or provider integration tests to this iteration.

Run a browser journey covering:

1. Configure a goal, deliverables, criteria and controls; fund through mock PayPal.
2. Review the agent, enable its schedule and show the next occurrence.
3. Advance demo time; inspect a validated deliverable and a Needs work example.
4. Open Audit independently and find requests from previous runs.
5. Approve and complete mock checkout; demonstrate Run now and Resume on schedule.
6. Decline another request; show the retained decision and correct hold release.
7. Review outputs: Accept one; Request changes on another; show its next scheduled
   revision and version history.
8. Inspect AG Grid costs/statistics and reload to verify persistent state.

Also cover expired quotes, pending-payment recovery and blocked continuation in
focused acceptance checks. The recorded pitch can omit these secondary branches
while retaining approval, denial and deliverable review at readable pacing.

Keep the demo under three minutes, with a useful deliverable, scheduled-work
context and an owner purchase decision in the first 30 seconds. Then follow the
setup → enable → independent Audit journey without starting in a contextless
checkout screen.

## Remaining recording and deferred production work

The mock application and acceptance checks are implemented locally. The remaining
demo deliverable is a new recording of the updated script. The October 21 video
documents the earlier manual-task workflow and does not demonstrate these changes.

Preserve current data and completed receipts during additive schema changes.
Introduce only the mock state needed for the chosen scenarios; do not replace
working controls or accounting merely to make fixtures easier.

Before future real execution, revisit durable schedule claims/restart handling,
background identity independent of browser sessions, current-period budget-gate
reevaluation, safe concurrent dependencies, external provider reconciliation and
real output validation. Existing budget gates deliberately survive period
rollover, and execution currently depends on an unexpired owner session. These
remain real implementation gaps; this mock workflow does not resolve them.

## Evidence and review scope

The October 22 implementation passed 140 backend tests and five browser journeys
against the local working tree. Focused coverage includes occurrence deduplication,
stale schedule controls, criteria gating, version-specific reviews, purchase
continuation, payment recovery, accounting and owner isolation. These are local
verification results, not a remote CI, commit, publication or deployment claim.

The historical baseline below was recorded during the October 21 code and UI
review in `e11-epic-completion`, branch `codex/paypal-mock-mvp`, based on commit
`68993e2` plus uncommitted PayPal/UI changes. Tests were read but not rerun during
that earlier planning review. Its source line numbers describe that earlier state.

| Historical baseline evidence | October 21 source references |
| --- | --- |
| Agent creation fields; separate task brief and fixed reviewed output | [Creation model](../../backend/aicl/creation/models.py) lines 26–35; [brief service](../../backend/aicl/commerce/service.py) lines 113–127, 337–352; [adapter](../../backend/aicl/commerce/adapters.py) lines 61–79 |
| Mandatory purchase and one unfinished job; explicit paid-job continuation | [Commerce execution](../../backend/aicl/commerce/service.py) lines 774–824; [existing guard tests](../../backend/tests/integration/test_workflow_journey.py) lines 55–74 |
| Missing scheduler; lifecycle-only activation; session-dependent execution | [Instance model](../../backend/aicl/control/instances.py) lines 57–71; [startup hooks](../../backend/aicl/hooks.py) lines 7–12; [lifecycle operation](../../backend/aicl/creation/operations.py) lines 210–217; [commerce ownership check](../../backend/aicl/commerce/service.py) lines 80–84 |
| Atomic budgets, UTC periods and rollover gate semantics | [Budget reservation](../../backend/aicl/control/budget.py) lines 164–242; [gate reevaluation](../../backend/aicl/creation/operations.py) lines 42–85; [gate tests](../../backend/tests/integration/test_gate_authority.py) lines 16–67 |
| Sparse workspace projection and missing Audit navigation | [Workspace model](../../backend/aicl/web/views.py) lines 42–55; [navigation/cards](../../backend/aicl/web/pages.py) lines 18–22, 43–49; [agent sections](../../backend/aicl/web/manage_pages.py) line 41 |
| Existing results and limited history projection | [Run schema](../../backend/aicl/migrations/0009_mock_commerce.sql) lines 8–15; [run/dashboard projection](../../backend/aicl/commerce/service.py) lines 287–334; [task/history rendering](../../backend/aicl/commerce/pages.py) lines 135–158 |
| Existing payment safeguards, quote expiry and recovery | [Commerce service](../../backend/aicl/commerce/service.py) lines 228–265, 430–487, 623–674, 728–740, 801; [payment and receipt UI](../../backend/aicl/commerce/pages.py) lines 91–110, 148–156, 208–223 |
| Raw event presentation; reusable owner-wide audit query | [Activity template](../../backend/aicl/web/manage_pages.py) lines 125–131; [audit store](../../backend/aicl/control/audit.py) lines 35–40, 84–117 |
| Local payment transport scope | [Mock MVP guide](../mock-paypal-mvp.md); [payment tests](../../backend/tests/integration/test_payment_workflow.py); [remembered-buyer tests](../../backend/tests/integration/test_payment_buyer.py) |

