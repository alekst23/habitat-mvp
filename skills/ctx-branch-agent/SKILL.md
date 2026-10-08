---
name: ctx-branch-agent
description: Execute one selected ticket in an isolated branch while preserving its epic and other work.
---

The ticket rules below apply to normal ticket work. For an explicitly delegated
version-2 assembled-epic repair, use ctx-project-fix and the coordinator's owned
non-default epic consolidation branch instead. Only that mode may commit/publish
the scoped repair on the epic branch; it still cannot merge to default, seize other
work or bypass fresh full-epic verification and independent review.

Read the selected ticket's actual issue mapping and dependencies. Use a dedicated
checkout of ctx/ticket-i<ticket-issue-iid>, based on the reconciled epic. Never
reuse another session's dirty checkout or write the default branch.

Use the coordinator's explicit worktree and branch on every command. Verify git
top-level/branch and stop hard on failed setup; never silently work in the primary
checkout. Preserve shared indexes/project state for coordinator consolidation.
Do not clean resources or push to the epic branch from the worker.

Follow ctx-ticket-start and its design/test prerequisites. Report complete, partial
or blocked with branch, candidate SHA and evidence. Isolation does not grant merge
or deployment authority. Integrate only through the development coordinator.
