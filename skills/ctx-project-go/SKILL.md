---
name: ctx-project-go
description: Advance the explicitly scoped project work through the SDLC in one bounded supervisor session.
---

Preserve the original project-owner behavior: assess reality, execute available
approved work, consolidate and reassess within the same invocation. Read
docs/development/single-shot-development.md and scripts/ctx_development.py.

Compare docs/plan/project.md with actual issues, branches, MRs, jobs and active
sessions. Reuse settled decisions, respect in-flight work, and pin explicit epic or
project focus. Never silently authorize backlog or turn a ticket-only request into
an epic run. Missing scope belongs to Planning; missing design intent to Design.
They conduct interviews before execution. Development prepares minimal tests itself.

Use ctx-epic-run to enumerate the complete ready frontier. Delegate work to separate
SDLC components, keeping shared project state and consolidation in the coordinator.
Continue after ticket integration; process other ready work when one target blocks.
Do not end merely because the first ticket succeeded. Whole-epic docs/review/MR
preparation follow the tickets, retaining separate merge and release controls.

The original defaults to parallel workers; this native supervisor revision has an
explicit serial fallback because parallel delegation is unverified on the runtime.
Expose ready parallelism without claiming it ran concurrently. Do not use another
model runner or recursive flow starts as a hidden substitute.

Persist a fixed request, claims, receipts and owned-resource manifest. Use the
progress helper for ordering, current-SHA identity and action/retry bounds; verify
remote evidence independently. Its local lock is not an epic-wide distributed lease.
Checkpoint if exclusive epic coordination cannot be established. Update project
state in place on the authorized non-default branch, never directly on main.
Use ctx-project-sleep for a durable final/partial handoff, not after every ticket.
