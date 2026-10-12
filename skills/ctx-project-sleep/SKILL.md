---
name: ctx-project-sleep
description: Save development progress, verified evidence and precise resume instructions across flow sessions.
---

Reconcile completed, partial, in-flight and blocked work against GitLab. Save branch
and candidate SHAs, evidence links, unresolved decisions and the next operation in
the project/epic state and source issue. Commit state on the authorized epic branch.

Persist the pinned request, full progress journal (including active/uncertain claims),
receipts and owned-resource manifest in verified source-issue notes or committed run
documents on the authorized branch. The runner's .ctx directory is ephemeral, not
a durable checkpoint. Read back the saved body/identity/links. In a healthy native
session this is an intermediate save, NOT a final response: reassess and continue.

For a single-epic native run use ctx_owner.py render/parse and the
ctx-owner-handoff:v1 contract in single-shot-development.md. It wraps the full
existing closure/journal, objective/authorization, session counter, answers and
resource/receipt history; never substitute a prose summary. Read back and compare
the complete parsed payload. The next run discovers this on the source issue from
"Continue E2". Keep machine references in the handoff, not a long user command.
Legacy checkpoints require reconciliation and lossless migration, never reset.
New notes use visible CTX_OWNER_HANDOFF_V1_BEGIN and CTX_OWNER_HANDOFF_V1_END
lines from the renderer, not HTML comments. Marker-stripped legacy notes need the
guide's explicit verified-note migration, then a new complete read-verified note.
Do not repair transport by committing checkpoint-only files that move the design SHA.

Do not mark pending work complete or lose earlier failure evidence. Give the same
ctx-development entry point, actual source/epic IIDs, exact refs and saved journal
needed to resume. Follow durable-execution.md for a controller-envelope run: publish
one final structured checkpoint with continue/complete/needs_decision/needs_access/
blocked, full closure/journal, source identity, observed HEAD and prior checkpoint hash.
The external controller, not this skill, starts the next native slice. No routine
human phase prompts. Native runs follow single-shot-development.md: preserve full
closure/journal and session budget receipts, continue within this session, and give
one human resume action only at a real stop. Do not claim cross-session auto-resume. Keep
dirty, unmerged, active and foreign worktrees. No force or glob cleanup.

Keep the approved objective through every stage boundary; a checkpoint is progress,
not a request for the user to select another agent. Retain pending answers until
artifact save/readback and independent review. Controlled decision application
adds decision_applications receipts; the controller verifies actual changed paths
and file readback before acknowledging them. Never relabel a terminal failed worker
as running merely because an old reservation remains; save its recovery evidence.
