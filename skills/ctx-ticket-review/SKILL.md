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

## Bounded retrieval and interrupted reviews

Start from the exact candidate SHA, changed-path list and verification report.
Fetch complete changed files at that SHA, once per path; use the installed
repository-file or read-only GitLab API tool with an explicit ref. Repository
search is discovery, not a substitute for file contents. Cache successful reads
within this review. Do not repeatedly fetch an unchanged MR diff or issue the
same unsuccessful search. After one corrected request, use a supported exact-file
read; if that also fails, save the concrete missing path/tool error and return
blocked for evidence/access. Never infer missing source from search snippets.

Before the supplied `save_by`, publish/read back a partial review note with claim,
candidate SHA, verification URL, checked files/ACs, findings and exact remaining
checks. Partial notes are progress evidence, never approval or a final verdict.
On recovery, inspect saved partial notes and validate their SHA/provenance, then
finish the remaining checks and reconsider all findings before publishing the
complete independent review. A platform interruption is not a code defect, and
neither a successful runner job nor a partial matrix proves the review passed.

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
