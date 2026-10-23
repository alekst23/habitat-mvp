# PayPal Sandbox checkout

Habitat can now use PayPal's Sandbox Orders API for agent funding and
owner-approved purchases. The local mock-payment demo remains available. Sandbox
uses PayPal-hosted checkout and test money; there is no live-payment mode.
By default, inference and completion checks use local scenario fixtures. The
launcher also supports separately configured real inference; compute execution,
ad delivery and campaign results remain simulated. A Sandbox purchase proves
payment to the configured test seller, not a connection to a real advertising
platform.

## What you need

1. A [PayPal Developer account](https://developer.paypal.com/dashboard/).
   In **Apps & Credentials**, select **Sandbox** and create or select a REST app
   belonging to a Sandbox **Business** account. Save its client ID and client
   secret privately. [PayPal's API setup guide](https://developer.paypal.com/api/rest/)
   describes the app and credential setup.
2. The receiving Business account's **PayPal Merchant ID**, not its email or app
   client ID. Sign in as that Business account at
   [PayPal Sandbox](https://www.sandbox.paypal.com/), then open **Account Settings →
   Business information → PayPal Merchant ID**.
   [PayPal's merchant-ID guidance](https://developer.paypal.com/platforms/checkout/save-payment-methods/onboarding/platform/)
   confirms the same location for Sandbox accounts.
3. A Sandbox **Personal** buyer account with a test balance. Find its login under
   **Testing Tools → Sandbox Accounts → View/Edit Account**. Use that login at
   checkout, not your real PayPal account. Personal accounts buy; Business accounts
   receive funds. [Sandbox accounts guide](https://developer.paypal.com/sandbox-testing/accounts).
4. For the complete agent-purchase journey, a **second Sandbox Business account
   and its own REST app**. Provide that app's client ID, secret and merchant ID as
   the purchase-seller settings below. Without all three, agent purchases stay
   disabled; service-credit top-ups still work. These are two seller-owned apps,
   not a marketplace or partner-onboarding integration.

No external webhook endpoint or tunnel is required for this local MVP. PayPal
redirects the buyer's browser back to the local return or cancel URL. The server
verifies the order with PayPal; a redirect alone never proves payment. Interrupted
or uncertain outcomes use the same order's reconciliation action. Webhooks,
refund/dispute handling and production deployment are separate follow-on work.

## Save credentials privately

From the `e11-epic-completion` repository, create an ignored file such as
`.ctx/paypal-sandbox/credentials.env`, restrict it to your account (`chmod 600`),
and enter these values in your editor:

```dotenv
AICL_PAYMENT_MODE=paypal_sandbox
AICL_PAYPAL_CLIENT_ID=YOUR_SANDBOX_SERVICE_CLIENT_ID
AICL_PAYPAL_CLIENT_SECRET=YOUR_SANDBOX_SERVICE_CLIENT_SECRET
AICL_PAYPAL_MERCHANT_ID=YOUR_SANDBOX_SERVICE_MERCHANT_ID

# Required only when demonstrating approved agent purchases:
AICL_PAYPAL_PURCHASE_CLIENT_ID=YOUR_SANDBOX_SELLER_CLIENT_ID
AICL_PAYPAL_PURCHASE_CLIENT_SECRET=YOUR_SANDBOX_SELLER_CLIENT_SECRET
AICL_PAYPAL_PURCHASE_MERCHANT_ID=YOUR_SANDBOX_SELLER_MERCHANT_ID
```

Replace all placeholders. For funding only, omit the three purchase-seller lines.
Do not paste secrets into chat, source control, demo captions or screenshots.
The client secrets stay in server settings and are masked in settings output;
they are not passed to an agent. The file reader accepts literal `KEY=value`
lines, optional matching quotes, blank lines and full-line comments. It does not
execute shell code or expand variables. Only the seven variables above are
accepted in this file. Environment variables are also supported; file values
override matching environment values. Do not source this file as shell code.

## Start the isolated local server

Use the project's Python environment with `backend/requirements.txt` installed.
From this checkout, the existing workspace environment can run it directly:

```sh
PYTHONPATH=backend ../e11-completion/.venv/bin/python -m aicl.sandbox_server \
  --credentials-file .ctx/paypal-sandbox/credentials.env --check-config

PYTHONPATH=backend ../e11-completion/.venv/bin/python -m aicl.sandbox_server \
  --credentials-file .ctx/paypal-sandbox/credentials.env
```

With a fresh checkout, create a local virtual environment, install
`backend/requirements.txt`, and substitute `.venv/bin/python` in those commands.

The configuration check makes **no API request**. Starting the server also makes
no purchase or automatic payment; the owner initiates checkout in the app.
Network access to `https://api-m.sandbox.paypal.com` is required when paying or
checking an order. Invalid/missing settings fail before startup and name the
variable without printing its value. Sandbox mode rejects production settings,
live mode and mixed mock-payment API credentials.

The server prints its URL, then listens only at
[http://127.0.0.1:4180](http://127.0.0.1:4180). It uses a separate persistent
database at `.ctx/paypal-sandbox/aicl.db`, preserving the existing demo on port
4173. `--port` and `--database` can override those defaults. Use a separate
browser profile for the Sandbox app: browsers share cookies between ports on the
same host, so logging into one local preview can replace the other preview's
session cookie.

This launcher uses fixed local test keys and captured sign-in email. Do not expose
it publicly. Request a Habitat sign-in link, then open
`/__test__/last-magic-link?email=YOUR_EMAIL` on port 4180 and follow the returned
link. The email is your Habitat identity; the Sandbox buyer login is entered only
on PayPal's site. Keeping the same local database and test keys preserves Habitat
identities across restarts.

## Demonstrate and verify the payment flow

1. On the isolated server at port 4180, sign in to Habitat, open **Create an
   agent** (`/agents/new`), and create **PocketPlan Sandbox** with the **inference**
   capability enabled. Select **Configure goals & schedule**, then **Use app
   marketing example**. This saves the campaign goals, deliverables, completion
   criteria and daily schedule. Use this button before saving a custom workflow;
   it is available only while the workflow is unsaved.
2. Open the agent's controls (`/instances/{id}#budgets`). Set all four inference
   and compute limits, for example $1 daily and $5 monthly for each category,
   then **Save limits**. Under **Agent purchase allowance**, enable purchases,
   set **Total purchase limit (USD)** to $30, and **Save purchase controls**.
   A $45 allowance also permits the optional later $15 expansion; it is not
   needed for the first purchase. In **Funding**, click **Add $5.00 with PayPal**.
3. Click **Continue to PayPal**, sign in as the Sandbox Personal buyer, and consent to the
   payment. When the browser returns to Habitat, click **Finish approved payment**.
   Confirm the resulting order shows its PayPal reference and funding receipt.
   Service credit is added only after
   the server verifies the completed capture, amount, currency and receiving
   merchant. Use the Personal buyer rather than either receiving Business account.
4. Return to **Goals & schedule** and click **Enable schedule**. This also
   activates the draft agent after its controls pass. Expand **Demo controls**
   and click **Advance to next scheduled run** once. The first occurrence produces
   a campaign plan, ad creative and a $30 campaign purchase recommendation.
   Open **Audit → Purchases** (`/audit?view=purchases&instance_id={id}`), review
   the linked source work and exact campaign scope, select **Start now**, then
   **Approve purchase**. Owner approval authorizes the request; it does not itself
   pay the seller. Wait until this payment is verified before advancing another
   occurrence, which can create reports and a separate expansion proposal.
5. Continue the approved purchase through PayPal checkout using the second
   Business seller configuration. The buyer consents again on PayPal, then clicks
   **Finish approved payment** after returning to Habitat. This is a
   separate seller payment; it does not debit inference/compute service credit.
6. Confirm the funding and purchase receipts in Habitat and the test transactions
   in the relevant Sandbox Business accounts. Save order/capture IDs as evidence;
   keep buyer credentials, client secrets and access tokens out of the recording.
7. Exercise cancel and recovery: cancel checkout without adding credit; refresh a
   completed receipt without creating a duplicate payment; if checkout is
   interrupted, reconcile that order instead of starting another one.
   If the purchase approval expires while on PayPal, review the original seller,
   scope and amount, check the renewal box and finish that same payment. This
   creates a fresh audit entry and repeats AICL checks without creating another
   PayPal order. Changed quotes require a new approval and cannot use this renewal.

External Sandbox funding and purchase transactions, including their hosted buyer
checkout and browser return, were verified on 22 October 2026 as recorded below.
Deterministic adapter, service and configuration tests remain separate from that
external transaction evidence.

Initial implementation verification (22 October 2026): 278 backend tests passed across
the main suite and the separate loopback payment-process test. One existing
test-server launcher check was excluded because it requires port 4173, which is
occupied by the current demo. Browser checks covered checkout, the return page,
capture, receipt and funding credit using an isolated HTTP test double. No real
PayPal account credentials or external Sandbox transaction were used in those
checks. The port 4173 demo remained on mock payments.

Account setup verification (22 October 2026): both Sandbox Business REST apps
are configured for the service-funding and purchase-seller roles. Configuration
validation and Sandbox OAuth authentication succeeded for both apps. Credentials
are stored in the Git-ignored `.ctx/paypal-sandbox/credentials.env` file with
owner-only `0600` permissions. The isolated application uses port 4180. OAuth
checks created no order or payment; they establish API access, not a completed
checkout or capture.

Hosted payment verification (22 October 2026): a Sandbox Personal buyer completed
both PayPal-hosted checkouts, returned to Habitat, and finished the approved
payments. Habitat recorded these verified captures:

| Purpose | Amount | Result |
| --- | --- | --- |
| Agent service credit | $5.00 USD | Completed capture and one funding receipt |
| Owner-approved PocketPlan campaign | $30.00 USD | Completed capture and one purchase receipt |

A read-only ledger check at 23:40 UTC found both orders completed, exactly one
receipt per order, exactly one $5 funding credit, and no service-credit entry for
the separate seller purchase. Three simulated inference usage entries totaled
$0.006, leaving $4.994 of service credit. Purchase allowance recorded $30 spent
and $0 held. Receipt amounts, currencies and purposes matched their orders, with
no binding mismatches. After both completed receipt pages were refreshed, a second
read-only check at 23:41 UTC confirmed that order states, capture references,
receipt counts, funding-credit count and balances were unchanged. Audit displayed
the funded campaign and its linked source job and outputs. Redacted local evidence,
including provider order and capture references, is saved in
`.ctx/paypal-sandbox/payment-verification.json`; no credentials or buyer details
are included. This verifies Sandbox payments, not real advertising delivery.

For the hackathon video, replace the existing mock top-up and purchase checkout
shots with this real Sandbox journey. Keep the explanation concise: PayPal funds
agent operations, AICL controls spending, and each agent purchase requires owner
authorization plus PayPal buyer consent. Label the environment **PayPal Sandbox**
and keep the simulated AI/advertising limits clear in the closing disclosure.
