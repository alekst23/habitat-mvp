# Habitat PayPal demo readiness and usability findings

The active submission is the PayPal AI Hackathon. The current app implements the
mocked owner workflow in the [change plan](design/owner-workflow-change-plan.md):
configure goals and deliverables, enable scheduled work, then independently
review purchases and outputs in Audit. The earlier development-workflow
presentation is retired.

## Fresh scheduled-workflow walkthrough — October 22, 2026

**Browser walkthrough and captions-only export verification complete.**
The [new video](../../demo-recordings/habitat-scheduled-workflow-2026-10-22/habitat-scheduled-workflow-captions-only.mp4) runs **2:48 (168.00 seconds)**, with a Habitat logo and
workflow-diagram intro and PayPal funding by 0:22. The media is an edited walkthrough
of fresh actual browser captures, not a continuous screen recording. The current
default is captions only, with no audio. The previous local-voice draft is retained
as an optional archive.

The dedicated recording agent **Garden Pilot Assistant**,
`bcfe7b60-967d-4c96-98a1-ae95012e6e5e`, has three configured outputs:
**Invitation copy**, **Pilot launch checklist**, and **Outreach resource brief**.
The walkthrough funded **$5** of service credit and set a separate **$3 purchase
allowance**, then exercised scheduled occurrences through the demo clock.

| Review step | Observed result |
| --- | --- |
| Inspect a purchase's work context | Purchase identifies the supported deliverable and links its saved goal, criteria and occurrence through the source job. |
| Decline the outreach resource | One request was declined; its decision remains in history. |
| Approve the checklist resource | One **$1** resource was paid and delivered, with continuation on schedule. |
| Review the checklist | **Version 1 accepted** after inspecting its output and completion checks. |
| Revise the invitation | Feedback requested a shorter invitation and one clear next step; **version 2** retains the earlier output and review history. |
| Monitor costs | AG Grid showed **$4.986 service credit**, **$0.014 inference usage**, **$1 merchant spending**, and **five jobs**. |
| Stop future work | Schedule left **paused**; existing decisions and outputs remain available. |

The current export preserves the **168-second, 1920×1080 H.264** visual edit
assembled from **25 actual browser captures** and removes audio. The **5,546,916-byte**
file contains no audio stream; its video was copied without re-encoding. Full
decode passed. CUA playback used the captions-only source, reported `readyState=4`,
duration 168 and no media error, and played successfully. The
[local review player](http://127.0.0.1:8851/) was left paused at the intro.

The prior narrated draft passed full decode and browser playback: `readyState=4`,
no media error, duration 168, advancing playback time, and successful seeking to
the decline scene at 67 seconds. Those earlier checks remain historical media
evidence and do not verify the new audio-free export.

Captures, current [bottom text](../../demo-recordings/habitat-scheduled-workflow-2026-10-22/bottom-text.txt), and the editing plan are in the
[new demo directory](../../demo-recordings/habitat-scheduled-workflow-2026-10-22/script.md).
Execution, completion checks, merchant responses and payments remain local scenario
fixtures. These observations do not claim production scheduling, real PayPal
charges or real inference. Existing agents were preserved.

## Mock owner workflow verification — October 22, 2026

**Outcome:** local verification passed **142 backend tests and five browser
journeys**. The application now supports saved completion criteria, validation
before submission, hourly/daily schedule settings, an independent purchase inbox,
payment-gated **Run now / Resume on schedule**, **Accept / Request changes** with
version history, and AG Grid cost/statistics monitoring. Existing owner isolation,
payment recovery, reservations and accounting remain covered.

Scheduled occurrences are mocked. Open **Demo controls** on the agent's
**Goals & schedule** page and select **Advance to next scheduled run** to demonstrate
due work without waiting. This control advances the saved demo schedule; it does
not start a real cron worker, inference request or external purchase. Mock funding,
checkout consent, decisions, receipts and deliverable history persist across reloads.

The [updated script and bottom captions](hackathon-demo-script.md) now target
**2:48**. The fresh browser walkthrough above covers the current app; the new 168.00-second
captions-only export passed media QA. These results are local verification, not a
new remote CI or deployment claim.

## Historical recording — October 21, 2026

The [October 21 owner journey](../../demo-recordings/habitat-paypal-journey-2026-10-21/README.md)
is an edited 2:49 recording of the earlier workflow, with saved task customization,
remembered PayPal buyer, funding, decline, pending payment, delivery, explicit
resume and pause. It does not cover the new scheduled work or independent Audit
and deliverable-review flow. Its
[review evidence](../../demo-recordings/habitat-paypal-journey-2026-10-21/qa-review.md)
records the fresh browser run and media checks. Payments and inference use local
demo adapters. The October 19 findings below are retained as historical evidence.

## Usability fix verification — October 19, 2026

**Outcome:** the three rehearsal UI issues are fixed locally on
`codex/demo-script-rehearsal`, based on stable main `68993e2`. This is local
verification and independent code review, not a new remote CI or deployment claim.

- Known work results now refresh status, budgets, confirmations and activity
  together while keeping the result notice visible. A failed follow-up read
  preserves the known outcome and requires explicit review before another request.
- Draft, paused, archived, gated and capability-empty instances disable the test.
  Only enabled capabilities appear. Budget and connection guidance gives the next
  step; the simulator explicitly explains zero inference tokens and no real output
  or payments. Network tests now have a destination field.
- Manual recheck appears only for a persisted gate. Saving corrected limits clears
  it automatically. Uncertain-response recovery uses a button-styled activity link
  with an explicit reload, including when already at the same URL/anchor.

Verification: **73 backend tests passed; all four existing browser journeys
passed**, followed by a passing targeted rerun of the expanded E11-6 journey.
The final journey covers automatic denial/success refresh, no-enabled-capability
and paused states, duplicate suppression, failed state refresh, unknown/lost work
responses, dirty budget-form preservation, newly inserted confirmation handlers,
network destination denial, and desktop/375px layout. Unknown/lost response and
failed-refresh cases use HTTP interception; normal work, gate, confirmation and
network checks use the real local service with simulated provider/executor ports.
Independent implementation review found no must-fix issues. Backend authorization,
CSRF, owner/tenant derivation, reservations and version checks are unchanged.

The preview was restarted from the changed checkout on `http://127.0.0.1:4173`,
retaining its existing SQLite demo database. A fresh in-app browser walkthrough
created **PayPal Demo — Verified Controls**,
`7a89f4f5-809e-48b3-81b6-8e87aa22dc88`. It verified draft disabled state, zero-budget
denial with automatically gated summary, four limits saved at daily 1/monthly 10,
automatic success/usage refresh, and paused disabled state. No manual page refresh
was needed after known work outcomes. The success recorded October 20 at 01:29 UTC
(October 19 EDT): **one minute, 0.005000 USD simulated compute, zero inference,
0.995000 daily compute available**. The new agent was left paused; earlier agents
were preserved. This was not a timed video or a real payment/model run.

Screenshots and receipt: `.ctx/completion-evidence/demo-ui-fixes/`. The current
[demo script](hackathon-demo-script.md) removes manual refresh and paused-submit
workarounds. A human timed take is still needed. The remaining product work is the
[PayPal implementation backlog](paypal-mvp-backlog.md).

## Stable-main rehearsal — October 19, 2026

**Outcome:** the current control walkthrough completed in the browser. The PayPal
funding, purchase, fulfillment and real-model scenes could not be run because the
site has no such controls or adapters. This was a manual browser rehearsal with
screenshots, not an automated acceptance run or a timed final video.

Checkout: stable main `68993e286150c6eca2526b35ca6ea8aeb8c93253`, whose application
files are identical to `419e77b`. Used the existing signed-in local preview at
`http://127.0.0.1:4173`; did not restart it or claim a process-reported Git identity.
Sign-in was outside this run. The approximately 730px-wide in-app viewport required
scrolling and section jumps. Audit timestamps are UTC: the observed successful
work was October 20, 2026 at 00:37 UTC, October 19 locally in EDT.

Created **PayPal Demo — Control Rehearsal**, instance
`c9f2405a-de40-470c-a0dc-0df1fdf44e7a`, using the wizard with only `inference` enabled.
The saved instructions express the launch-kit goal and clearly identify this as
a simulated rehearsal. The existing Director of Marketing, Demo Helper and prior
Budget Control rehearsal agents were not changed.

| Script step | Observed behavior | Result |
| --- | --- | --- |
| Create agent and review controls | Wizard saved name/instructions and one capability; creation receipt linked to a draft with four zero limits | Passed |
| Activate before setting limits | Lifecycle became active; no work was automatically started | Passed |
| Run one minute with zero limits | `Result: budget_exhausted. work was denied`; no usage row. Summary remained visually active until navigation/refetch | Control passed; stale-summary friction |
| Save inference and compute limits, each daily 1/monthly 10 | Save refreshed the page; active status and full budget headroom appeared; no manual gate-clear step needed | Passed |
| Run one simulated minute | `Result: succeeded.` appeared, but budget rows still showed zero settled and Activity still said No usage yet | Work passed; stale-summary friction |
| Click the inline reload link | Automated pointer click left the result and stale rows unchanged. The link wrapped over two lines; its href matched the instance path | Reproduced interaction issue; cause not isolated |
| Press Enter on that link | Page refreshed; one row showed 1 minute, inference 0.000000 USD and compute 0.005000 USD. Daily compute available became 0.995000; monthly 9.995000 | Passed |
| Pause, then request another minute | Status became paused; request returned `instance_not_active`; prior usage and available limits were unchanged | Passed |
| Refresh and inspect Activity | Audit included both denials, lifecycle changes, limit change, reservation, dispatch and settlement. Exactly one successful usage row remained | Passed |
| Look for the PayPal journey | Workspace/agent navigation had no funding or purchase screen. Capability catalog had no purchase tool. Connections offered simulated Gmail and Reddit only | Blocked by missing product implementation |

Final state: **paused**, only inference enabled, inference daily/monthly limits
**1/10**, compute limits **1/10**, one simulated **0.005000 USD** compute charge,
zero inference usage, zero held amounts. No payments, model calls, messages,
external purchases or provider connections were performed.

Local screenshots are saved under `.ctx/completion-evidence/demo-rehearsal-main/`:

- `01-created.png` — creation receipt and draft state.
- `02-budget-denied.png` — zero-budget denial.
- `03-success-before-refresh.png` — inline success before dependent views refresh.
- `04-usage-and-audit.png` — persisted simulated usage and audit.
- `05-paused-refusal.png` — paused request refusal.
- `06-final-paused.png` — final paused agent and remaining budget headroom.

The local `receipt.json` captures the operation outcomes and final state. Its
automation elapsed time includes inspection and tool waits; it is not the
duration of a narrated demonstration.

### Issues recorded before the fixes

1. **Refresh dependent state after a result.** Current success/denial can disagree
   with the header, budget table and activity. Update them together while keeping
   the outcome visible and preserving unknown-result protections.
2. **Make readiness and simulator meaning clear.** Active does not mean ready;
   paused agents still display an enabled Run button. The request selector lists
   disabled capabilities. The selected `inference` action submits zero tokens and
   compute minutes, producing no model artifact. Give the presenter and owner a
   plain explanation of the actual operation and relevant blocking control.
3. **Simplify recovery.** Saving limits already clears a budget gate, while
   **Re-check and clear** remains visible when no gate needs it. Use an actionable
   denial message and show manual recheck only when relevant. Investigate the
   wrapped reload link; automated pointer failure alone does not establish a
   general human-click or browser-independent defect.
4. **Build the PayPal task journey.** Funds/allocation, exact purchase review,
   buyer checkout, separate seller receipts/delivery and a real agent task/output
   are missing, not usability fixes that narration can cover. See the
   [itemized backlog](paypal-mvp-backlog.md).

For that earlier build, the workaround was browser refresh after first showing each work result,
skip the redundant gate-clear button, paste prepared wizard text and use section
links. The 207-word, 2:50 script is ready for a human timed read-through. The final
PayPal sequence remains a target and cannot yet be recorded as working behavior.

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

The three control-UI priorities were resolved in the verification above. For the
payment journey, also require a top-up preview with seller,
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
