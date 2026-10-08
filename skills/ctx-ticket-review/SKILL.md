---
name: ctx-ticket-review
description: Independently validate a ticket's acceptance criteria, scope and code quality against current execution evidence.
---

Read the ticket, feature spec, complete changed files and candidate MR diff. Use
read/comment tools only; send fixes to the builder. Verify actual GitLab jobs and
the acceptance report at the reviewed SHA, not the builder's claim of success.

Apply these review perspectives; they are checks, not a requirement for six agents:

- AC and intent: trace every ticket AC to code and runtime/inspection evidence,
  account for applicable spec scenarios, dependencies, non-goals and scope creep.
- Architecture: contracts, dependency direction and project-specific boundaries.
- Correctness: real edge cases, state transitions, error handling and concurrency.
- Tests: meaningful assertions and the minimum sufficient coverage. Existing tests
  count; do not request test-per-function quotas, redundant layers or speculative cases.
- Security/performance: tenant scope, secrets, reservation/idempotency and bounded work.
- Conventions: material maintainability issues in changed code, without style churn.

Emit an AC-by-AC matrix: ID, passed/partial/missing/blocked, code reference, test or
inspection reference, browser evidence where required, and checked SHA. A single
test may support several ACs. An inspected implementation cannot substitute for
required runtime behavior. No UI evidence is acceptable only for non-UI criteria.

Block for missing/failed/stale acceptance evidence or unresolved material findings.
Record ready, needs changes or needs decision with precise evidence. This verdict
is not GitLab MR approval, ticket integration or release authorization.

For version-2 Development bind verification_url to the saved current-SHA verification
report. Classify actionable scoped code/test/AC findings as blocker_kind=defect with
unique finding IDs, in-scope ac_ids, summary and actual evidence_url per the single-shot
protocol. The supervisor sends them to implementation and returns here after fresh
checks. Confirm prior findings are really resolved; do not carry an old review forward.
Missing evidence/permissions/intent is a genuine blocker, not automatic repair authority.

## Final routing response

Terminal tokens: [ready, blocked]

Publish the review verdict, AC matrix, findings and integration/repair handoff as
an operation-report note on the source issue/work item. Read that saved note back
by ID and verify its identity, body, checked SHA and evidence links; retain its
ID/URL in the durable handoff. Failed publication or readback requires `blocked`.
If the review passes with current complete evidence and no blocking findings,
the ENTIRE final response must be `ready`.
For missing evidence, changes or a decision, the ENTIRE final response is `blocked`.
No Markdown, explanations, verdict prefix or handoff text belongs in that response.
Never emit `integrate`: it names the next component, not this review's result.
The supervisor consumes `ready` plus the verified current-SHA report before
delegating integration; the reviewer does not perform it. The retained historical
single-ticket flow uses its router for the equivalent handoff.
The deterministic consumer may recover a valid last-line token from accidental
preceding prose. That compatibility behavior does not relax this producer contract
or permit conflicting signals or `integrate` as a review result.
