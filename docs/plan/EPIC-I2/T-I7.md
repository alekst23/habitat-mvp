# T-I7: Funding and control panel — PayPal auth/capture, AG Grid dashboard, judge mode

Project ID: 87271414  
Source issue: #1  
Epic: EPIC-I2 (#2)  
Ticket issue: #7  
Branch: `ctx/ticket-i7`  
MR: (to be created)  
Status: pending

## Acceptance criteria

See issue #7.

## Dependencies

T-I5 (#5): tool interface and activity log operational.  
T-I3 (#3): PayPal authorize-and-capture behavior confirmed.

## Design

Spec: `docs/design/habitat-foundation/spec.md` scenarios F7, F8, F9.

PayPal proxy: separate service, authorize intent + metered captures, webhook verification. AG Grid control panel: React SPA, evaluate AG Studio. Judge mode: invite codes, sandbox funding, draft execution.

Design SHA: (to be set after ctx-ticket-design)

## Tests before implementation

Scenarios: F7-S1 through F7-S5, F8-S1 through F8-S3, F9-S1 through F9-S2. Red-test SHA: (pending).

## Implementation and verification

(pending)

## Independent ticket review

(pending)

## Closure

(pending) — Unblocks T-I8.
