# Habitat owner workflow review

The current [owner workflow change plan](owner-workflow-change-plan.md) maps the
simplified three-lane diagram, including goals and deliverables, to fresh code
evidence and an ordered MVP backlog. It supersedes this earlier review's delivery
order and execution scope, and records the agreed mock-only behavior for
validation, scheduled work, purchase continuation and deliverable review.

The target design has two connected, independently entered workflows: scheduled
agent work and owner Audit. An owner sets a goal, controls and funding, then
enables a schedule. The agent works at that frequency while eligible. The owner
can open Audit at any time to inspect activity and spending or handle requests.
Audit is not a mandatory stage after every run.

[Scheduled work and Audit diagram](../../../docs/diagrams/habitat-scheduled-work-and-audit-2026-10-21.png)

The current local MVP supports manually started tasks and explicit continuation
after payment. It does not implement recurring execution or an independent Audit
inbox. Scheduling is a core gap for this target, even though the existing manual
path can still demonstrate the controls and purchase behavior.

## Target workflows

### Set up and enable scheduled work

1. **Define the agent's goal.** Save its purpose and task inputs once, then set
   AICL permissions, resource limits and purchase allowance.
2. **Fund inference with PayPal.** Carry the amount and agent into checkout.
   Remember the chosen account while requiring consent for every payment.
   Service credit funds inference; purchase allowance is a separate policy limit.
3. **Review and enable a schedule.** Persist the frequency, timezone and next run.
   Enabling or running the agent establishes its hourly or daily schedule.
4. **Dispatch eligible work when due.** Recheck lifecycle, permissions, current
   limits, service credit and reservations on every dispatch. Continue at the
   configured frequency while controls permit. If budget or credit is unavailable,
   show a blocked or exhausted state and its reason, with no billable dispatch.
   A daily/monthly policy budget may regain availability at its applicable period
   reset or after the owner changes its cap; insufficient service credit requires
   funding. Every later due tick still rechecks all controls. Pause prevents new
   work without erasing history.
5. **Publish outcomes and requests.** Runs append activity and usage to Audit.
   A run that needs a purchase enqueues its exact proposal and waits for the owner.
   Only the work dependent on that purchase waits; other eligible work may continue
   under the target policy. No run can approve its own purchase.

### Open Audit independently

The owner enters Audit from the workspace whenever they want. They can inspect
activities, results, receipts and spending, or open a pending request. A purchase
request is one possible Audit item; it is not required for every run.

For a purchase, review the item, seller, license, recipient and total before
approving or declining. Approval precedes any purchase execution and opens buyer
checkout, which still requires payment consent. A pending payment retains the
same order and hold. Completed payment records the receipt and delivery; it never
automatically resumes the dependent task. The owner explicitly continues that
task, and its controls are checked again.

Declining stops the dependent attempt, releases its purchase hold and preserves
prior inference charges. Audit keeps that decision and the later outcomes visible.
The owner may adjust controls, resolve a blocked schedule or pause the agent
without having to follow a fixed run → approval → audit sequence.

## Gaps and implementation priorities

### G1 Guided setup and goal clarity

**P1.** Creation asks for general instructions, then the agent
page separately asks for a launch-kit brief. A checklist points to controls spread
through a long page. The supported work remains one launch-kit scenario, so the
introduction should establish that scope before collecting inputs.

Create a persistent sequence of **Goal → AICL controls → Funding → Review and schedule** with
saved-state indicators and a clear next action. Distinguish the agent's enduring
purpose from the current task's product, audience and goal; avoid requesting the
same information twice. Explain PayPal funding and owner-approved purchases in
the introduction.

Evidence: [landing and creation templates](../../backend/aicl/web/pages.py)
(lines 31–35, 54–56), [setup checklist and task brief](../../backend/aicl/commerce/pages.py)
(lines 121–142), and [supported task adapter](../../backend/aicl/commerce/adapters.py)
(lines 16–23, 61–78). Saved briefs and readiness already have backend support.

### G2 Actionable agent list and readiness

**P1.** Workspace cards show lifecycle and control gates, but not task state,
funding readiness, outstanding purchase approval or the next action. The workspace
**Needs attention** count includes only gated instances; an active agent waiting
for an owner decision can be missed.

Add the goal, schedule state, next run, current work and readiness to each card.
Give Audit a direct entry with pending-request counts and links to the relevant
items. Show **Scheduled**, **Blocked or exhausted** and **Waiting for you** as
distinct conditions; a request waiting for approval need not stop unrelated work.

Evidence: [workspace rendering](../../backend/aicl/web/pages.py) (lines 43–49) and
[workspace projection](../../backend/aicl/web/views.py) (lines 42–55). The
[commerce dashboard projection](../../backend/aicl/commerce/service.py)
(lines 303–334) already provides current runs, readiness, attention counts and
balances for an individual agent; the combined workspace projection is missing.

### G3 Unified review and schedule enablement

**P1.** Activate is available for a draft even when its task is not ready. The
lifecycle transition changes state, while task start separately checks controls.
This protects execution but leaves an owner with an active agent that cannot run.
The lifecycle **Resume** action and **Resume task with purchased template** also
have different effects.

Add a final review showing the saved goal, permissions, limits, service credit,
frequency, timezone and next run. Enabling should establish the persistent schedule
and clearly show whether work is eligible or blocked. Distinguish **Resume agent
schedule** from **Resume dependent task**. Preserve exact purchase approval,
buyer consent and explicit task continuation after payment.

Evidence: [lifecycle actions](../../backend/aicl/web/manage.py) (lines 51–54),
[lifecycle mutation](../../backend/aicl/creation/operations.py) (lines 210–217),
[task readiness](../../backend/aicl/commerce/service.py) (lines 151–223), and
[post-payment continuation](../../backend/aicl/commerce/pages.py) (line 156).

### G4 Independent Audit inbox and readable history

**P1 for the independent inbox; P2 for history presentation.** Receipts, task
history, spending summaries and activity exist, but are
separate sections. The audit list renders event codes, outcomes and actors without
the event reasons or details. Owners must reconstruct how a decision affected
spending and the task.

Make Audit an independently accessible inbox and history view. Runs append events
and enqueue exact purchase proposals; the owner may review them separately from
scheduled execution. Provide plain-language timelines linking decisions, payment,
delivery, usage and results. Keep service credit, merchant spending and held
allowance separate, and link a blocked schedule to the control needing resolution.

Decouple a pending purchase's dependent task from other eligible work. The current
runner blocks a second task whenever one active task is awaiting approval,
checkout, payment or Resume; it cannot yet implement this target policy. Preserve
the wait for explicit owner continuation of purchased-asset work, even if another
scheduled task runs in the meantime.

Evidence: [funding and receipt UI](../../backend/aicl/commerce/pages.py)
(lines 97–110), task history and costs in the same file (lines 135, 157), and
[activity rendering](../../backend/aicl/web/manage_pages.py) (lines 125–131).
The [dashboard projection](../../backend/aicl/commerce/service.py) (lines 303–334)
already returns ledger, receipts and runs for this presentation.
The [single-current-task guard](../../backend/aicl/commerce/service.py)
(lines 786–789) and [workflow test](../../backend/tests/integration/test_workflow_journey.py)
(lines 55–74) establish the current concurrency limitation.

### G5 Scheduling is absent and planned

**P1 and core to the target workflow.** The implementation has no
schedule configuration, next-run projection or recurring task dispatcher.
Execution is initiated through owner Start and Resume requests.

Implement persisted hourly/daily frequency, timezone, next-run time and enabled,
paused and blocked/exhausted state. Add durable dispatch and duplicate-run
protection. Every dispatch must check current lifecycle, permissions, budgets,
credit and reservations. A blocked or exhausted state prevents billable dispatch
and identifies the cause: a daily/monthly policy cap can regain availability at
its applicable reset or after an owner cap change, while insufficient service
credit requires a top-up. Each later due tick rechecks every control before work
can proceed. Schedule visibility must survive restart.

Define overlapping and missed-run behavior, and dependency-aware waiting for
purchase requests, without duplicate charges or automatic purchase approval.
Payment completion must not automatically resume the dependent task. Keep the
current **Start task** and explicit **Resume task** path described as manual until
the scheduler and these controls are implemented and verified.

Evidence: [instance model](../../backend/aicl/control/instances.py) (lines 57–71),
[task start and resume routes](../../backend/aicl/commerce/routes.py)
(lines 163–198), and [task execution service](../../backend/aicl/commerce/service.py)
(lines 774–824). A search of application code, migrations and application tests
found no schedule, cron or next-run implementation.

## Existing behavior to preserve

- Draft creation, persisted brief, capability controls, resource limits,
  purchase allowance and an all-blockers readiness checklist.
- PayPal account choice remembered across agents, without authorizing future
  charges. Funding pays Habitat for service credit; purchases pay the seller
  separately.
- Exact approval or decline, recovery of a pending payment on its original order,
  receipt and delivery, then explicit task Resume.
- Declined attempts and their planning usage remain in history. A fresh task
  requires a fresh purchase approval. Pause blocks further work and retains history.

## Review evidence and scope

Reviewed on 2026-10-21 through application code and existing tests; tests were not
rerun for this review. The workspace and recorded demo agent were also inspected
read-only in the browser. No application behavior was changed.

[Owner journey tests](../../backend/tests/integration/test_owner_journey_pages.py)
(lines 131–215) cover saved task inputs, approval, pending checkout, completed
payment, explicit Resume and decline/retry history.
[Workflow tests](../../backend/tests/integration/test_workflow_journey.py)
(lines 55–119) cover one current task and readiness checks.

These observations concern the local MVP. The commerce routes are enabled only
for development/test, and the current payment, merchant and inference adapters
implement the demo workflow. They do not establish live PayPal or model execution:
see [commerce routes](../../backend/aicl/commerce/routes.py) (lines 1, 34–36) and
[adapters](../../backend/aicl/commerce/adapters.py) (lines 1–4).
