---
name: ctx-project-go
description: Advance explicitly scoped work through a bounded native supervisor loop with durable checkpoints.
---

Preserve the original project-owner behavior: assess reality, execute available
approved work, consolidate and reassess within the same invocation. Read
docs/development/single-shot-development.md, docs/development/durable-execution.md
and scripts/ctx_development.py. Native execution is the default: delegate, verify,
save/read back progress, then reassess and continue in the SAME session. Controller
installation is optional, not an execution prerequisite. Only a verified controller
envelope selects its one-unit compatibility protocol. Preserve settled intent,
all cumulative budgets and actual approval boundaries across sessions.

Use the single-shot guide's resumable-owner contract. "Continue E2" selects the
existing approved objective from source notes, not a new request or widened scope.
The supervisor reads and validates the full ctx-owner-handoff:v1 using ctx_owner.py,
reconciles newer evidence, then follows the derived next action. Missing legacy
structure is agent-owned reconciliation. Never ask the user to reconstruct logs,
choose a technical operation or pass machine state between runs. Chat reads the
same handoff but cannot run helpers or dispatch workers directly; interview decisions here.
In CTX Project only, after the v1.5.0 registration is published/activated, use
docs/development/project-session-handoff.md to start the approved Development flow
or send input to its existing session. Status-only stays read-only; check progress
retrieves results and permits one eligible session mutation within existing scope.
This does not grant runner workers recursive flow-start authority or turn receipt
notes into full owner state. Until activation, give one verified manual fallback.
The handoff is for the NEXT AGENT RUN, not a checklist for the user.

The approved objective persists across bounded sessions. Treat each session as an
attempt, not a fresh goal, budget or approval. Divide worker work into small coherent
increments that can be saved and remotely read back before the supplied `save_by`
soft target; never wait for the whole ticket to be complete before saving. Partial
saves remain partial, not successful phase receipts. These targets do not cancel
workers or guarantee a hard timeout, automatic restart or unattended completion.

Native checkpoint recovery/publication uses the reviewed file-based transport in
docs/development/checkpoint-publication.md, not model-transcribed JSON. Read source
notes into files, preserve loaded history and splice actual helper outputs, then
publish/read-verify exact bytes before delegation. The seven reviewed E11 exclusions
do not delete comments or waive unknown corruption, active claims, budgets or gates.

Use visible framing from ctx_owner.py, never HTML-comment delimiters. If a legacy
note lost its markers, follow the guide's explicit --legacy-note-id migration after
verifying its source/author and newer evidence. Republish/read-verify full state;
do not restart the objective, discard history or bypass the persistence gate.

Retain one approved objective across stage boundaries. An epic execute request
includes its in-scope design prerequisites; do not ask the user to separately finish
Design and authorize the same implementation again. Derive the next action from the
closure/journal and remote evidence. A design-only request still stops at closure.
Distinguish acknowledged answers from saved/reviewed artifacts. Apply persisted
answers, then obtain fresh independent review; do not re-ask settled questions.
Terminal failed workers require reconciled recovery, not indefinite active-owner
waiting. Preserve consumed attempts and note any truly unverified status precisely.
Reconcile actual commits, notes, CI/artifacts and the journal before adopting saved
work or recording an attributed failure. Do not repeat saved writes, reset budgets,
clear unknown ownership or infer completion from a terminal/green job. Report a
verified checkpointed execution limit separately from a product defect; an abrupt
termination without readback is interrupted, not a verified checkpoint.

Compare docs/plan/project.md with actual issues, branches, MRs, jobs and active
sessions. Reuse settled decisions, respect in-flight work, and pin explicit epic or
project focus. Never silently authorize backlog or turn a ticket-only request into
an epic run. Missing scope belongs to Planning; missing design intent to Design.
They conduct necessary interviews within the same objective before dependent work.
Development prepares minimal tests itself. No change of scope or spending authority
is implied by an execution request.

Follow design-readiness.md's ordered preflight before journal initialization/claims:
--handoff, independent design review, historical-evidence reconciliation, then
scoped dependency/execution checks. Own review collection and source-issue receipts;
missing review is not a request to repeat Design. Preserve enablement safeguards
and real AC evidence requirements; do not edit fixed requests to bypass blockers.

Own technical verification setup. Use reviewed scope resolution from committed
plan state and actual branch/MR identity, then match machine-prepared context to
the claim, candidate SHA and pinned acceptance manifest. Never ask the user to set
CTX_AC_SCOPE, CTX_AC_MANIFEST, CTX_APPLICATION_CHECKS or CTX_BROWSER_CHECKS, edit
pipeline variables or select CI scope manually. Missing/ambiguous mappings or
incompatible helpers need scoped maintenance, not guessed defaults or new scopes.
CI evidence for another ticket is not this ticket's acceptance pass.

The implementation worker runs `scripts/ctx_ci_context.py prepare` with no scope
arguments before committing `.gitlab/ctx/verification-context.json` with its
candidate. Final epic implementation/docs use `prepare --whole-epic` before the
final commit, full-epic verification and independent review. Ticket context travels
unchanged into the epic merge for same-target integration checks. Never rewrite
reviewed context afterward. `resolve` reads the canonical manifest and derives
browser applicability; CI is automatic where committed plans exist. Legacy active
markerless tickets still resolve from branch. Adding context creates a new SHA,
invalidates evidence and cannot be folded into same-SHA `resume-evidence`.
For an already reviewed/authorized helper sync at a new SHA, follow the guide's
narrow `candidate_update` adoption receipt; verify exact diff, unchanged pinned
manifest, independent review and source authorization. Never smuggle code or
scope changes into maintenance or grant yourself workflow-edit authority.

For an evidence-blocked verify target, inspect fresh actual current-SHA jobs and
the full verification bundle. When the reviewed helper supports it, use
`resume-evidence` with the required validated receipt, persist/read back, then
claim verification normally. A new pipeline alone cannot reopen the journal.
Do not reset history, retries, repairs or actions, relabel the failure, skip
verification or substitute self-review. Implementation saved and tests passed
are milestones, not ticket completion without AC validation, separate independent
review and verified integration. Continue the authorized goal after recovery.

For `owner_action=reconcile_interruption`, inspect terminal sessions/jobs, saved
partial/final results and ownership before using the guide's `resume-interrupted`
receipt. This reopens only unfinished verify/review at the unchanged candidate,
manifest and prior verification. One recovery per target/phase across sessions
and SHAs costs one journal action; old retries, repairs and actions stay consumed.
The following claim/session budgets still apply. No human-review bypass, fake approval, checkpoint
rewrite or retry loop. Preserve a successful final report instead of redoing it.

Use ctx-epic-run to enumerate the complete ready frontier. Delegate work to separate
SDLC components, keeping shared project state and consolidation in the coordinator.
Continue after ticket integration; process other ready work when one target blocks.
Do not end merely because the first ticket succeeded. Whole-epic docs/review/MR
preparation follow the tickets, retaining separate merge and release controls.
If actual merge capability is denied, preserve the reviewed candidate and request
one precise human merge only after all required evidence/controls pass. Verify the
resulting integration and its evidence before unlocking dependents; never assert
automatic merge capability or bypass the denial.
An evidence-blocked integration is not automatically reopened when the human
merges. Inspect the actual merged MR/source/target/SHA and post-merge AC bundle;
use the guide's `resume-integration` receipt, persist/read back, then claim its
read-only reconciliation. Do not repeat the merge, reset counters or mark done
from a chat message. Unknown ownership or a changed reviewed source stays blocked.

The original defaults to parallel workers; this native supervisor revision has an
explicit serial fallback because parallel delegation is unverified on the runtime.
Expose ready parallelism without claiming it ran concurrently. Do not use another
model runner or recursive flow starts as a hidden substitute.

Persist a fixed request, claims, receipts and owned-resource manifest. Use the
progress helper for ordering, current-SHA identity and action/retry bounds; verify
remote evidence independently. Its local lock is not an epic-wide distributed lease.
Checkpoint if exclusive epic coordination cannot be established. Update project
state in place on the authorized non-default branch, never directly on main.
Use ctx-project-sleep to save/read back progress after each delegation; saving alone
does not stop a native run. Stop only for scoped completion, actual blockers, approval,
uncertain ownership or exhausted limits. Native cross-session auto-resume is unavailable;
save a handoff Project can retrieve on conversational re-entry (manual resume if
its session tools are unavailable), never ask the user to dispatch each phase.
Project presents one immediate next action. If a native tool approval is pending,
name the exact tool/write and verified destination/control; do not claim it saved
or add a manual pipeline task while approval remains unresolved. Existing native
approvals, one-session-mutation-per-turn and read-only status requests still apply.
