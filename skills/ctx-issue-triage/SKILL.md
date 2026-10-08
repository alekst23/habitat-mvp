---
name: ctx-issue-triage
description: Investigate a GitLab issue and resolve its intended behavior before planning implementation.
---

Read the source issue, relevant implementation and existing feature spec. Determine
what already works, the smallest required change, dependencies and missing intent.
Resolve scope questions in Planning; leave detailed behavior/solution questions for
Design's ctx-spec-interview after the scope/tickets are saved. Preserve user answers;
do not repeat an interview already resolved in the issue.

Persist scope, decisions, open design questions and existing spec links on the issue. Infrastructure that does
not exist is an explicit prerequisite. Return ready only when the intended behavior
is sufficiently defined to decompose; a complete specification is not required yet.
Otherwise save the question and stop. In Duo Chat ask and wait, using normal prose
instead of an ambient routing token.
