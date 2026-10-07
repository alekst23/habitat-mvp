---
name: ctx-branch-agent
description: Execute one selected ticket in an isolated branch while preserving its epic and other work.
---

Read the selected ticket's actual issue mapping and dependencies. Use a dedicated
checkout of ctx/ticket-i<ticket-issue-iid>, based on the reconciled epic. Never
reuse another session's dirty checkout or write the default branch.

Follow ctx-ticket-start and its design/test prerequisites. Report complete, partial
or blocked with branch, candidate SHA and evidence. Isolation does not grant merge
or deployment authority. Integrate only through the development coordinator.
