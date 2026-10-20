# PayPal funded AICL technical design

Status: proposed, October 19, 2026. Implements the
[funding specification](spec.md) as a follow-on to the existing E11 application;
does not alter its historical acceptance claims. No live money movement or provider
enablement is performed by this document.

## Runtime boundary

Keep FastAPI, server-rendered pages, and one persistent SQLite database. Payment,
ledger, AICL gate, inference adapter, and reconciliation are modules in that host.
The first reviewed agent executes under the authenticated owner's scoped context;
a later portable runner receives restricted work authority, never PayPal or model
provider credentials. No MCP server is needed for this internal contract. A future
MCP transport must call the same authorization services without bypassing them.

Add explicit composition choices for fake tests and PayPal Sandbox plus real
inference. Preserve existing fake defaults. Configuration selects fixed PayPal
API origins and a fixed model endpoint; untrusted payloads cannot supply them.
The initial payment adapter accepts Sandbox only. Live payments remain a separate
release/configuration decision.

## Payment contract

`FundingService.create_order(auth, amount_minor, destination_instance?, request_key)`
validates a server-configured top-up amount and USD currency. It derives owner and
tenant from authentication and binds the optional destination to that owner. It
persists the funding attempt and stable create/capture request IDs before network
I/O. The owner request key is bound to a payload hash: identical replay returns the
same attempt; changed amount or destination conflicts.

Create a trusted `payment_binding` with `purpose=service_topup`, owner, environment,
expected Habitat merchant, amount/currency and local attempt, adding the order ID
when known. The [purchase broker](../agent-purchases/technical.md) shares this
registry and global capture identity, but uses `purpose=agent_purchase` and the
integrated seller. Purpose is immutable. Agent text, browser input and provider
`custom_id` cannot choose a finalizer or credit destination.

Create one Orders v2 purchase unit using `intent: CAPTURE`, the configured merchant,
and the local attempt reference. The provider return identifies an existing local
attempt; it cannot choose which account receives credit. The owner approves through
PayPal Checkout. An authenticated, CSRF-protected capture route checks the attempt
binding before requesting capture with its persisted capture key.

`apply_capture(observation)` is the only crediting path. It verifies the canonical
order/capture against the trusted `service_topup` binding, owner-bound attempt,
Sandbox environment, Habitat merchant,
amount, currency, order ID, and capture ID. A matching `COMPLETED` capture inserts
one funding posting, any explicitly requested valid allocation, and the audit
record in one transaction. A completed order by itself is insufficient. For this
MVP each funding order has one full capture; reject unexpected partial or multiple
captures for manual reconciliation rather than guessing the credited amount.

The create/capture HTTP response, webhook worker, and polling reconciler all call
that same finalizer. Enforce capture uniqueness separately from event uniqueness:
different events and a synchronous response can describe the same payment.
The unique `(environment, merchant_id, capture_id)` record is shared across funding
and purchases. A purchase capture or refund cannot create a service-credit posting;
a contradictory or unmatched purpose/merchant is quarantined for reconciliation.

PayPal documents buyer approval before capture, and an API-specific retention
period for `PayPal-Request-Id`. Stable IDs help retry an operation; they are not a
permanent substitute for local identity and provider reconciliation. After timeout
or expired provider retention, query the existing order/capture before deciding
whether another request is safe. Do not generate a new key to escape ambiguity.
[Capture](https://developer.paypal.com/api/orders/v2/orders-capture),
[idempotency](https://developer.paypal.com/api/rest/reference/idempotency/)

Local attempt states: `created`, `checkout_ready`, `capture_requested`,
`payment_pending`, `reconciliation_pending`, `funded`, `failed`, `cancelled`.
Refund/reversal/dispute status is an overlay on the payment record, not a reset to
an unfunded attempt. Out-of-order completion evidence cannot restore reversed
credit. No two terminal outcomes are inferred from transport errors alone.

## Payment events and reconciliation

Use PayPal's signature-verification endpoint with the registered webhook ID,
original event body, and transmission headers. Reject invalid authenticity;
transient verification failure remains retryable. Persist authenticated events
before acknowledging them and process through a durable inbox. For authenticated
adverse evidence mapped to a known account, accepting the inbox event and freezing
that account are one transaction; monetary adjustment can await reconciliation.
Store raw material
only in restricted storage with retention limits; normal logs and agent tools get
safe identifiers and status, not payer data or credentials.

Subscribe to the account/API's supported completed, pending, declined/denied,
refunded, reversed, and dispute events. Current PayPal references use different
declined/denied naming in different API families; normalize supported failures and
re-fetch authoritative payment state. Unmatched verified events are retained for
reconciliation and cannot credit an arbitrary account.
Route matched events through trusted local payment bindings, using the correct
merchant app's webhook verification configuration. Funding restrictions and credit
adjustments apply only to funding bindings; seller purchase events update their
own purchase policy and receipts.

The worker retries pending/unknown local attempts and accepted-but-unprocessed
events with bounded backoff. Network calls occur outside SQLite write transactions.
Authoritative observations are applied transactionally afterward. Capture replies
can fund the account without waiting for a webhook; later events deduplicate.
Local checkout can work with the server capture response and polling. End-to-end
webhook testing needs a public HTTPS endpoint, supplied by the eventual host or a
development tunnel; it is not implied by running localhost.

Test verification with actual Sandbox-app events; PayPal's simulator has different
signature-verification constraints. [Webhook verification and delivery](https://developer.paypal.com/api/rest/webhooks/rest/),
[event names](https://developer.paypal.com/api/rest/webhooks/event-names/)

## Records and invariants

Use forward-only migrations and integer arithmetic. PayPal USD cents convert
exactly to micro-USD; usage supports fractional cents. Round maximum-cost quotes
up, never down, and settle using the same documented price-version rounding rule.
Do not round each inference call to PayPal cents. Preserve existing budget
history and append new records rather than rewriting old usage.

| Record | Fields and constraints |
| --- | --- |
| `funding_account` | Owner/tenant, payment environment, USD, active/frozen state, reason, version; unique `(tenant_id, environment, currency)` |
| `funding_attempt` | Account, destination intent, owner request key/hash, expected amount/currency/merchant, order/capture identities, distinct stable create/capture keys, state and timestamps; unique `(environment, order_id)` and owner request key |
| `payment_binding` / `provider_capture` | Shared purpose-aware registry and globally unique capture identity defined in the [purchase contracts](../agent-purchases/technical.md); each funding attempt and receipt references these records |
| `payment_receipt` | Unique `(environment, merchant_id, capture_id)`; gross, fee, net, issued credit, provider status, source references; adjustments preserve the original receipt |
| `paypal_event` | Unique `(environment, event_id)`, resource ID, body hash, verification/processing status, retry metadata; durable inbox |
| `funds_entry` | Immutable postings: account, owner or agent bucket, signed micro-USD, operation type/key, source capture/refund/hold, timestamp; unique operation key plus posting ordinal |
| `funds_hold` | Existing budget hold ID, account/agent, maximum customer charge and provider cost, customer/provider price versions, operator-policy version; lifecycle derived from existing hold |
| `execution_receipt` | Unique hold ID; canonical request hash, provider/model/request ID, actual usage, customer charge, provider cost, price versions, output reference, evidence status |

The ledger has owner-unallocated and per-agent buckets. Allocation/reclaim creates
equal and opposite postings in one transaction; only unheld credit can move.
Captured top-ups issue credit once. Work settlement consumes credit once. Active
holds, including unknown outcomes, reduce availability but do not count as settled
usage. A materialized balance may be maintained in the same transaction and must
reconcile to the postings and holds.

Conservation, in one environment/currency, including adverse outcomes:

```text
L = issued service credit - usage charges - accounted refunds/reversals
H = active agent holds + refund holds
free credit = max(0, L - H)
shortfall = max(0, H - L)
L = free credit + H - shortfall
```

In an unrestricted account, free credit is owner-unallocated plus agent-available
credit summed across instances. A frozen account cannot dispatch even when free
credit is positive. The realized deficit is `max(0, -L)`; the remainder of the
shortfall is exposure covered by outstanding reservations rather than settled usage.
Both are derived views, not extra financial debits. Example: a $5 reversal when
all $5 is held gives `L=0, H=5, shortfall=5`. Releasing that hold makes shortfall
zero; settling $2 instead gives `L=-2, H=0, shortfall=2`. Record the usage debit
once; do not append another loss to make the view balance.

Operator cost holds are a separate ledger/policy dimension and are not deducted
again from customer credit.
Keep sandbox and live identities, databases or account partitions, and balances
distinct. No synthetic payment entry can be promoted into live funding.

## Trusted quote and atomic dispatch

Add a `ResourceQuote` with canonical request digest, instance/policy version,
provider and model, customer and provider price versions, maximum input/output
tokens, timeout, maximum customer charge by category, and maximum provider cost.
Build it server-side from the fully assembled request. The adapter must enforce
the same model and bounds and fail closed for unsupported pricing dimensions.
For the first release, reject models/features whose maximum cost cannot be bounded.

Extend `SqliteWorkGate._reserve_and_consume()` in `backend/aicl/work/gate.py`.
Within its existing `BEGIN IMMEDIATE` transaction:

1. Re-read work identity and request digest. Identical replay returns the existing
   operation/result; different content conflicts.
2. Recheck authenticated owner, agent lifecycle, capability, and policy version.
3. Require an active matching funding account and enough available agent allocation.
4. Require all applicable category daily/monthly headroom to fit the customer quote.
5. Require the independent operator global/run ceiling to fit the provider quote.
6. Create the budget hold, funds/operator hold, work record, required approval
   consumption if applicable, and audit append together.
7. Commit, then claim and dispatch the operation once through the durable executor.
   The claim transaction rechecks the funding account is active under the same
   SQLite write lock used by event acceptance/freeze. A claim committed before a
   freeze is already in flight; a claim after the freeze cannot start. A reserved
   but unclaimed operation can be resolved as not-started and release its holds
   with the existing tombstone protection. Network dispatch follows a successful
   persisted claim; no database lock spans the network call.

The funding check and policy limits are both required; a top-up cannot bypass a
daily cap, and a larger cap cannot mint funds. An operator ceiling may be $0 even
when the sandbox balance is large. Insufficient operator capacity is reported as
service/provider budget unavailable, not an instruction for the owner to pay again.

One SQLite file serializes these mutations. Do not run independent application
replicas against separate local files and claim a shared atomic balance.

## Settlement, uncertainty, and overrun

The provider receipt is trusted usage evidence. Persist output and receipt before
exposing a final success. In one settlement transaction, append the actual service
debit and provider cost, settle category usage, release the unused reservation,
and mark work terminal. If settlement persistence fails, keep the hold for recovery.

Known no-start/no-usage failure can release the hold. Unknown dispatch, absent
usage, timeout, or process death retains both customer and operator reservations.
Reconciliation uses provider evidence where available or an explicit operator
resolution; lack of evidence alone cannot release funds. Preserve the existing
executor's no-start tombstone to prevent a late invocation after release.

Actual usage above the enforced quote is an adapter fault. Stop further dispatch,
record full provider liability and an explicit platform-loss adjustment, and cap
the customer charge at the authorized maximum. Do not silently debit beyond the
owner's reservation. Unknown cost dimensions must block the quote in the first place.

The real-cost ceiling covers calls through this proxy, not unrelated provider
usage or fixed hosting bills. Dedicated provider credentials/account controls and
operator billing capacity remain the external backstop.

## Refunds, reversals, and disputes

On verified adverse evidence, freeze the known affected account in the inbox
acceptance transaction. Preserve outstanding holds until their operations resolve;
claims committed before the freeze may still incur costs. Dispute opening restricts
the account but is not itself proof of a completed loss.

Track issued credit and already-accounted economic loss for each capture. Normalize
refund/reversal evidence into the authoritative cumulative lost capture principal,
then append only the unposted delta. Refund IDs help identify losses; event IDs
alone do not. A refund notification and reversal observation covering the same
principal cannot debit it twice. Customer-credit loss cannot exceed the credit
originally issued for that capture; processor/dispute fees are separate operator
expenses. If provider evidence cannot resolve overlapping amounts, keep the account
frozen for review instead of summing them speculatively.

If adverse evidence precedes original credit issuance, retain a nonspendable payment
tombstone and post neither credit nor debit. A later stale completed event cannot
fund it. For a fully lost capture this remains a no-credit/no-debit outcome. For a
partially refunded capture, reconciled historical issuance and all known adjustments
may be posted together under the freeze, with no intermediate spendable balance.
Only reviewed canonical state can then release the restriction.

For already-issued credit, apply the single adjustment under the freeze and reclaim
free owner credit, then free agent allocations in a deterministic order. Preserve
signed account net credit and outstanding holds; display the derived shortfall and
realized deficit defined above. Do not remove reservations, clamp away debt, or
invent a second loss entry. Future settlement or no-start release updates that
shortfall from actual state.

The first UI can defer refund initiation, but must handle external refund/reversal
events. A future refund request first locks refundable unspent credit, makes the
provider request with a stable ID, and retains that lock for pending/unknown results.
Only confirmed outcome finalizes or releases it. Unfreezing requires reconciled
state; a delayed old completion event cannot unfreeze the account.
[Refund API](https://developer.paypal.com/api/payments/v2/captures-refund)

## APIs and modules

| Route | Contract |
| --- | --- |
| `GET /funding` | Owner-scoped balances, allocations, safe receipt/status projection |
| `POST /funding/orders` | Owner session + CSRF; allowed amount, optional agent destination, idempotency key; returns local attempt and checkout data |
| `POST /funding/orders/{attempt_id}/capture` | Owner binding + CSRF; captures/reconciles the persisted order; no client credit amount |
| `GET /funding/orders/{attempt_id}` | Owner-scoped status polling; no mutation based on browser claims |
| `POST /instances/{id}/funding-allocations` | Atomic owner-approved transfer of available credit; expected version and idempotency key |
| `POST /webhooks/paypal` | Provider signature authentication; no owner session/CSRF; bounded payload, durable inbox, replay-safe processing |
| `POST /instances/{id}/runs` | Reviewed task input and request ID; server computes trusted quote; rejects simulation fields and client prices |
| `GET /instances/{id}/runs/{run_id}` | Owner-scoped output, usage, holds, errors and safe evidence |

New modules: `funding/{models,ports,service,paypal,ledger,routes}.py` and
`inference/{quote,provider,executor}.py`. Register through existing application
composition. Extend `control/budget.py`, `work/gate.py`, the executor contract,
settings, migrations, and owner projections; keep the simulated endpoint separate.

Secrets: PayPal Sandbox client secret, webhook ID/configuration, and model-provider
credentials belong to operator configuration, not prompts or agent tools. Browser
client ID exposure follows the selected PayPal Checkout integration; the secret
never enters browser code. Pin allowed provider/model, customer/provider prices,
top-up denominations, and real-spend limits explicitly before real inference starts.

## Existing code changes required before real calls

- `work/routes.py` accepts client token/compute estimates; replace that authority
  on the real-run path with a server-built quote.
- The existing executor contract lacks enforced model/output/time bounds; add
  them and reject simulation payloads in the real adapter.
- `work/gate.py` currently substitutes zero usage when a fake result lacks usage.
  Real execution must classify missing billing evidence as unknown.
- `control/budget.py` currently demands positive values for all four limits.
  Check categories with a positive charge for inference-only execution; preserve
  fail-closed handling of missing applicable policy.
- `control/price_table.py` has generic example meters. Bind real pricing to one
  approved provider/model and preserve separate service-price and provider-cost
  versions. Example data cannot authorize real dispatch.
- Capture completion and settlement must update balances/readiness/activity
  together in the UI. The prior manual-refresh behavior is insufficient here.

## Focused acceptance cases

1. Response plus repeated/different completion events credits one capture once;
   amount/merchant/owner/environment mismatch never credits.
2. Timeout after PayPal completed capture recovers that same payment; pending
   capture remains unfunded; browser-only approval cannot fund anything.
3. Concurrent allocation and request attempts conserve credit; a changed payload
   under an existing operation key conflicts.
4. Empty funding with positive limits denies before provider invocation; funded
   credit with a breached category limit also denies.
5. A large sandbox top-up cannot bypass a zero or exhausted real provider ceiling.
6. A bounded real task saves output and measured usage, settles one debit, and
   returns the same result on replay without another provider call.
7. Missing usage, timeout, and restart retain holds until authoritative recovery;
   a no-start resolution cannot race a delayed executor into paid work.
8. A reversal racing reservation/claim prevents post-freeze claims, retains in-flight
   holds, and accounts for loss once. Reversal-before-credit and overlapping refund/
   reversal evidence cannot debit unissued credit or duplicate a loss; hold release
   and settlement correctly change the derived shortfall. Stale completion is inert.
9. Browser journey shows top-up, pending/completed receipt, allocation, live result,
   current balances, and an actionable insufficient-funds state without manual refresh.
10. Purchase captures/refunds never change service credit, and funding captures
    cannot settle seller purchases; wrong purpose/merchant/environment is rejected.

Use focused local fake-provider tests for failure/race cases, plus actual Sandbox
capture/webhook evidence and one explicitly budgeted real-model run for integration
acceptance. Test fixtures alone cannot establish either external integration.
