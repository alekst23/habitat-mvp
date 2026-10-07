---
name: ctx-issue-triage
description: Investigate a GitLab issue and resolve its intended behavior before planning implementation.
---

Read the source issue, relevant implementation and existing feature spec. Determine
what already works, the smallest required change, dependencies and missing intent.
Use ctx-spec-interview for unanswered material questions. Preserve user answers;
do not repeat an interview already resolved in the issue.

Persist the scope, decision and spec links on the issue. Infrastructure that does
not exist is an explicit prerequisite. Return ready only when the intended behavior
is sufficiently defined to decompose; otherwise save the question and stop.
