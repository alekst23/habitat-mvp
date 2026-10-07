# EPIC-I2: Habitat MVP — First Runnable Foundation

Project ID: 87271414  
Source issue: #10  
Epic issue: #2  
Feature spec: `docs/design/habitat-foundation/spec.md`  
Epic branch: `ctx/epic-i2`  
Draft MR: (to be created after first ticket integrates)

## Outcome and scope

Deliver the Habitat MVP as described in `docs/habitat-mvp.md`: a hosted marketing-agent application where a small business owner can configure a trustworthy AI agent through conversation, authorize a USD budget via PayPal, and watch the agent perform real marketing actions within explicit authorization and hard limits.

The foundation milestone covers everything needed before the budget-denial demonstration is runnable end-to-end.

## Tickets and dependencies

| Ticket issue | Title | Dependencies | State | Evidence |
|---|---|---|---|---|
| T-I3 (#3) | Feasibility spikes | — | pending | |
| T-I4 (#4) | Trust core | T-I3 | pending | |
| T-I5 (#5) | Tool interface and onboarding | T-I4 | pending | |
| T-I6 (#6) | Marketing agent and action broker | T-I5 | pending | |
| T-I7 (#7) | Funding and control panel | T-I5 | pending | |
| T-I8 (#8) | Demo and submission | T-I6, T-I7 | pending | |

## Integration and wiring

All services communicate through the tool interface. Agents reach only the tool interface and proxies. Only proxies call the secrets service. The ledger is append-only. Tenant identity is derived from authentication at every boundary.

Service boundaries:
- `secrets-service`: envelope encryption, KMS, cache, revocation
- `inference-proxy`: model calls, USD metering, reservation
- `ledger-service`: reservations, settlements, price tables
- `tool-interface`: all tool groups, state events, auth
- `action-broker`: state machine, approvals, connectors, reconciliation
- `paypal-proxy`: authorize/capture, webhook verification
- `web-research-proxy`: no-credential browsing
- `data-proxy`: scoped read connectors, purpose tags
- `provisioning-proxy`: Render API, resource caps
- `habitat-site`: onboarding UI, control panel, SSE/WebSocket
- `onboarding-agent`: Render service or Workflow task
- `marketing-agent`: Render background worker or Workflow task

## Waves

Wave 1 (independent): T-I3  
Wave 2: T-I4  
Wave 3: T-I5  
Wave 4 (parallel): T-I6, T-I7  
Wave 5: T-I8

## Whole-epic review and merge readiness

Required before epic MR to main:
- All tickets closed with passing tests and independent review
- All MVP acceptance criteria from `docs/habitat-mvp.md` verified with evidence
- Secret scan of repository and history clean
- CI green on epic branch
- Conceptual/integration review of cross-service wiring
- Documentation: README, setup instructions, judge account guide
- Merge order: ticket branches → epic branch → main (via reviewed MR)

## Decisions, blockers and handoff

**Blockers:**
- Reddit Ads API access approval (T-I3 spike)
- PayPal authorize-and-capture behavior confirmation (T-I3 spike)
- Duo access/credits and runner availability for live flow execution
- Protected branch and mandatory CI check configuration

**Open decisions (see spec.md open questions):**
1. Live vs. sandbox PayPal for demo run
2. Model provider and data-retention settings
3. Cloud browser service
4. Per-owner isolation on Render
5. Habitat margin
6. Reddit Ads API vs. browser recipe

**Next operation:** `ctx-epic-design issue=2` to write technical design, then `ctx-ticket-design issue=3` to start T-I3 (feasibility spikes).
