# Habitat delivery project

## Objective

Build the hosted Habitat MVP using the CTX GitLab Duo workflow. Demonstrate one
coherent issue-to-release change with verified nine-stage evidence, supervised
human outcome approval and no real-payment/ad side effects in development tests.

## Current state

Planning has run successfully through GitLab Duo with `/flow:ctx-planning`, as
confirmed by the user. This is not an outstanding registration/execution blocker.
The revised planning/development/delivery definitions, 30 shared repo skills,
AC validator and browser CI harness are local changes awaiting publication and
live validation. Application/deployment adapters remain unconfigured; no end-to-end
release or nine-stage completion is claimed. Existing remote plans must be reconciled
on resume rather than recreated. Add the planning session URL when available.

## Active work

| Epic | Issue | Branch | State |
|---|---|---|---|
| E11: AICL MVP — Configurable AI Control Layer | #11 | ctx/epic-i11 | planning; Design pending |

The earlier E2/PayPal foundation is retained as historical scope and evidence. It is superseded for MVP planning by E11; no prior issue is closed or deleted.

## Ticket backlog

| Ticket | Issue | Wave | State |
|---|---|---|---|
| T-I3: Feasibility spikes | #3 | 1 | pending |
| T-I4: Trust core | #4 | 2 | pending |
| T-I5: Tool interface and onboarding | #5 | 3 | pending |
| T-I6: Marketing agent and action broker | #6 | 4 | pending |
| T-I7: Funding and control panel | #7 | 4 | pending |
| T-I8: Demo and submission | #8 | 5 | pending |

## Ready next work

1. Review/publish this revision; update the existing planning catalog version and
   enable development/delivery. Validate the new versions in Duo.
2. Resolve Duo access/credits and runner availability for live flow execution.
3. Configure protected branches and mandatory CI checks.
4. Reconcile the existing epic/tickets and stable numbering. Develop the foundation
   ticket with the minimum tests, real app/CI commands and browser startup contract.
5. Run `ctx-epic-design issue=2` to write technical design and reconcile tickets.
6. Run `ctx-ticket-design issue=3` to start T-I3 (feasibility spikes, Wave 1).
7. Run current-SHA AC validation and separate ticket/epic review. Enable required
   application checks before implementation merges; then connect delivery adapters.

## Blockers and decisions

- GitLab Duo access/credits: resolve before live flow execution.
- The app, test startup, Playwright tests and application command adapters are missing.
- Protected branches and mandatory CI checks: must be configured before implementation MRs merge.
- Hosting/configuration/secrets adapters: not implemented; no deployment permitted yet.
- Public repository/MIT license and hackathon submission: T-I8 scope.
- Reddit Ads API access: may require separate approval; T-I3 spike resolves.
- PayPal authorize-and-capture behavior: must be confirmed for account type; T-I3 spike resolves.
- Open decisions: live vs. sandbox PayPal for demo, model provider, cloud browser, per-owner isolation, Habitat margin.

## Durable handoff

Source issue: #10  
Epic issue: #2 (EPIC-I2)  
Epic branch: ctx/epic-i2  
Spec: docs/design/habitat-foundation/spec.md  
Epic plan: docs/plan/EPIC-I2/_epic.md  
State: docs/plan/EPIC-I2/state.json  
Source SHA: 4198664fc2bc917ee722146553b27fa41f0918c9  
Next operation: ctx-epic-design issue=2
