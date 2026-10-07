# E2-1 Feasibility Spike Findings

**Ticket:** E2-1 (issue #3)  
**Epic:** E2 (issue #2)  
**Branch:** `ctx/ticket-i3`  
**Status:** Complete — findings committed, go/no-go decisions recorded.

## Spike documents

| Document | Topic | Decision |
|---|---|---|
| [reddit-ads-api.md](reddit-ads-api.md) | Reddit Ads API access, OAuth scopes, campaign/budget API | ⚠️ Conditional GO — browser recipe is primary path |
| [paypal-authorize-capture.md](paypal-authorize-capture.md) | PayPal authorize-and-capture, partial captures, sandbox | ✅ GO — Orders API v2, standard account sufficient |
| [render-api.md](render-api.md) | Render API, background workers, Blueprint, isolation | ✅ GO — per-owner workers via API, Blueprint for platform |
| [cloud-browser.md](cloud-browser.md) | Hosted browser, Playwright, stored sessions, cost | ✅ GO — Browserbase recommended |

## Key decisions

1. **Reddit Ads:** Browser recipe (Playwright + Browserbase) is the primary connector path. Submit API access request in parallel; use API if approved before T-I6.
2. **PayPal:** Use Orders API v2 with `intent: AUTHORIZE`. Partial/multiple captures confirmed. 29-day authorization window — Habitat must track expiry. Sandbox matches production.
3. **Render:** Background workers for per-owner agents, provisioned via Render API by the provisioning-proxy. Platform services via Blueprint (`render.yaml`).
4. **Cloud browser:** Browserbase (primary). Free tier sufficient for development. Stored sessions via Browserbase session IDs, stored in secrets-service.

## Open questions resolved by this spike

- Q3 (cloud browser): Browserbase
- Q4 (Render isolation): One background worker per owner, API-provisioned
- Q6 (Reddit Ads API vs. browser recipe): Browser recipe is primary

## Open questions NOT resolved (deferred)

- Q1 (live vs. sandbox PayPal for demo): Deferred to T-I8
- Q2 (model provider and data-retention): Must be decided before T-I4 begins
- Q5 (Habitat margin in price tables): Must be decided before T-I4 ledger implementation

## Unblocks

This spike unblocks E2-2 (Trust core, issue #4). The decisions above are inputs to T-I4's ledger and secrets design.
