# Habitat PayPal demo script

Updated October 19, 2026. The submission focus is **Habitat for the PayPal AI
Hackathon**. The previous software-development-workflow presentation is retired.
Target recording length: **2 minutes 50 seconds**, with at most 330 spoken words.

**Demo promise:** PayPal funds the agent's inference, and the agent uses a
controlled PayPal purchasing tool to obtain a useful resource on the owner's
behalf. AICL enforces the owner's separate funding, inference, purchase, and
approval controls throughout one launch-kit task.

**Readiness: TARGET — not implemented.** The current MVP has working owner
controls and simulated work, but no PayPal integration, merchant purchasing tool,
or real AI execution. Every payment, purchase, and model scene below requires
implementation and verification before recording. The
[rehearsal notes](hackathon-demo-rehearsal.md) preserve the controls already tested.
The [funding specification](design/paypal-funding/spec.md),
[funding technical design](design/paypal-funding/technical.md), and
[agent purchase specification](design/agent-purchases/spec.md) define the proposed
contracts.

## Smallest recording scenario

Use one reviewed marketing agent and one deliverable: a launch kit for the owner's
app, consisting of a short plan, a purchased marketing template, and three draft
posts using that template. The template is an artifact we own or have permission
to distribute through one controlled **Demo Template Shop** Sandbox merchant.
That merchant has a different PayPal merchant identity from the Habitat merchant
that receives service-credit top-ups. Do not add arbitrary merchants, live
advertising, or message sending to this recording.

The owner buys **$5 USD of Habitat service credit** through PayPal Sandbox.
Habitat verifies a completed capture before recording credit; approval and a
return redirect alone add no funds. The owner explicitly allocates the credit to
the agent and sets applicable daily/monthly inference and compute limits. Each
model call reserves a bounded maximum, settles measured usage, and releases the
unused reservation. In-policy model calls need no additional PayPal checkout.
[PayPal Orders integration](https://developer.paypal.com/api/rest/integration/orders-api)

Separately, the owner enables purchasing from Demo Template Shop and sets a
**$2 purchase limit**. The agent proposes a template with a **$1 final total**,
including any applicable tax or other charges. These are controlled demo catalog
values, not claims about a real third-party product. The purchase limit is a
policy ceiling, not cash or a PayPal account balance. The owner reviews the exact
merchant, items, license/recipient, currency, and total in Habitat, then completes
buyer approval in PayPal Sandbox Checkout. The broker verifies the approved order
and uses the merchant adapter to capture it once. Only verified completed payment
allows delivery of the receipt and purchased artifact to the agent.

**These are two separate payment paths.** The top-up pays Habitat for service
credit. The purchase pays Demo Template Shop through the buyer's PayPal checkout;
it never spends or transfers Habitat inference credit. Ordinary Orders checkout
requires an integrated merchant and buyer approval. PayPal's `pay_order` tool
captures an authorized order; it does not grant arbitrary buyer-wallet authority.
[Orders flow](https://developer.paypal.com/api/rest/integration/orders-api),
[PayPal agent tools](https://developer.paypal.com/ai-tools/agent-tools/)

**Sandbox credit does not pay real model bills.** The operator pays the model
provider through an independently capped account. Record actual measured usage
and the resulting credit balance; never invent charges or provider output.

## Timed target script

All screen actions below are proposed behavior. Read the quoted narration only
after it works. Keep **PayPal Sandbox · test money** visible in payment scenes.
The quoted narration contains 251 words; allow the remaining time for interaction
and inspection. Verify timing with a full rehearsal.

### 0:00–0:15 — The owner problem

**Screen:** Habitat workspace and the reviewed marketing agent.

> An agent needs money to think and sometimes needs to buy something to finish a
> task. Habitat makes both visible and controlled. I'll use PayPal to fund this
> agent and approve one useful purchase.

### 0:15–0:45 — Fund and allocate inference credit

**Screen:** Add $5 through PayPal Sandbox Checkout. Show the verified completed
capture, then explicitly allocate the credit to the agent. Show applicable
inference/compute limits and the independent operator real-cost ceiling.

> First, I buy five dollars of Habitat service credit through PayPal Sandbox.
> Habitat verifies the completed payment, then I allocate that credit to my agent.
> This is test money; real inference uses a separately capped operator account.

### 0:45–1:05 — The agent proposes a purchase

**Screen:** Ask, “Prepare a launch kit for my app, using a suitable marketing
template.” Show an actual model-produced plan and the allowlisted merchant's
trusted $1 quote. Show the $2 purchase policy separately from service credit.

> The agent plans my launch kit and proposes a one-dollar marketing template from
> our demo merchant. Its purchase limit is separate from its inference credit.
> Finding a product does not authorize payment.

### 1:05–1:30 — Owner review and PayPal buyer approval

**Screen:** Review the exact seller, item, license/recipient, currency, and final
total. Approve in Habitat, then complete PayPal Sandbox buyer checkout. Both
approvals bind to this purchase; changed details require a new approval.

> I review the seller, template, and final total, then approve this specific
> purchase. PayPal lets me review and approve the payment. The merchant receives
> this payment directly; my Habitat service credit does not pay for it.

### 1:30–1:50 — Verify payment and deliver the resource

**Screen:** Broker verifies order identity, seller, contents, total, and approval;
merchant adapter captures once. Show completed capture, merchant receipt, and the
delivered template. Payment pending is never shown as paid or fulfilled.

> Habitat verifies the order and completed capture before delivering the template.
> Here are the merchant receipt and purchased file. Repeating the request cannot
> create another charge or spend the approval twice.

### 1:50–2:20 — Use the purchase and meter inference

**Screen:** Agent uses the delivered template to produce actual draft posts.
Show the saved launch kit, measured model usage, released reservation, remaining
service credit, and separate merchant purchase record.

> Now the agent uses that template to create my launch kit. Each model call
> reserves a bounded cost, settles measured usage, and releases unused credit.
> I can inspect the result, inference charges, and merchant purchase separately.

### 2:20–2:40 — Refuse an unapproved purchase

**Screen:** Request another allowed-catalog purchase without owner approval.
Show a readable approval-required response before payment dispatch. Other policy
checks pass so the demonstration proves the approval gate. A separate acceptance
test must also prove that changing an approved quote invalidates its approval.

> A second purchase has no approval, so Habitat stops before payment. The agent
> cannot approve itself. A changed price or different item also needs a fresh
> approval.

### 2:40–2:50 — Close on the product

**Screen:** Finished launch kit, both payment records, remaining credit, and the
blocked purchase.

> Habitat connects funded intelligence with controlled purchasing: useful work,
> clear receipts, and an owner who stays in charge.

## Implementation needed for this recording

| Work | Minimum completion evidence |
| --- | --- |
| Real AI task | Reviewed agent plans the launch kit, proposes the allowlisted template, consumes the delivered artifact, and saves actual model output with usage. Current scripted chat and fake work are insufficient. |
| PayPal funding | Owner-bound Sandbox Orders `CAPTURE` flow; verified amount, currency, Habitat merchant, and completed capture; one durable credit per capture. Approval or pending capture adds no credit. |
| Allocation and inference | Explicit allocation of existing credit, applicable daily/monthly limits, atomic bounded reservations, measured settlement at versioned prices, and release of unused credit. Sandbox funding cannot increase the operator real-cost ceiling. |
| Merchant purchase tool | One controlled seller identity distinct from Habitat's funding merchant, a trusted owned/licensed digital-product quote, and a server-side merchant adapter behind AICL. Agent context never receives payment credentials. |
| Purchase policy and approval | Separate purchase-spend policy; exact merchant, items, total, currency, license/recipient and expiry bound to owner approval; buyer Checkout approval bound to the corresponding order. Agent cannot widen policy or approve its own proposal. |
| Purchase execution and fulfillment | Broker verifies the order, captures through the merchant adapter, and delivers receipt plus artifact only after verified completed capture. Preserve stable operation identities and prevent duplicate charges and fulfillment. |
| Recovery | Verified/deduplicated webhooks, pending/unknown reconciliation, refund/reversal handling and restart readback for each payment path. Uncertain capture never starts a replacement payment. |
| Owner UI | Funding credit, agent allocation, inference limits, purchase policy, approval details, pending states, two payment records, delivered artifact, usage and remaining credit are clearly distinct and update immediately. |
| Full rehearsal | Actual Sandbox top-up and separate merchant capture, useful real-model output using the purchased asset, and an unapproved-purchase refusal before payment dispatch. Separately verify changed-quote denial and duplicate-safe execution. |

Reuse current authentication, owner controls, reservation/settlement concepts and
audit history. Payment and purchase operations need their own contracts; simulated
Gmail/Reddit approvals do not constitute payment support. MCP can carry the tools,
but the AICL policy checks and approval enforcement live in the trusted service.
Broader merchant discovery and delegated payment programs remain later work.

## Recording and submission constraints

The PayPal rules require a functional application with PayPal Sandbox integration
and an AI tool, model, or platform; PayPal must be central. A working local build
with complete setup instructions can satisfy demo access. Public hosting is not
mandatory. The repository needs an open source license, and the video should be
under three minutes and publicly visible on YouTube.
[Official rules, checked October 19, 2026](https://paypalaihackathon.devpost.com/rules)

Prepare fresh top-up and purchase orders for the take. Sign into the Sandbox buyer
in advance, verify both Sandbox merchant identities, and keep the catalog/template
license and price ready. Rehearse with a stopwatch; shorten introduction and
accounting narration if needed, preserving both real Sandbox checkout sequences,
owner approval, purchased artifact, useful model output, and denial evidence.
Keep the operator real-cost ceiling enabled throughout.

The existing control-only walkthrough is development evidence. It does not replace
the missing payment, purchase, and AI scenes. Final narration must match the final
implementation and the transaction states actually observed.
