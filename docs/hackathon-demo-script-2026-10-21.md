# Habitat demo — a funded agent, with the owner in control

Updated October 21, 2026. This cut follows one chronological owner journey in
**2:49.08**: define a task, set boundaries, fund inference through PayPal, decline
a purchase, approve a fresh proposal, complete its checkout, inspect the delivery,
resume the task, and pause the agent. The funding checkout appears at **0:23.40**,
within the first 30 seconds. Declining and its accounting outcome receive
**20.52 seconds** together.

Habitat lets owners define an agent's purpose and capabilities, set resource and
purchase limits, and approve individual purchases. The launch kit is the supported
task in this MVP; the owner customizes its product, audience and goal. This is not
an arbitrary-task runner. PayPal has two distinct roles: a top-up pays Habitat for
service credit, while a separately approved purchase pays the merchant. Remembering
a buyer account does not authorize future charges.

The app controls, receipts and balances are persisted locally. The payment API,
merchant delivery and inference in this demonstration use local adapters; there
are no live PayPal or model calls. The checkout retains its small
“Demo checkout — no real charges” note. The closing narration explains the scope.
See the [implementation guide](mock-paypal-mvp.md).

## Video, script and editable captions

- [Watch the chaptered player](../../demo-recordings/habitat-paypal-journey-2026-10-21/index.html)
- [Download the new MP4](../../demo-recordings/habitat-paypal-journey-2026-10-21/habitat-paypal-journey.mp4)
- [Read every spoken line and bottom caption](../../demo-recordings/habitat-paypal-journey-2026-10-21/narration.txt)
- [Edit the scene plan](../../demo-recordings/habitat-paypal-journey-2026-10-21/plan.json)
- [Bottom caption subtitles](../../demo-recordings/habitat-paypal-journey-2026-10-21/captions.srt)
- [Spoken subtitles](../../demo-recordings/habitat-paypal-journey-2026-10-21/spoken-subtitles.srt)
- [Exact timeline and image-to-scene mapping](../../demo-recordings/habitat-paypal-journey-2026-10-21/timeline.json)
- [Capture coverage and limitations](../../demo-recordings/habitat-paypal-journey-2026-10-21/coverage.md)

The video is an **edited walkthrough assembled from actual browser captures** of
the app, rather than an uninterrupted screen recording. Each capture preserves the
real UI and account values; the edit controls readability and pace. Bella's existing
ElevenLabs narration was recut at complete-sentence boundaries at its original
speed. No new narration request or API credit was needed. The updated captions
explain the saved brief and remembered buyer workflow, which postdate that audio.
The earlier videos remain unchanged in their original folders.

The scene schedule below matches the exported 169.08-second video. Full decode,
visual review and browser playback/seek checks passed. See the artifact's
[export QA](../../demo-recordings/habitat-paypal-journey-2026-10-21/export-qa.json)
and [review notes](../../demo-recordings/habitat-paypal-journey-2026-10-21/qa-review.md)
for the evidence and its limits.

## Exact scene schedule

| Time | Scene | Bottom caption |
| --- | --- | --- |
| 0:00.00–0:10.00 | Give the agent a clear job | Create your agent, then save the product, audience and goal for its launch-kit task. |
| 0:10.00–0:20.32 | Set the boundaries before work begins | Daily and monthly resource caps bound usage. A separate $2 purchase limit still requires approval for each proposal. |
| 0:20.32–0:28.52 | Fund the agent through PayPal | Add $5 of service credit for inference. The amount and Habitat recipient carry into checkout. |
| 0:28.52–0:37.72 | Confirmed funding makes the task ready | Complete checkout, return to this agent, and confirm its $5 service credit and setup readiness. |
| 0:37.72–0:48.72 | Start the task and inspect its purchase request | The saved brief starts the task. Review the $1 template, seller, license and recipient before deciding. |
| 0:48.72–0:58.72 | Say no: the task stops | Decline purchase. This task stops without paying the seller or delivering an asset. |
| 0:58.72–1:09.24 | Declining releases the reserved allowance | $0 merchant spend · $0 held · $2 allowance available. The completed $0.002 planning step remains charged. |
| 1:09.24–1:19.76 | A new attempt needs its own exact approval | Review the new proposal. Approve and continue to PayPal opens its prepared checkout directly. |
| 1:19.76–1:29.76 | Your PayPal choice carries forward | The remembered account and order details are already filled in. Each payment still needs your consent. |
| 1:29.76–1:43.76 | Pending payment keeps the task waiting | No delivery or merchant spending yet. The $1 order remains reserved, leaving $1 of purchase allowance available. |
| 1:43.76–1:50.56 | Complete the same approved order | Return to the pending checkout and complete the $1 payment. Do not create a replacement order. |
| 1:50.56–2:01.56 | Keep the seller receipt with the delivery | The saved receipt identifies the $1 merchant payment separately from the $5 service-credit top-up. |
| 2:01.56–2:14.08 | Inspect the template, then choose to continue | Payment never restarts the agent automatically. Resume rechecks lifecycle, permissions, budgets and credit. |
| 2:14.08–2:23.08 | The saved brief becomes a concrete launch kit | Review the result for your product, audience and goal, with the purchased template as its source. |
| 2:23.08–2:32.08 | See where the money went | $4.994 service credit · $1 merchant spend · $1 purchase allowance · $0 held. Three inference steps used $0.006. |
| 2:32.08–2:42.08 | Pause whenever you need to stop new work | Pause blocks another task while preserving this result, its receipts and the usage history. |
| 2:42.08–2:49.08 | Habitat — funded work, owner-approved purchases | A clear task. Bounded resources. Remembered PayPal details. Exact consent. Recorded outcomes. |

## Operator rehearsal

Start the existing local app and its payment API using the current local demo
launcher described in the implementation guide. Sign in before recording. Use a
fresh agent so the balances and attempt count below remain reproducible; do not
reuse or reset an owner's existing agent. The app used for this take is
`http://127.0.0.1:4173`. Recording begins after sign-in, so it is not an
authentication demonstration.

1. **Create the agent.** Choose a meaningful launch-assistant name, owner
   instructions and inference capability. Continue from the creation receipt to
   **Set up your first task**. The product feature is controlled agent execution;
   the marketing task is the example being configured.
2. **Save the brief.** Fill **Product or service**, **Who is it for?**, and
   **What should this launch achieve?**, then **Save task brief**. Show the saved
   values. Saving the brief consumes no service credit and starts no work.
3. **Set boundaries.** Set inference daily/monthly limits to **1 / 10** and compute
   daily/monthly limits to **1 / 10**, then save. Enable **Enable purchases**, set
   **Total purchase limit (USD)** to **2**, and **Save purchase controls**. Activate
   the agent. The setup checklist should now identify only outstanding readiness
   conditions, including funding if it has not yet completed.
4. **Fund this agent.** In **Funding**, choose **Add $5.00 with PayPal**. Review
   the Habitat recipient and amount. For a new owner, choose the buyer account at
   the first checkout; for an existing owner, show the remembered choice. Do not
   invent a first-time selection when it was already saved. **Complete payment**
   returns to this agent's setup. Confirm **$5.00** service credit and readiness;
   show the saved top-up receipt without creating another order.
5. **Start and inspect.** Choose **Start launch-kit task**. The saved brief carries
   forward. Show the **$1.00** template, seller, license and asset recipient. The
   planning step costs **$0.002**; starting does not approve the purchase.
6. **Decline visibly.** Choose **Decline purchase**. Hold on the stopped-task
   message long enough to read it. Open Funding and show **$4.998** service credit,
   **$0** merchant spending, **$2** available allowance and **$0** held. The
   declined purchase cannot proceed; previously incurred planning usage remains.
7. **Start a fresh attempt.** Use **Start a fresh task**, retain the saved brief,
   and **Start launch-kit task** again. Review its new exact proposal. Choose
   **Approve and continue to PayPal**: the prepared checkout opens directly.
   Earlier refusal or approval does not authorize this new proposal.
8. **Show remembered details.** Hold on the account choice, seller and **$1**
   total. The owner does not re-enter the task, amount, recipient or saved buyer
   choice. **Change account** remains available, but changing it is outside this
   short walkthrough. Payment still requires this order's buyer consent.
9. **Demonstrate pending.** Expand **Payment options** and choose **Mark as
   pending**. Return to the task and show the pending state without delivery or
   Resume. Funding should show **$4.996** service credit, **$0** merchant spending,
   **$1** allowance available and **$1** held. Return through **Resolve pending
   checkout**. A status check observes the same order; it does not create a new
   payment or itself guarantee settlement.
10. **Complete the same checkout.** Review the pending order and choose
    **Complete payment**. The app returns to the task with its saved receipt and
    delivered template. Expand **Payment receipt**, then **View delivered
    template**. Payment alone must not resume inference.
11. **Resume deliberately.** Choose **Resume task with purchased template**.
    Habitat rechecks lifecycle, inference permission, resource limits and service
    credit. Review **Your marketing launch kit**, showing the chosen product,
    audience, goal and purchased source.
12. **Inspect the accounting.** Funding should now show **$4.994** service credit,
    **$1** merchant purchases, **$1** purchase allowance available and **$0** held.
    Two planning attempts and one final step cost **$0.006** in total. Merchant
    payment is separate from service credit. Retain the first declined attempt
    under task history and the completed funding/purchase receipts.
13. **Pause and finish.** Choose **Pause**, then show setup/readiness blocking a
    fresh task while the output, receipts and history remain. This is a lifecycle
    blocker; do not describe it as an actual zero-budget request denial.

The fresh final-take agent is
`7d487563-8d4f-4824-b5bd-2d75acfbdc33`. Its expected closing state is paused,
with the balances in step 12. Rehearsals that add attempts will have different
inference balances; never reuse the numerical narration against mismatched UI.

## What this cut establishes

The browser journey demonstrates a saved customized brief; resource and purchase
boundaries; service funding; remembered buyer details; explicit refusal and
released allowance; a fresh exact approval; direct checkout; pending payment and
held allowance; completion of that same order; receipt and asset delivery;
explicit resume; personalized task output; separated accounting; and pausing.

The cut does **not** perform an actual zero-budget work request, cancel a payment,
change buyer accounts, create a second agent to prove cross-agent account reuse,
or wait for quote expiry. It also does not establish concurrency, repeated-POST
idempotency, restart recovery, cross-owner access controls, webhook verification,
refunds, disputes, live payments or real inference. A visible pending state and
retained receipt alone do not prove those properties. Existing tests and older
recordings remain separately scoped evidence; no new test-suite or CI pass is
claimed by this recording.

The [PayPal implementation backlog](paypal-mvp-backlog.md),
[funding contracts](design/paypal-funding/technical.md), and
[purchase contracts](design/agent-purchases/technical.md) describe remaining
provider integration work. Keep this local demonstration distinct from PayPal
Sandbox or production execution.
