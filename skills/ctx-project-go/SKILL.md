---
name: ctx-project-go
description: Reconcile durable project state and select authorized ready work for a development run.
---

Compare docs/plan/project.md with actual issues, branches, MRs, jobs and active
sessions. Preserve other work and unresolved decisions. Select a ready ticket only
within the requested epic/focus; missing intent goes to planning. Use ctx-epic-run
for dependency reconciliation. A default run never silently authorizes the backlog.

Persist the source issue, selected ticket, branch and resume point for downstream
components. Do not claim dispatch without an actual session. Each run is bounded;
checkpoint with ctx-project-sleep when waiting for CI, a decision or another run.
