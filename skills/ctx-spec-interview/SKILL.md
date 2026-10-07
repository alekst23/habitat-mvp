---
name: ctx-spec-interview
description: Resolve missing product intent and maintain a behavioral specification with stable acceptance scenarios.
---

Read the issue and existing spec before asking anything. Resolve who benefits,
observable success, preconditions, relevant failure behavior and non-goals. Ask
only questions whose answers change behavior, scope or authority; persist them on
the issue and checkpoint rather than waiting in an interactive terminal.

Write docs/design/<feature>/spec.md with stable Given/When/Then scenario IDs.
Keep implementation details in technical.md when needed. Reuse equivalent scenarios
and existing coverage; do not expand the test matrix with speculative permutations.
Commit the spec on the actual epic branch and link the issue and plan.
