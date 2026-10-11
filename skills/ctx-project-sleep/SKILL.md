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
a durable checkpoint. Read back the saved body/identity/links before returning.

Do not mark pending work complete or lose earlier failure evidence. Give the same
ctx-development entry point, actual source/epic IIDs, exact refs and saved journal
needed to resume. Follow durable-execution.md for a controller-envelope run: publish
one final structured checkpoint with continue/complete/needs_decision/needs_access/
blocked, full closure/journal, source identity, observed HEAD and prior checkpoint hash.
The external controller, not this skill, starts the next native slice. No routine
human continue prompts. Without the controller, do not claim auto-resume. Keep
dirty, unmerged, active and foreign worktrees. No force or glob cleanup.

Keep the approved objective through every stage boundary; a checkpoint is progress,
not a request for the user to select another agent. Retain pending answers until
artifact save/readback and independent review. Controlled decision application
adds decision_applications receipts; the controller verifies actual changed paths
and file readback before acknowledging them. Never relabel a terminal failed worker
as running merely because an old reservation remains; save its recovery evidence.
