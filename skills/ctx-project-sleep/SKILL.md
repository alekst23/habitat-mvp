---
name: ctx-project-sleep
description: Save development progress, verified evidence and precise resume instructions across flow sessions.
---

Role boundary: the persistence/journal/helper instructions below are for the native
runner. CTX Project chat reads the full checkpoint but never rewrites it or commits
checkpoint-only files to move the reviewed SHA. For the activated v1.5.0 session
tools, use docs/development/project-session-handoff.md's compact request/receipt
notes pointing to the original native state. Save actual session identity, result
links and next action; return a check-progress re-entry without asking the user to
copy commands/results. Status-only writes nothing; no unattended chat auto-wake.

Reconcile completed, partial, in-flight and blocked work against GitLab. Save branch
and candidate SHAs, evidence links, unresolved decisions and the next operation in
the project/epic state and source issue. Commit state on the authorized epic branch.

Persist the pinned request, full progress journal (including active/uncertain claims),
receipts and owned-resource manifest in verified source-issue notes or committed run
documents on the authorized branch. The runner's .ctx directory is ephemeral, not
a durable checkpoint. Read back the saved body/identity/links. In a healthy native
session this is an intermediate save, NOT a final response: reassess and continue.

For a single-epic native run use the trusted ctx_checkpoint.py file-to-note publisher
and docs/development/checkpoint-publication.md; ctx_owner.py remains the codec for the
ctx-owner-handoff:v1 contract in single-shot-development.md. It wraps the full
existing closure/journal, objective/authorization, session counter, answers and
resource/receipt history; never substitute a prose summary. Read back and compare
the complete parsed payload AND exact saved body. Do not retype generated JSON through
the model, truncate history, delete invalid notes, use personal credentials or bypass
the readback gate. The helper's fixed service-account OAuth transport never exposes
credentials to the model and never dispatches work. Unknown writes are reconciled,
not blindly retried. The next run discovers this on the source issue from
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
