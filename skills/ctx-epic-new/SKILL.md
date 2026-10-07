---
name: ctx-epic-new
description: Create or reconcile a GitLab-backed epic and its durable plan without duplicating existing work.
---

Read AGENTS.md and docs/development/ctx-contract.md. Resolve or create the actual
parent epic issue after deduplication; an ordinary GitLab issue is sufficient.
Use E<epic-issue-iid>, docs/plan/E<iid>/ and ctx/epic-i<iid>. Record the separate
intake issue. Never predict GitLab's next issue number.

Use the epic/state templates. Decompose only the resolved specification, including
necessary infrastructure and integration work. Use ctx-ticket-new for allocations.
Open/update a draft epic MR for visibility. This is not permission to merge or deploy.
