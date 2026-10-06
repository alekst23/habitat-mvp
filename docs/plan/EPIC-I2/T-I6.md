# T-I6: Marketing agent and action broker — agent loop, broker, connectors, approvals, hard stops

Project ID: 87271414  
Source issue: #1  
Epic: EPIC-I2 (#2)  
Ticket issue: #6  
Branch: `ctx/ticket-i6`  
MR: (to be created)  
Status: pending

## Acceptance criteria

See issue #6.

## Dependencies

T-I5 (#5): tool interface and onboarding operational.

## Design

Spec: `docs/design/habitat-foundation/spec.md` scenarios F5, F6.

Marketing agent: Python or Node.js on Render. Action broker: separate service, DB conditional updates. Reddit Ads connector: API or browser recipe per T-I3. Kill switch: owner tool → broker → platform API.

Design SHA: (to be set after ctx-ticket-design)

## Tests before implementation

Scenarios: F5-S1 through F5-S5, F6-S1 through F6-S2. Red-test SHA: (pending).

## Implementation and verification

(pending)

## Independent ticket review

(pending)

## Closure

(pending) — Unblocks T-I8.
