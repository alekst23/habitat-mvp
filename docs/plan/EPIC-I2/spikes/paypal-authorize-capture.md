# Spike: PayPal Authorize-and-Capture — Feasibility Findings

**Ticket:** E2-1 (issue #3)  
**Epic:** E2 (issue #2)  
**Date:** 2026-10-06  
**Spike scope:** Confirm authorize-and-capture flow, partial/multiple captures, authorization validity window, sandbox behavior, and account type requirements.

## Summary

**Go/No-Go:** ✅ GO — PayPal Orders API v2 supports authorize-and-capture with partial/multiple captures. Sandbox behavior matches production for the flows we need. Standard developer accounts support this flow.

---

## Findings

### 1. Authorize-and-capture flow

Source: https://developer.paypal.com/docs/api/orders/v2/ and https://developer.paypal.com/docs/checkout/advanced/

- PayPal Orders API v2 supports `intent: AUTHORIZE` at order creation.
- Flow:
  1. `POST /v2/checkout/orders` with `intent: AUTHORIZE` → returns `order_id`
  2. Buyer completes PayPal checkout (redirect or JS SDK)
  3. `POST /v2/checkout/orders/{order_id}/authorize` → returns `authorization_id`
  4. `POST /v2/payments/authorizations/{authorization_id}/capture` → captures funds
- This is the correct flow for Habitat: authorize the full budget upfront, capture incrementally as the agent spends.

### 2. Partial and multiple captures

- **Partial captures are supported:** The capture endpoint accepts an `amount` field; if less than the authorized amount, the remaining authorization stays open.
- **Multiple captures are supported:** Multiple `POST /v2/payments/authorizations/{id}/capture` calls can be made against a single authorization, up to the authorized amount.
- The `final_capture: true` flag must be set on the last capture to release the remaining authorization.
- This maps directly to Habitat's model: reserve the full budget, capture as the agent incurs costs.

### 3. Authorization validity window

- PayPal authorizations are valid for **29 days** from the authorization date.
- After 29 days, the authorization expires and cannot be captured.
- Habitat must track authorization expiry and prompt the owner to re-authorize before expiry if the budget is not fully consumed.
- The authorization can be voided early with `POST /v2/payments/authorizations/{id}/void`.

### 4. Sandbox behavior

- PayPal Sandbox (https://developer.paypal.com/tools/sandbox/) provides test buyer and seller accounts.
- Sandbox behavior **matches production** for the authorize-and-capture flow, including:
  - Partial captures
  - Multiple captures
  - Authorization expiry (simulated)
  - Webhook events (PAYMENT.AUTHORIZATION.CREATED, PAYMENT.CAPTURE.COMPLETED, etc.)
- Sandbox webhooks can be tested via the PayPal Developer Dashboard.
- **Webhook signature verification** works the same in sandbox and production; the verification key differs.

### 5. Account type requirements

- The authorize-and-capture flow is available to **all PayPal Business accounts** and to Personal accounts in some regions.
- A standard PayPal developer account with sandbox credentials is sufficient for development and testing.
- No special approval or elevated account type is required for the authorize-and-capture flow itself.
- **Note:** For live payments, the seller account must be a Business account. For the hackathon demo, sandbox is sufficient.

### 6. Webhook events relevant to Habitat

| Event | Meaning |
|---|---|
| `PAYMENT.AUTHORIZATION.CREATED` | Authorization succeeded; safe to credit ledger |
| `PAYMENT.AUTHORIZATION.VOIDED` | Authorization voided; remove from ledger |
| `PAYMENT.CAPTURE.COMPLETED` | Capture succeeded; settle ledger entry |
| `PAYMENT.CAPTURE.REFUNDED` | Capture refunded; reverse ledger entry |
| `CHECKOUT.ORDER.APPROVED` | Buyer approved; proceed to authorize step |

- Webhook signature verification: use the `PAYPAL-TRANSMISSION-SIG` header and the PayPal public key (fetched from the PayPal cert URL in the webhook headers).
- Duplicate webhook delivery: PayPal may deliver the same event multiple times. Habitat must use the event ID as a uniqueness key (F7-S2 in spec).

### 7. Re-fetching authorization before crediting

- Per spec F7-S1: credit the ledger only after re-fetching the authorization from PayPal.
- Use `GET /v2/payments/authorizations/{authorization_id}` to confirm status is `CREATED` before crediting.
- This prevents crediting on a spoofed or replayed webhook.

---

## Go/No-Go Decision

**Primary path (PayPal Orders API v2, authorize-and-capture):** ✅ GO
- Standard developer account is sufficient.
- Sandbox matches production for all flows we need.
- Partial/multiple captures work as required.
- 29-day authorization window is acceptable; Habitat must track and warn before expiry.

## Open questions resolved

- **Q1 from spec.md:** Live vs. sandbox PayPal for demo → **Sandbox for development and judge mode; live for the team's own demo run (decision deferred to T-I8).**
- **Authorization validity:** 29 days — Habitat must implement expiry tracking.
