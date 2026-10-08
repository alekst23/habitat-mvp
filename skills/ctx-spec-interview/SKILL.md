---
name: ctx-spec-interview
description: Resolve missing product intent and maintain a behavioral specification with stable acceptance scenarios.
---

Read the issue and existing spec before asking anything. Resolve who benefits,
observable success, preconditions, relevant failure behavior and non-goals. Ask
only questions whose answers change behavior, scope or authority. In CTX Design
chat, ask and wait for replies; save useful draft checkpoints on the epic branch
unless the user requested read-only work. In ambient execution, persist questions
on the issue and checkpoint rather than waiting in an interactive terminal.

Write docs/design/<feature>/spec.md with stable Given/When/Then scenario IDs.
Keep implementation details in technical.md when needed. Reuse equivalent scenarios
and existing coverage; do not expand the test matrix with speculative permutations.
CTX Design commits the spec on the actual epic branch, verifies full file readback
at the returned commit SHA and links the issue and plan. An issue note is a report,
not a substitute for saved spec files. Never send users to Planning/Development
merely to persist design. Open questions prevent readiness, not draft persistence.
