# Habitat Foundation

## Intent and observable success

Habitat lets a small business owner set up a trustworthy AI agent that does real marketing work for them, within a budget they control. The owner describes what they want in plain language. Habitat's onboarding agent configures the account and the working agent while the page updates in front of them.

**Observable success:** A new owner visits the site, completes onboarding through conversation alone, connects Reddit Ads, authorizes a USD budget via PayPal, watches the marketing agent propose and execute a paid campaign, sees live costs by category, and can stop everything with a single action. Judges can replicate this with sandbox funding.

## Preconditions

- Secrets service with KMS-backed envelope encryption (unbuilt)
- Inference proxy with USD metering and reservation (unbuilt)
- Ledger with integer micro-dollar accounting and reservations (unbuilt)
- Append-only activity log with hash chain (unbuilt)
- Tool interface with authentication and state-change events (unbuilt)
- Action broker with state machine and approval flow (unbuilt)
- PayPal proxy with authorize-and-capture and webhook verification (unbuilt)
- Reddit Ads connector (API or browser recipe, per T-I3 findings) (unbuilt)
- Render deployment for platform services and per-owner agent resources (unbuilt)
- AG Grid control panel (unbuilt)
- Global operator-level cost caps independent of owner funding (unbuilt)

## Features and scenarios

### F1: Onboarding

**F1-S1:** Given a new visitor, when they start a conversation with the onboarding agent, then the agent asks about their business and goal, creates the account, marketing agent, and plan through the tool interface, and the page renders each change as it happens.

**F1-S2:** Given an owner in onboarding, when the agent proposes a budget split and approval rules, then the owner can adjust and authorize funding through PayPal before the agent proceeds.

**F1-S3:** Given an owner connecting Reddit Ads, when they complete the OAuth flow, then Habitat stores the token encrypted and records the granted scopes; the agent never sees the token.

**F1-S4:** Given a completed onboarding, when the owner views the control panel, then they see the marketing agent status as running.

### F2: Trust and authorization

**F2-S1:** Given any agent tool call, when the call arrives at the tool interface, then the tenant is derived from authentication, never from the call arguments.

**F2-S2:** Given an agent attempting to call an owner-only tool (budget, policy, approvals), when the call arrives, then it is denied with an authorization error.

**F2-S3:** Given an agent attempting to approve its own action, when the approval call arrives, then it is denied.

**F2-S4:** Given an unknown tool name, when the call arrives, then it is denied.

**F2-S5:** Given two concurrent approval attempts for the same action, when both arrive simultaneously, then exactly one succeeds and the other is rejected.

### F3: Budget and ledger

**F3-S1:** Given a billable model call, when the inference proxy receives it, then it reserves the maximum USD cost before dispatching; if the budget is insufficient, the call is denied.

**F3-S2:** Given an unknown model price, when the inference proxy receives a call for that model, then the call is blocked.

**F3-S3:** Given a budget of zero, when any spend attempt arrives, then it is denied.

**F3-S4:** Given every iteration of an agent loop, when the loop runs, then a ledger entry is created for each iteration.

**F3-S5:** Given a completed model call, when the response arrives, then the ledger settles the actual cost and releases the unused reservation.

### F4: Secrets and encryption

**F4-S1:** Given a connection secret, when it is stored, then it is encrypted with AES-256-GCM using a per-connection data key wrapped by a KMS master key; the encryption context binds tenant, connection, and field.

**F4-S2:** Given a ciphertext from one tenant's connection, when it is placed in another tenant's record and decrypted, then decryption fails.

**F4-S3:** Given a revoked connection, when a subsequent decrypt is attempted, then it fails even if a cached key was previously valid.

**F4-S4:** Given any agent context, when a model call is made, then no secret, token, or credential appears in the prompt, response, or log.

### F5: Action broker and approvals

**F5-S1:** Given a proposed action, when it arrives at the broker, then it follows the state machine: proposed → policy checked → budget reserved → pending approval (if required) → executing → succeeded/failed/rejected/expired.

**F5-S2:** Given an action requiring approval, when the owner approves it, then the broker verifies the payload hash matches the approved payload before executing.

**F5-S3:** Given an approved action whose payload is altered after approval, when execution is attempted, then it is rejected.

**F5-S4:** Given an action in executing state after a service restart, when the broker recovers, then it reconciles against the platform using the idempotency key, never retries blindly.

**F5-S5:** Given a campaign creation action, when it executes, then the platform-side lifetime budget is set equal to the reservation amount.

### F6: Hard stops

**F6-S1:** Given the owner activates the kill switch, when it is processed, then the agent is paused, every live campaign is paused through the platform API, and new reservations are blocked.

**F6-S2:** Given an action that would exceed the remaining spending allocation, when the broker receives it, then it is refused.

### F7: PayPal funding

**F7-S1:** Given an owner authorizing a USD budget, when they complete the PayPal flow, then Habitat creates an order with authorize intent and credits the ledger only after re-fetching the authorization from PayPal.

**F7-S2:** Given a duplicate PayPal webhook event, when it arrives, then the uniqueness constraint on the event ID prevents double-crediting.

**F7-S3:** Given a PayPal webhook with an invalid signature, when it arrives, then it is rejected and the ledger is not updated.

**F7-S4:** Given a missing PayPal webhook configuration, when the service starts, then startup fails.

**F7-S5:** Given sandbox funding, when it is credited, then the real operator-level cost cap is not raised.

### F8: Control panel

**F8-S1:** Given the owner views the control panel, then they see costs by category and run, the activity log with evidence, pending approvals, live campaigns, and results.

**F8-S2:** Given a new ledger entry, when it is written, then the control panel reflects it without a page reload.

**F8-S3:** Given the owner exports the activity log, then the export includes every action, data read, secret use, cost, and approval, and the hash chain verifies.

### F9: Judge mode

**F9-S1:** Given a judge invite code, when a judge signs up, then they get an account with PayPal Sandbox funding, real inference within a global cap, and spending actions executed as drafts or paused campaigns.

**F9-S2:** Given a judge account, when a spending action is approved, then it is executed as a draft or paused campaign, not live spend.

## Edge cases and failure behavior

- Any error, timeout, missing configuration, unknown price, unknown action type, missing handler, or invalid session denies the request (fail closed).
- An action found in executing after a restart is reconciled, never advanced blindly.
- A timeout with an unknown outcome keeps its reservation until reconciliation.
- Payment events that cannot be attributed to an owner are held for review, not retried indefinitely.
- Revoking a connection does not undo charges already incurred; the UI states this.
- Disconnecting revokes the token at the provider and deletes the stored secret.

## Non-goals

- Bring-your-own-agent packaging
- Local Habitat
- Additional marketing channels beyond Reddit Ads (first channel)
- Multiple agents per owner
- Team accounts
- Customer personal data (email lists, user records)
- Customer-managed keys
- Confidential hosting
- Autonomous funding without owner authorization
- Agent spawning
- Provider marketplace

## Open questions

1. **Live vs. sandbox PayPal for the team's own demo run** — must be decided before T-I8 begins; state clearly in the video.
2. **Model provider and data-retention settings** — must be decided before T-I4 begins; affects data-flow disclosure.
3. **Cloud browser service selection** — resolved by T-I3 spike.
4. **Per-owner isolation layout on Render** — resolved after first end-to-end path works (T-I5).
5. **Habitat margin in price tables** — must be decided before T-I4 ledger implementation.
6. **Reddit Ads API access** — resolved by T-I3 spike; browser recipe is fallback.

## Implemented by

Epic: #2 (EPIC-I2)  
Tickets: #3 (T-I3), #4 (T-I4), #5 (T-I5), #6 (T-I6), #7 (T-I7), #8 (T-I8)  
Source issue: #1  
This spec outlives the epic.
