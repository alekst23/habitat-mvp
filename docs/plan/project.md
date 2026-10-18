# Habitat delivery project

## Objective

Build the hosted Habitat MVP using the CTX GitLab Duo workflow. Demonstrate one
coherent issue-to-release change with verified nine-stage evidence, supervised
human outcome approval and no real-payment/ad side effects in development tests.

## Current state

E11 now has an implemented AICL application: control/budget primitives, canonical
creation, fake-backed connections and work authorization, magic-link sign-in,
wizard/chat creation and owner management pages. E11-1 through E11-4 are integrated
into `ctx/epic-i11`. E11-5 is implemented, repaired and independently reviewed at
`55b8c8ea`; MR !76 still needs integration in this snapshot. Whole-epic verification,
review and closure remain pending. [Completion evidence](E11/completion.md) records
candidate identities and distinguishes passing ticket checks from epic acceptance.

## Active work

| Epic | Issue | Branch | State |
|---|---|---|---|
| E11: AICL MVP — Configurable AI Control Layer | #11 | ctx/epic-i11 | implemented candidate; integration and epic acceptance pending |

The earlier E2/PayPal foundation is retained as historical scope and evidence. It is
superseded for MVP planning by E11; this documentation update closes no prior issue.

## Ticket backlog

| Ticket | Issue | Wave | State |
|---|---|---|---|
| E11-1: AICL domain and control foundation | #12 | 1 | code integrated |
| E11-2: Canonical creation service and web-app tools | #13 | 2 | code integrated |
| E11-3: Authenticated workspace and agent-creation wizard | #14 | 3 | code integrated |
| E11-4: Built-in chat agent creation surface | #15 | 3 | code integrated |
| E11-5: AICL web pages, instance management, and cross-surface proof | #16 | 4 | reviewed candidate; integration pending |

## Ready next work

1. Reconcile E11-5 integration and the saved Development checkpoint.
2. Complete the separately scoped source-security foundation under review, then
   reconcile docs and prepare whole-epic verification context.
3. Obtain fresh backend/browser/acceptance evidence and independent final epic
   review for the assembled candidate before reporting completion.

## Remaining boundaries

- The previous source-security adapter was unconfigured; passing ticket behavior
  checks did not make that mandatory job pass.
- Protected branches, required checks and review remain integration prerequisites.
- No public MCP API, payment/funding, external execution, real-provider enablement,
  autonomous runner or deployment is included in E11.
- Application checks now exist. No accepted deployment or nine-stage release is
  claimed. Historical workflow publication records are preserved in `docs/development/`.

## Durable handoff

- Source issue: #10
- Epic issue: #11 (E11)
- Epic branch: `ctx/epic-i11`
- Epic plan: [E11 scope](E11/_epic.md)
- State: [E11 state](E11/state.json)
- Next operation: reconcile E11-5 integration, then assembled-epic verification/review
