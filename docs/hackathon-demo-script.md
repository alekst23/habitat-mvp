# Habitat demo — scheduled work, reviewed outcomes

Updated October 22, 2026. **Target: 2:48.** The intro establishes the owner journey; PayPal funding appears at 0:22, inside the first 30 seconds. Fresh browser captures now cover this scheduled workflow and its independent Audit review. The current edition is captions only, with no narration. It preserves the 168-second visual edit: 1920×1080 H.264, using 25 browser captures. The captions-only export is verified: 168.00 seconds, 5,546,916 bytes, no audio stream, full decode and browser playback passed. The H.264 video was copied without re-encoding.

The editable [recording script](../../demo-recordings/habitat-scheduled-workflow-2026-10-22/script.md), [scene plan](../../demo-recordings/habitat-scheduled-workflow-2026-10-22/plan.json) and [bottom text](../../demo-recordings/habitat-scheduled-workflow-2026-10-22/bottom-text.txt) live with the new demo artifacts. The prior local-voice draft is retained separately as an optional archive.

[Watch the video](../../demo-recordings/habitat-scheduled-workflow-2026-10-22/habitat-scheduled-workflow-captions-only.mp4) · [Local review player](http://127.0.0.1:8851/)

## The story

The owner defines a community-garden goal, expected deliverables and completion criteria. They fund inference, enable a cadence, then review work independently in Audit. A purchase request explains which job and output require it. The owner declines one request, approves another, and completes its separate checkout. Paid work resumes on schedule. Outputs are checked before submission, accepted or revised, and retained with costs and history.

The garden project is the owner's example configuration, not a built-in product feature. Habitat's features are goal and criteria configuration, bounded scheduled work, separate purchase consent, deliverable review and cost monitoring. This MVP uses local deterministic execution, validation and payment scenarios; it does not call PayPal or an inference provider. Retain the small checkout note and final scope disclosure.

## Recording configuration

Use a new dedicated recording agent; preserve existing agents and their history. Name it **Garden Pilot Assistant**. Enable inference. Prepare the saved configuration and limits, but leave funding, schedule activation, decisions and reviews for the walkthrough.

- **Goal:** Help our community garden recruit volunteers for the spring planting day.
- **Context:** Neighbors who are new to gardening. Use friendly, practical language and invite them to take part.
- **Invitation copy:** A welcoming invitation with a clear next step. Criteria: identify the audience; describe a practical benefit; include a next action. No purchased resource; passing scenario.
- **Pilot launch checklist:** A practical checklist for organizing the first session. Criteria: include at least three actions; identify a coordinator; explain the next step. Requires a purchased resource; passing scenario.
- **Outreach resource brief:** A short plan for reaching nearby residents. Criteria: identify the audience; suggest an outreach channel; identify a success measure. Requires a purchased resource; passing scenario. Decline this request in the walkthrough.
- **Schedule:** Every hour, America/New_York.
- **Controls:** $1 daily and $10 monthly inference/compute limits; purchases enabled with a $3 cumulative allowance.
- **Funding:** $5 service credit. Each merchant resource quote is expected to be $1; verify the actual screen instead of assuming.
- **Revision feedback:** Make the invitation shorter and give neighbors one clear next step.

Record saved values rather than prolonged typing. Capture genuine UI states and actions. Do not imply the demo clock is a production background worker. If a quote expires during setup, refresh it and review the current quote before recording its decision. Keep the related source job visible so each purchase remains distinguishable.

## Intro diagram

Use the existing Habitat sprout logo and wordmark with three simple swimlanes: **Configure** (goals, deliverables and criteria; funding and limits), **Scheduled work** (hourly or daily jobs within controls), and **Audit** (purchase decisions, deliverable review, costs). Connect scheduled work to Audit records. Purchases are one possible result of a job, not a mandatory next step or direct continuation after every run. Do not add implementation infrastructure to this short owner-journey diagram.

## Script and bottom text

The bottom caption is the on-screen explanation for the captions-only video. The earlier voice script remains archived in `narration.txt` and is not part of this edition.

| Time | Screen/action | Bottom caption |
| --- | --- | --- |
| 0:00–0:10 | **01-intro · A home for useful agent work**<br>Habitat logo and simplified workflow diagram. Make Audit a separate review lane, connected to scheduled work; approval is not a required step after every run. | Configure the outcome → schedule funded work → review purchases, deliverables and costs. |
| 0:10–0:22 | **02-configure · Define what complete means**<br>Saved goal and context, then Invitation copy criteria. Briefly reveal the named checklist and outreach deliverables. Routine typing is prepared offscreen. | The owner defines the goal, deliverables and completion criteria. The garden project is one example. |
| 0:22–0:33 | **03-funding · Fund inference with PayPal**<br>Funding amount and $5 checkout with Habitat as recipient; authorize payment and show credited balance. Keep the final checkout disclosure visible. | PayPal funds service credit for inference. Purchase allowance is a separate spending control. |
| 0:33–0:43 | **04-schedule · Enable scheduled work**<br>Show hourly cadence and next occurrence, Enable schedule, then Demo controls → Advance to next scheduled run. Do not imply a real background cron is running. | Choose hourly or daily work. This walkthrough advances the demo clock to the next occurrence. |
| 0:43–0:54 | **05-audit · Review on your own schedule**<br>Audit Purchases showing both pending requests, the Deliverables badge with one ready output, and the compact tab/filter layout. | Audit gathers past purchase requests, completed outputs and costs. Other eligible work can continue. |
| 0:54–1:07 | **06-source-job · See the work behind a purchase**<br>Outreach resource brief purchase: hold Supports deliverable, saved scope and Why requested. Open View source job; show original requirements and linked requests. Return with Back to purchases. | Each request identifies its deliverable and source job, including the original goal, criteria and scheduled occurrence. |
| 1:07–1:21 | **07-decline · Decline a purchase**<br>Outreach request before decision, click Decline purchase, then hold on declined state. Keep the deliverable identity visible so this cannot be confused with the checklist approval. | Decline stops this purchase and releases its allowance. The decision and prior inference usage remain recorded. |
| 1:21–1:33 | **08-approve · Approve an exact purchase**<br>Checklist request with seller, $1 total and license. Show Resume on schedule selected next to Run now, then click Approve purchase. | Review the item, seller, license and total. Choose Resume on schedule, then approve this purchase. |
| 1:33–1:43 | **09-checkout · Remember details, require consent**<br>Prepared $1 merchant checkout with remembered buyer and source-job link. Complete payment and show paid/delivered result; preserve the small demo checkout note. | The saved PayPal buyer carries forward. Each merchant payment still needs the owner’s consent. |
| 1:43–1:53 | **10-continue · Continue the waiting job**<br>Paid purchase waiting for scheduled continuation. Advance the next demo occurrence, then follow View resulting deliverable or its Audit output card. | After payment and delivery, the waiting job continues at its next eligible scheduled occurrence. |
| 1:53–2:06 | **11-accept · Review the actual output**<br>Checklist content and completion criteria, then Accept deliverable and hold on Accepted. Keep version/source-job provenance visible. | Read the deliverable and its completion checks. Accept the exact version you reviewed. |
| 2:06–2:19 | **12-revise · Ask for a useful revision**<br>Invitation copy review. Enter Make the invitation shorter and give neighbors one clear next step. Click Request changes; hold on saved feedback, then advance next demo occurrence. | Give specific feedback. A revision is queued for the next scheduled occurrence, with history preserved. |
| 2:19–2:28 | **13-versions · Keep review history**<br>Version 2 with Proposed revision and its shorter invitation; show previous version link/history. | Version history preserves the original, feedback and revised output. Validation and owner acceptance are separate. |
| 2:28–2:39 | **14-costs · Understand the costs**<br>Costs & statistics summary for the recording agent, then AG Grid usage ledger. Demonstrate one sort or filter; use actual balances from recording, never hard-coded totals. | AG Grid makes usage and costs sortable and filterable. Service credit, merchant spending and holds stay distinct. |
| 2:39–2:48 | **15-close · Scheduled work. Reviewed outcomes.**<br>Pause schedule, hold paused state, then logo end-card if space allows. Keep a readable final demo-scope line. | Pause future work; preserve history. Demo MVP: local simulated execution, validation and payments. |

## Editing and evidence rules

- Keep captions and states readable at the established timing. Target 2:48; the exported video must remain below 3:00.
- Keep the diagram readable for at least eight seconds. Do not open on an unexplained purchase or a later result.
- The decline scene has 14 seconds: show the identified outreach request for at least five seconds and its recorded declined state for at least seven.
- Hold source-job requirements long enough to connect the resource to its work. Do not omit this screen to gain time.
- Approval, checkout and scheduled continuation are separate actions. Preserve that order.
- Allow at least four seconds on Accepted and five on saved revision feedback. Do not compress these outcomes into a flash.
- Keep output text legible; crop or scroll deliberately rather than shrinking a full-page screenshot. Use gentle transitions and avoid continuous decorative zooming.
- Captions must not cover the controls or statuses they describe. Verify the final artifact at ordinary playback size.
- Use actual final balances. Do not manufacture a zero hold or a particular inference total if additional scheduled jobs were created during the demo.
- Call the artifact an **edited walkthrough** if it is assembled from browser screenshots. Do not describe still-image edits as a continuous screen recording.

## Recording artifacts

- [plan.json](../../demo-recordings/habitat-scheduled-workflow-2026-10-22/plan.json): renderer input, with scene IDs, durations, captions, narration and capture instructions.
- [timeline.json](../../demo-recordings/habitat-scheduled-workflow-2026-10-22/timeline.json): planned timing mirror; replace or supplement with actual render timings after assembly.
- [bottom-text.txt](../../demo-recordings/habitat-scheduled-workflow-2026-10-22/bottom-text.txt): current on-screen captions, grouped by scene.
- [narration.txt](../../demo-recordings/habitat-scheduled-workflow-2026-10-22/narration.txt): optional archived voice script from the earlier draft.
- [captures.json](../../demo-recordings/habitat-scheduled-workflow-2026-10-22/captures.json): maps each scene to the actual browser captures from the recording pass.

## Earlier recording

The [October 21 script](hackathon-demo-script-2026-10-21.md) and its
[2:49 walkthrough](../../demo-recordings/habitat-paypal-journey-2026-10-21/index.html)
remain historical artifacts. They show the earlier manually started task flow and
do not demonstrate this scheduled workflow or the current source-job review.
