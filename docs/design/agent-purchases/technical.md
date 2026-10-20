# AICL purchase broker technical design

Status: proposed, October 19, 2026. Implements the [purchase specification](spec.md)
alongside the [funded inference contracts](../paypal-funding/technical.md). This is
design work; no provider integration or transaction is claimed as completed.

## Services and hosts

Keep the first deployment on one Habitat application host with FastAPI modules,
server-rendered owner pages, the reviewed agent runner, and one persistent SQLite
database. The AICL layer contains the policy gate, approval service, inference
proxy, purchase broker, credential broker, audit, and payment reconciler. An MCP
facade, when needed, calls these services under the same scoped runner identity.

Add a controlled **Demo Template Shop** seller service with a distinct Sandbox
merchant account/app and one licensed digital item. It may run as a separately
configured local service for the demo; expose only catalog, quote, checkout, and
authenticated fulfillment operations to Habitat. Only that seller's server holds
its merchant secret and makes merchant order/capture calls. Habitat's funding
adapter retains its own separate merchant configuration. Shared PayPal HTTP and
verification code is allowed; merchant credentials and payment purposes stay bound.

The seller integration must support exact quote binding, idempotent create/capture,
status reconciliation, and idempotent delivery. Without these, it is not an eligible
MVP merchant. Network destinations come from operator configuration, not an agent
URL. Browser return/cancel URLs are fixed application routes.

## Records and typed contracts

Use integer USD minor units for purchases, separate from inference micro-USD.

| Record | Required identity and state |
| --- | --- |
| `merchant_connection` | Allowlisted merchant reference, environment, actual PayPal merchant ID, authenticated seller endpoint and credential reference; no secret in agent projections |
| `purchase_quote` | Owner/tenant/agent, merchant, offer/version, quantity, subtotal/tax/fees/shipping, all-in total, USD, license/terms digest, recipient/fulfillment reference, expiry, canonical digest |
| `purchase_operation` | Immutable quote ID/digest, owner request key/hash, purpose, exact approval ID, policy hold, checkout/order binding, stable create/capture keys, durable claim and payment state |
| `purchase_policy_hold` | Per-operation amount and applicable per-purchase/daily/monthly policy versions/windows; outstanding until known nonexecution or authoritative settlement |
| `payment_binding` | Purpose `service_topup` or `agent_purchase`, owner, local operation, environment, expected merchant, amount/currency, provider order; unique provider order identity across both flows |
| `provider_capture` | Unique `(environment, merchant_id, capture_id)` across both flows; payment binding, canonical status/amount and immutable observation history |
| `purchase_receipt` | Operation/capture identity, gross paid, externally refunded amount, safe reference and timestamps; unique settlement per operation/capture |
| `purchase_delivery` | Purchase and seller fulfillment IDs, delivery status, validated artifact reference/hash, license and retry metadata; one logical delivery |

`PurchaseQuote` is produced from authenticated seller data. The owner approval binds
its canonical digest plus purpose and the requesting agent. The agent cannot supply
an authoritative amount, payee, approved flag, capture ID, endpoint, or callback URL.
Idempotency keys are scoped to owner and operation; the same key with different
content returns conflict. Read/status/cancel routes always recheck tenant ownership.

## State and transaction boundaries

Payment states: `awaiting_owner`, `approved`, `checkout_creating`, `checkout_ready`,
`capture_claimed`, `payment_pending`, `reconciliation_pending`, `paid`, `declined`,
`cancelled`, `expired`, `failed`. Refund/dispute state is an overlay on the receipt.
Delivery states: `not_requested`, `pending`, `ready`, `failed`. Transport errors
never establish a definitive failure or nonpayment. An uncertain create also
blocks another create until the seller reconciles the existing request key.

1. **Quote:** validate a fresh seller quote and persist the canonical snapshot.
2. **Request review:** under `BEGIN IMMEDIATE`, check tenant, active agent,
   `purchase` capability, allowed merchant/item, quote expiry, per-purchase ceiling,
   and daily/monthly headroom. Reserve policy allowance, create the operation and
   pending confirmation, and append audit together. This hold reserves quota, not
   cash. Review creation cannot reserve the same last allowance twice.
3. **Owner approval:** authenticated owner session plus CSRF, expected version,
   unexpired exact digest, one-use confirmation. The owner approves or declines;
   the agent cannot call the approval route. Approval becomes a grant bound to the
   operation, consumed only by its successful capture claim.
4. **Create checkout:** persist the stable create key and seller binding before
   network I/O. Create one full-capture order for the immutable quote. The seller
   validates its own quote and returns the order identity and PayPal checkout URL.
   Bind that identity to the existing operation; never trust a browser-supplied
   order as a replacement. Only approved PayPal checkout origins may be returned.
5. **Buyer consent:** the owner completes PayPal Checkout. A callback is a signal
   to reconcile, not evidence that payment or even approval succeeded. Fetch the
   merchant's canonical order through the authenticated integration, verifying
   environment, payee, line items/reference, all-in total, currency, and buyer-
   approved status against the binding. A mismatch cannot reach capture.
6. **Claim capture:** atomically recheck the exact unconsumed grant, quote expiry,
   current owner/agent/capability/merchant policy, applicable limits, and verified
   order binding. Consume the grant and persist one capture claim and audit event
   under the same SQLite write lock used by pause, revoke, cancel, and expiry.
   Network capture follows commit, uses the persisted key, and is permitted only
   for that claim. A claim committed before revocation is already in flight.
7. **Finalize:** accept only canonical `COMPLETED` capture for the expected full
   amount and merchant, bound to the persisted capture claim and its consumed exact
   grant. Use that committed claim snapshot; a later revocation cannot invalidate
   an authorized in-flight capture. In one transaction, insert/deduplicate the global capture,
   mark the purchase paid, settle external purchase spend, release the policy hold,
   write the receipt/audit, and enqueue delivery. Do not post service-credit entries.
   A genuine out-of-band capture without that claim remains unexpected financial
   evidence: record the payment liability/spend once, quarantine and restrict the
   operation, and reconcile with the seller. Preserve any cancellation tombstone;
   never fabricate an approval, enqueue ordinary fulfillment, or resume the agent.
8. **Fulfill:** seller checks the completed purchase and delivers the licensed asset
   idempotently. Persist its receipt/hash before exposing `ready`. Delivery retries
   use the same purchase; never create another payment. Bound downloads by allowed
   origin, type and size; treat all asset contents as untrusted task data.

No database write lock spans an external request. The seller also persists create,
capture and fulfillment identity before its own calls; its responses must support
querying those operations after a timeout. Repeated `purchase.execute` calls return
the existing status/receipt and cannot create a second claim or order.

If a quote expires while creating checkout or waiting for the buyer, retain the
order binding but prevent capture. Cancellation/expiry before claim installs a
durable no-capture tombstone; a late callback cannot revive it. The controlled
seller must not auto-capture on browser approval. Release the hold only when the
claim was prevented and nonexecution is established. After a claim or ambiguous
capture, retain it and reconcile rather than reporting a safe cancellation.

## Policy accounting across windows

Use separate purchase limits; existing inference/compute budgets cannot stand in
for this category. For an active daily/monthly window, availability is its limit
minus settled external purchase gross in that window minus all outstanding holds,
including unresolved holds from earlier windows. Recheck both windows at final
claim, moving a reserved operation's window binding atomically if necessary.
For this check, require `settled gross + other outstanding holds + this operation's
amount <= current limit` in each window. Count this operation's existing hold
exactly once; a $1 purchase already holding the full $1 allowance remains eligible.
Lowered limits or a rollover can require renewed owner attention before claim.

On completion, count purchase gross once in the window of authoritative capture
time and remove the corresponding hold atomically. If capture was delayed into a
later window and now exceeds its limit, record the true spend, block further claims
as necessary, and show the overage; never hide a paid purchase to preserve a cap.
Claims made before that delay are already in flight. Windows are consistently UTC
for the MVP and are labeled in the UI. No guarantee of hard external settlement-
date limits is made for payments already in flight.

Refunds/reversals update cumulative economic loss/refunded principal by canonical
capture, deduplicating overlapping observations. Show paid and refunded separately.
Do not automatically replenish a spent approval or gross purchase quota. A dispute
or conflicting payment evidence restricts the affected purchase and new purchases
under that merchant connection until reconciled; it cannot create inference credit.

## Isolate funding from purchases

Register both order types in `payment_binding` before they can be captured. Every
capture/verified event is matched through that trusted registry using environment,
merchant and provider identities. PayPal `custom_id`, browser parameters, event
payload labels, and agent text are correlation hints, never routing authority.

The funding finalizer additionally requires `purpose=service_topup` and the expected
Habitat merchant. The purchase finalizer requires `purpose=agent_purchase` and the
integrated seller. Unmatched/contradictory events stay quarantined for reconciliation.
Register app-specific webhook verification configuration for each merchant; do not
verify a seller event with Habitat's unrelated webhook identity. Reuse the durable
inbox and signature/replay rules from the funding design. Payment acceptance,
restriction, and financial posting remain transactional within their purpose.

No payout operation converts Habitat service credit into seller payment. A purchase
capture or refund must never change the service-credit ledger, including when the
same owner or numeric amount appears in both flows.

## API and integration points

| Route / service | Responsibility |
| --- | --- |
| `POST /instances/{id}/purchases/quotes` | Authenticated reviewed runner/owner; trusted seller quote |
| `POST /instances/{id}/purchases` | Quote, reason, request key; reserve policy and request review |
| `POST /purchases/{id}/approval` | Human owner session, CSRF, expected version/digest; approve/decline |
| `POST /purchases/{id}/execute` | Resume bound operation; return owner/checkout requirement or existing status |
| `POST /purchases/{id}/cancel` | Owner/scoped tool; safe preclaim cancellation only |
| `GET /purchases/{id}` | Owner/agent-scoped safe receipt, payment and delivery status |
| Seller quote/order/capture/status/delivery ports | Fixed merchant integration, persisted identities, canonical evidence |

Add `purchases/{models,ports,service,policy,merchant,routes}.py`; share a purpose-aware
`payments` registry/inbox with funding. Reuse `control/confirmation.py`'s expiring,
payload-bound approval pattern, extending its current Gmail/Reddit-only action
catalog. Reuse `work/gate.py`'s atomic reservation discipline and `work/ports.py`'s
claim/tombstone pattern, without forcing external purchases into model-usage meters.
Only the scoped broker reaches the seller adapter. Owner tooling, agent tooling,
and any later MCP facade all converge on these same services.

## Acceptance and evidence

1. Correct seller quote yields exact review; spoofed price/payee/URL, expired quote,
   missing capability, cross-owner access, or disallowed seller is refused.
2. No owner approval or no PayPal buyer consent means no capture. Changed item,
   total, merchant, license, quantity or recipient requires new review.
3. Concurrent approvals/execute calls respect quota, consume one grant and produce
   one capture claim. Cancel/pause/revoke/expiry racing claim has one serialized
   winner and accurately reports any in-flight operation.
4. Response, callback, duplicate webhooks and restart settle one purchase once.
   Timeout after actual capture reconciles the original order; no second purchase.
   A capture without a committed exact claim records unexpected financial reality
   without reviving a cancelled task or triggering normal fulfillment.
5. Unknown create/capture and late callbacks retain correct holds/tombstones.
   Window rollover and changed limits cannot silently bypass the claim check.
   Claiming a purchase that already holds its full allowance counts that hold once.
6. Completed capture with failed delivery remains paid; delivery retry returns the
   same resource without another payment. A successful payment alone is not a
   successfully completed task.
7. Purchase captures/refunds cannot mint or debit service credit, and funding
   captures cannot satisfy purchase receipts. Wrong merchant/environment/purpose
   is rejected even when amount and owner match.
8. Real Sandbox buyer checkout produces distinct funding and seller capture
   receipts; the agent receives the actual seller asset and uses it in a metered
   real inference result. An unapproved follow-up purchase is refused visibly.

Use local fakes for deterministic race/replay failures and real Sandbox evidence
for checkout/capture/webhook integration. Verify the seller's actual asset/license
and test-account separation. The standard capture integration follows
[PayPal Orders](https://developer.paypal.com/api/rest/integration/orders-api) and
[capture semantics](https://developer.paypal.com/api/orders/v2/orders-capture).
These checks describe required future evidence, not tests already executed.
