# Habitat delivery project

## Objective

Build the hosted Habitat MVP using the CTX GitLab Duo workflow. Demonstrate one
coherent issue-to-release change with verified nine-stage evidence, supervised
human outcome approval and no real-payment/ad side effects in development tests.

## Current state

E11 implements the AICL application: control/budget primitives, canonical creation,
fake-backed connections and work authorization, magic-link sign-in, wizard/chat
creation and owner management pages. All five implementations are integrated into
`ctx/epic-i11`. The E11-5 candidate `5960066639a243e617c17b42630655a7135045fc` passed every mandatory CI job and
independent review; application, browser and E11-5 acceptance checks also passed
at its actual integration SHA.
[Completion evidence](E11/completion.md) distinguishes historical integration,
current ticket evidence and the separate final whole-epic gate.

## Active work

| Epic | Issue | Branch | State |
|---|---|---|---|
| E11: AICL MVP — Configurable AI Control Layer | #11 | ctx/epic-i11 | all implementations integrated; final whole-epic verification/review pending |

The earlier E2/PayPal foundation remains historical scope and evidence. E11
supersedes it for MVP planning; this record closes no prior issue.

## Ticket backlog

| Ticket | Issue | Wave | State |
|---|---|---|---|
| E11-1: AICL domain and control foundation | #12 | 1 | integrated; historical receipts reconciled |
| E11-2: Canonical creation service and web-app tools | #13 | 2 | integrated; historical receipts reconciled |
| E11-3: Authenticated workspace and agent-creation wizard | #14 | 3 | integrated; historical receipts reconciled |
| E11-4: Built-in chat agent creation surface | #15 | 3 | integrated; historical receipts reconciled |
| E11-5: AICL web pages, instance management, and cross-surface proof | #16 | 4 | integrated; post-integration application checks passed |

## Ready next work

1. Commit reconciled epic documentation with acceptance scope `E11` after the
   current default-branch workflow history has been merged into the epic.
2. Obtain fresh whole-epic CI and independent review at that final SHA, recording
   the evidence on [MR !45](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/45). Keep it draft/open for the
   separate default-branch approval and merge decision.

## Remaining boundaries

- The historical unconfigured-security failures remain recorded. Current source,
  container and configuration-validation adapters passed the reviewed ticket CI;
  the assembled epic still requires its own final-SHA checks.
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
- Final verification/review location: [MR !45](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/45)
- Next operation: final whole-epic verification and independent review
- Default-branch merge and deployment: not performed
