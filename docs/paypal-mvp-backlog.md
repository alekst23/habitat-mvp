# Stable baseline and PayPal MVP implementation backlog

Updated October 19, 2026. The stable baseline is the **E11 owner-control MVP**,
including the responsive E11-6 UI. The next release adds both PayPal funding for
agent inference and owner-approved agent purchases. Design documents, diagrams,
and the demo script describe the external integration target.

The [local mock MVP](mock-paypal-mvp.md) now implements the complete rehearsal
journey with simulated payment, merchant and model adapters. It adds durable
top-ups and usage accounting, exact purchase approval, separate buyer checkout,
receipts, delivery and task resume. It credits a selected agent directly and uses
a cumulative purchase allowance. Real PayPal Sandbox captures, verified webhooks,
owner-wallet allocations and model calls remain pending below.

## What the baseline contains

- SQLite-backed instances, lifecycle, capabilities, budgets, reservations,
  confirmations, network policy, encrypted credential storage, and audit history.
- Magic-link sign-in, owner sessions/CSRF, wizard and scripted-chat creation,
  responsive workspace, agent controls, connections, usage and activity.
- Durable simulated execution and recovery; authorization and revocation checks.
- Reviewed PayPal [funding](design/paypal-funding/spec.md) and
  [purchase](design/agent-purchases/spec.md) contracts, editable diagrams, and a
  [2:50 target demo script](hackathon-demo-script.md).

The current runtime is still fake-only: no PayPal captures, real model calls,
merchant purchases, autonomous task runner, or deployment. Policy budgets are
limits, not money. The historical E11 evidence remains tied to its named commits.

## Itemized updates

The external integration criteria below remain pending. The local mock MVP is a
working basis for the shared records, controls, UI and runner, but is not evidence
of PayPal or model execution. Build the owner UI alongside each service slice.

| Order | Update | Depends on | Done when |
| --- | --- | --- | --- |
| 1 | Shared payment records and recovery | Existing auth, SQLite and audit | Orders/captures bind owner, environment, merchant, amount and purpose (`service_topup` / `agent_purchase`). Stable request IDs, verified webhook inbox and reconciliation settle once; unknown outcomes recover the same operation. A purchase can never mint inference credit. |
| 2 | PayPal top-ups, service-credit ledger and allocation | 1 | An actual Sandbox capture into Habitat's merchant account credits once after verified completion. Owner allocation transfers existing credit atomically. Pending payments stay unfunded; concurrent reservations conserve credit; refunds/reversals retain history and restrict spending correctly. |
| 3 | Bounded real inference proxy | 2; adapter can start against contract fakes | One approved model accepts server-built cost quotes and enforced input/output/time limits. Atomic holds cover customer credit, policy and operator real-cost headroom. Actual output and measured usage settle once; missing usage/timeouts retain holds. Client simulation estimates cannot authorize real spend. |
| 4 | Purchase capability, tools and approval broker | 1; parallel with 2–3 | Add quote, request-approval, execute, status and cancel tools. Trusted quotes bind seller/item/version/quantity/all-in total/license/recipient/expiry. Exact owner approval is single-use. Separate purchase-policy holds prevent overspend; changed or unapproved transactions cannot capture. |
| 5 | Integrated Sandbox seller and paid asset delivery | 1 and 4 | A distinct Demo Template Shop merchant sells one owned/licensed template. Buyer checkout and verified capture produce its receipt. Delivery returns the actual asset after payment. Delivery retries never buy again; duplicate/uncertain capture and restart reconcile the original order. |
| 6 | Reviewed agent runner with durable pause/resume | 3–5 | A real model plans a launch kit, selects the allowed offer, requests a purchase, pauses for owner/PayPal consent, resumes, consumes the asset as untrusted data, and saves useful output. Steps and total run cost are bounded. Preserve a portable runner contract; no arbitrary uploaded programs. |
| 7 | Funding, purchase and task UI | Build with 2–6 | Show service credit, allocations, resource limits and purchase policy separately. Provide exact transaction review, checkout, payment/delivery status, receipts, output and actionable readiness messages. Update balances/activity automatically after changes; preserve uncertainty without inviting duplicate submissions. |
| 8 | End-to-end demo evidence and release checks | 1–7 | Record a fresh Sandbox top-up and separate seller capture, the purchased asset used in measured real-model output, and an unapproved follow-up refused before payment. Verify changed-quote denial, concurrency, replay/restart, purpose isolation and reversal races. Rehearse the 2:50 script with reproducible setup. |

Recommended order: establish the shared payment contracts, then run funding and
purchase development in parallel. Connect real inference after funded reservations
work. Finish the agent's pause/resume journey once both integrations are reliable.
The first complete PayPal demo requires **both payment roles**.

## Configuration and assets required

- Habitat Sandbox merchant/app for top-ups and a distinct Sandbox seller/app for
  purchases, plus a buyer test account able to approve both checkout flows.
- One owned/licensed digital template with fixed catalog ID, version, USD price,
  terms and authenticated delivery endpoint.
- Webhook verification configuration for each merchant app; public HTTPS delivery
  via a development tunnel or eventual host for actual webhook acceptance tests.
- One model credential, fixed model/pricing configuration, and an explicit small
  operator real-cost ceiling. Sandbox credit never increases that ceiling.
- A durable local database, secret configuration outside Git/agent context,
  migration/restart instructions, and distinct simulated/Sandbox UI labels.

These inputs are prerequisites for external integration testing, not proof that
any account or secret is already configured.

## Keep outside this first release

Cloud deployment, arbitrary owner-supplied programs, multiple models, arbitrary
merchant shopping, live advertising, automatic top-ups, wallet vaulting/delegated
payment programs and public MCP hosting can follow later. MCP is an optional tool
transport; it does not replace AICL authorization or buyer consent. Real compute
billing needs an enforced meter before it can charge service credit; shared hosting
can remain operator-provided capacity.

## Verification boundary

The application source baseline is `419e77b9ab89173a3ee0531facec1c618324c4c3`:
its recorded UI pipeline passed 73 backend tests, four browser journeys, scoped
acceptance and the mandatory security/package/configuration checks. The stable-main
integration carries that application plus documentation and whole-epic verification
selection. Its merge request/pipeline is the source of current integration evidence;
the older passing checks are not claimed for a newer commit.

Local working databases, credentials, downloaded CI artifacts, temporary diagram
canvas backups, and unrelated sibling repositories are not release source.
