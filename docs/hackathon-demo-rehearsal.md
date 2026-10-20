# Habitat PayPal demo readiness and usability findings

The active submission is now the PayPal AI Hackathon. The earlier development-
workflow presentation is retired. The observations below still apply to Habitat's
owner controls, but they demonstrate only part of the new
[PayPal demo script](hackathon-demo-script.md).

## PayPal demo readiness

The current E11 MVP has no PayPal adapter, payment routes, payment persistence, or
sandbox transaction evidence. Work and creation chat are simulated. The old PayPal
feasibility spike is a design reference, not proof of an executed integration.

The first complete demonstration needs one real AI deliverable, an owner-approved
PayPal Sandbox top-up, a verified completed capture, an explicit agent allocation,
metered usage, and a separate owner-approved seller purchase whose delivered asset
is used by the agent. Include an unapproved-purchase refusal. The
[funding design](design/paypal-funding/spec.md) replaces the earlier per-job payment
proposal. Reuse the control foundation without claiming its current limits are
funded money; in-policy inference does not require payment approval for every call.

The [purchase design](design/agent-purchases/spec.md) is now core MVP scope. Missing
implementation includes trusted seller quotes, purchase policy/holds, exact owner
approval, buyer checkout for a distinct integrated Sandbox merchant, capture and
receipt recovery, and verified asset delivery. Purchase allowance is policy, not
prepaid inference credit. Neither an MCP connection alone nor the current fake
confirmation UI establishes this payment capability.

The existing three UI priorities remain useful, especially automatic status
updates. For the payment journey, also require a top-up preview with seller,
amount, currency, sandbox environment, and intended allocation; distinct buyer
approval and completed-capture states; and clear pending, cancelled, failed, and
unknown outcomes. Separate the funding receipt from individual usage records.

## Existing control rehearsal

Browser rehearsal completed October 19, 2026 against the local E11 UI candidate
`419e77b9ab89173a3ee0531facec1c618324c4c3` at `http://127.0.0.1:4173`.
The core budget-denial, recovery, and simulated-usage sequence works. The three
priorities below would make it easier to demonstrate and understand.

This is a manual rehearsal, not a new CI run or a complete usability study.
No application source was changed during this rehearsal. The companion script now
describes the PayPal target; unimplemented scenes are marked explicitly.

## What was exercised

Created **Demo Rehearsal — Budget Control**, instance
`2238ac2b-ef4b-450b-af5b-0791c7e6c678`, with only `inference` enabled.
The existing **Director of Marketing** instance was not modified.

| Step | Observed result |
| --- | --- |
| Create with zero budgets, then activate | Lifecycle became active. |
| Request one simulated compute minute | `budget_exhausted`; no successful usage record. |
| Without reloading, set all four limits: inference daily/monthly 1/10, compute daily/monthly 1/10 | Save succeeded; status became Active and the gate cleared. No separate clear action was needed. |
| Request one simulated compute minute again | `succeeded`; the result changed but other visible sections still showed old usage. |
| Activate the result's reload link with keyboard Enter | Compute settled 0.005000 USD; daily available 0.995000 USD; monthly available 9.995000 USD. Inference usage stayed zero. |
| Open Activity | One usage row: one minute, 0.005000 compute USD, 0.000000 inference USD. Audit included denial, limit change, reservation, dispatch, and settlement. |
| Lower compute daily limit to zero, save, request again, refresh | Request denied; persisted status Gated with reason `budget_exhausted`. The previous successful usage remained. |
| Restore compute daily limit to 1 and save | Status returned to Active automatically. Final limits are 1/10 for both categories; one successful usage row remains. |

Local screenshot evidence is under `.ctx/completion-evidence/demo-rehearsal/`:

- `01-denied-stale-status.png` — immediate denial result and the work form.
- `02-settled-usage.png` — refreshed usage and audit history after the successful request.
- `03-persisted-gate.png` — refreshed Gated status with zero compute daily limit.
- `04-recovered-control-room.png` — restored limits and Active status after the second denial.

These screenshots are local rehearsal artifacts, not new published CI evidence.

## Priorities before recording

| Priority | Confirmed friction | Proposed improvement | Acceptance check |
| --- | --- | --- | --- |
| 1 | Work changes only the inline result. Status, budgets, usage, and confirmations remain stale until refresh. A presenter can say “success” while the page still says “No usage yet.” | Refresh the affected sections after a settled result, keeping the result visible. If a full reload is used, preserve a short outcome notice. Retain special handling for uncertain outcomes. | Denied work visibly updates the gate; succeeded work visibly updates usage and available budget without a separate reload. An unknown outcome retains its hold and does not invite automatic resubmission. |
| 2 | Activate and Run appear before budget configuration. A new instance has zero budgets; the request selector lists all capabilities even when only one is enabled. “Active” can be mistaken for “ready.” | Add a compact readiness explanation beside Run: lifecycle, selected capability, relevant budgets, and required connection. Link to incomplete settings and label disabled capabilities. Keep deliberate denial testing available. | A new owner can identify why a request will be denied and reach the relevant control without reading the whole page. Readiness advice does not replace authoritative server checks. |
| 3 | `budget_exhausted` does not say what to change. Recovery copy implies a separate re-check click, and **Re-check and clear** remains visible after the gate has already cleared. | Use a plain-language denial message with a Budgets link; explain that saving limits rechecks the gate. Show manual re-check when it is relevant. | The zero-budget → positive-budget recovery has a clear next action, and the UI acknowledges automatic recovery without requesting an unnecessary step. |

Relevant implementation: `backend/aicl/web/manage_pages.py` renders the controls
and work-result handler; `backend/aicl/creation/operations.py` rechecks a gate after
saving limits. Any implementation work should preserve current authorization,
version checks, reservation semantics, and simulated-provider disclosure.

## Other presentation notes

**Inference versus compute:** the form offers `inference` but accepts only compute
minutes and submits zero model tokens. This is a valid control demonstration, but
the labels can imply generated model output. Add a short explanation of exactly
what the simulator measures, or make the simulated request inputs more explicit.
This rehearsal records simulated compute usage only.

**Navigation and density:** in the approximately 730-pixel-wide in-app viewport,
the control room requires substantial scrolling. Section links help. A wider
recording window and a concise readiness summary would make the main sequence
easier to follow. Connections and network controls remain visible for this
inference-only instance; they need no attention during the selected demo.

**Refresh-link observation:** automated pointer clicks on the wrapped reload link
did not navigate in this in-app browser. Keyboard Enter on the same link navigated
and showed the persisted state. The cause has not been isolated; this is not yet
classified as an application defect. Reproduce with ordinary pointer input at the
recording viewport before filing a click-target bug. Browser refresh is available
for rehearsal.

**Sign-in:** the current ignored local runner, `.ctx/ui-demo/serve.py`, provides a
local demo continuation and sign-in confirmation. It does not require delivered
email. The stock `python -m aicl.test_server` uses the captured-link procedure in
the README; this distinction matters when preparing judge reproduction steps.

**Correction to an initial hypothesis:** denial does not increment
`instance.version`. Saving budgets immediately after denial succeeded in the
browser, consistent with `backend/aicl/control/instances.py:set_gated`. There is
no confirmed stale-version/409 defect in this sequence.

## What can be recorded today

The budget-denial and recovery sequence is usable now with explicit refresh steps.
It can support the PayPal story once a real model-backed job and a working Sandbox
transaction are connected. It is not sufficient as the full PayPal submission demo.
A final take needs a fresh job, separate Sandbox funding and seller orders,
visible payment and delivery receipts, and a full
timed read-through after implementation.
