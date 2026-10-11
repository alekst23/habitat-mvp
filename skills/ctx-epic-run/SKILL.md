---
name: ctx-epic-run
description: Advance all authorized remaining epic tickets through dependency-aware SDLC phases and consolidation.
---

Read state.json, current issues/MRs, session notes and branch/CI state. Resolve actual
issue mappings and run scripts/ctx_workflow.py waves. Done dependencies require
real ancestry, review and integration evidence. Preserve blocked and in-flight work.

Preflight committed specs, per-ticket Design and acceptance manifests. Missing
design questions block affected work; missing test stubs route to ctx-ticket-tests
inside this invocation. Confirm actual remote ownership before dispatch. The local
wave helper/journal is not a distributed lease; never take over another live run.

Use the bounded supervisor and progress journal described in
docs/development/single-shot-development.md and durable-execution.md. Compute all independent ready work,
delegate design preflight/tests/implementation/verification/review/integration, then
reassess until scoped work is complete or a real blocker/budget requires checkpoint.
The current native runtime uses an explicit serial fallback; do not claim parallel
workers. Keep each ticket in its own verified worktree/branch and prevent workers
from writing shared project state. A failed setup must never fall back to main.

Publish/read back the claim before dispatch and the receipt after each delegation.
Only independently verified integration unlocks dependents. A blocked ticket does
not abort unrelated ready work. After closure, continue to the next ready ticket
in the next controller slice; integrate.more is not epic completion. When all tickets are integrated,
delegate ctx-epic-docs, obtain fresh epic-SHA checks, ctx-epic-review and ctx-epic-close.
Do not merge to default, dispatch another flow, invent evidence or expand scope.

Each session delegates at most ONE unit and checkpoints. The durable controller
continues the same authorized epic without a human phase-by-phase restart. The
journal allows at most 60 cumulative actions across sessions, and
one reconciled transient/CI-wait retry per target. Never repeat uncertain writes
or hide a partial result as completion. Preserve dirty/unmerged/foreign resources;
cleanup only clean, integrated, inactive entries in this run's ownership manifest.

Version-2 journals additionally allow three evidenced defect repairs per target.
Use the existing browser component for verify (all ACs, including backend tests).
After a repair, require new-SHA checks and independent review. Once assembled, the
epic gets docs, full-epic verification and review; scoped integration defects return
to the builder on the owned epic branch and through those gates again. Never reopen
completed ticket history, widen scope or reset limits. See the single-shot protocol.

technical_design findings route through a bounded document addendum and an independent
design_review before tests/implementation and fresh verification. Answered decision
blockers use resume-decision only after scoped artifact save/readback; the request
and manifest stay pinned. Both transitions share the existing repair/action budgets.
Cross-target contract effects or changed ACs require an explicit revision plan.
