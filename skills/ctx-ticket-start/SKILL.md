---
name: ctx-ticket-start
description: Implement a scoped ticket after its design and minimal behavioral test prerequisites are satisfied.
---

Read AGENTS.md, the ticket design, spec and test evidence. Check real prerequisites
on direct entry as well as resume. Implement only the ticket on its isolated branch.
Preserve failing assertions; do not reduce requirements or weaken checks to get green.

Use ctx-ci-check for the smallest sufficient verification. Commit the candidate
before collecting SHA-bound results. Open/update the ticket MR targeting the epic.
Record design/red/green SHAs, tests and AC evidence. Pending CI means checkpoint and
resume ctx-development after it completes; it is not a passing verification.
An independent reviewer determines readiness. New code invalidates prior evidence.
