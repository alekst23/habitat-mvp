# Optional controller: multiple recoverable Duo sessions

Status: **Development v1.7.0 published; controller NOT activated** (2026-10-11 UTC).
Full catalog readback matches source commit c1a472a after MR !28 merged; MR !29
synchronized E2 helpers. The native path repeats delegation within one session.
Only optional controller mode retains one-unit slices. Controller identity,
protected state/credentials, verified IDs, scheduler and live acceptance remain
prerequisites for that deferred mode, not for native execution.
**Deferred, not a prerequisite:** published v1.7.0 restores the native
multi-step path in [single-shot-development.md](single-shot-development.md). Use
that path without controller setup. This document governs only verified controller
envelopes; it does not override native continuation. Do not attempt inaccessible
protection/credential/scheduler setup as part of an ordinary Development run.

Planning and Design remain conversations. After their scoped artifacts are saved,
one authorized execution request owns the remaining epic. The deterministic
controller runs outside Duo; the existing Development catalog flow supplies native
subagents in CI. There is no additional bot per operation, ticket, or retry.

The published [CTX Project v1.2.0](project-owner.md) brings the conversational
Planning/Design procedures and project assessment into one chat. It does not
change this controller's installation status or add chat dispatch privileges.
Its read-only assessment can consume these records; only the controller writes
its protected state or launches the next session. The single-epic/serial limit,
manual init/resume boundary and limits on post-pinned-design revisions remain explicit.

The user does not pick the next ticket, collect reviews, or restart ordinary
technical work. The controller continues after saved progress and reconciles
interrupted sessions. Product questions, missing access, actual approvals, uncertain
external writes, conflicts and exhausted budgets still stop safely. Merge and
deployment authority are unchanged. Native parallel execution remains unverified;
this first controller serializes one epic's work, preserving the dependency frontier.

## Why a separate controller

Session 9282723 lost its workflow stream while the second repair delegation was
active. Its job exited successfully without a final session status. The observed
connection lasted approximately one hour; the exact server-side cause is not
established. A longer job timeout or another prompt cannot establish recovery.

`scripts/ctx_execution.py` implements one controller tick. Its GitLab adapter uses
the [Flows API](https://docs.gitlab.com/api/duo_agent_platform_flows/) to start the
same enabled catalog consumer with an exact version and explicit privileges, and
the [GraphQL session query](https://docs.gitlab.com/api/graphql/reference/#queryduoworkflowworkflows)
to read session status. It does not infer success from a pipeline exit code.
Neither experimental restart endpoints nor callback webhooks are required.

Historical v1.6.0 had `max_delegations: 1`. Published v1.7.0 instead has a 64-call
engine ceiling; optional controller mode retains its one-unit admission rule.
The coordinator calls `scripts/ctx_execution_budget.py --mode controller --started-at EPOCH --delegations RESERVED_COUNT`
before delegation; admission closes after ten minutes. Workers target saving by
the envelope's `save_by` (30 minutes after dispatch). This admission check does not
interrupt a running worker, and GitLab's documented component schema supplies no
verified hard per-worker timeout here. Overdue sessions retain ownership; the
controller never launches a concurrent writer. Native termination/receipt readback
must be observed before a recovery session. A stuck live session is reported as
overdue, not silently abandoned or cancelled. The controller does not enforce a
dollar cap; its bounded session/recovery counts supplement GitLab account limits.

## Slice contract (coordinator and every worker)

1. Read trusted default-branch instructions and the controller envelope. Resolve
   source/epic identities, actual branch head, existing sessions, active claims and
   ownership. Respect non-controller sessions too. The controller lock is not
   authority to seize human or manually triggered work.
2. Restore the full last checkpoint from `checkpoint_note_id` on the source issue.
   Recompute its canonical JSON SHA-256 with `ctx_execution.digest`; compare
   `previous_checkpoint_sha256`. Also reconcile newer reservation notes and commits.
   Never initialize a fresh journal just because this is a new CI checkout. Reuse
   the controller run_id in the execution request; retain its original session_url.
3. If `reconcile_session_id` is supplied, read that terminated session's reports,
   owned branches, actual commits and CI. Adopt only verified saved results. Unsaved
   edits are not completed work. Retain existing repair/research reservations. For
   a confirmed failed execution claim, use the existing attributed failure receipt
   and bounded transient retry; never clear an active claim to bypass replay.
4. Use the existing closure assessor or version-2 execution journal to choose the
   next eligible unit. One design repair unit is a coherent group of related
   contracts/findings that can be saved promptly, not the whole remaining backlog.
   Keep the cumulative three-cycle design repair budget and two research attempts
   per stable finding. Smaller units do not create fresh budgets. If these bounds
   prove insufficient, report it explicitly instead of resetting history.
5. Save/read back the full reservation BEFORE the single delegation. Include the
   controller run/attempt/session identity in the ordinary operation report. These
   reservation/progress notes must NOT use the final machine-checkpoint marker.
   Pass the worker its scope, exact base SHA, affected findings, save_by and paths.
6. The worker saves coherent increments on its authorized branch, pushes and reads
   back each saved SHA, then publishes/read-verifies its operation report. Do not
   wait for an epic-sized batch to finish before saving. Keep partial work labeled
   partial. Reviewers remain read/comment-only and cannot repair their own findings.
7. The coordinator reads the actual result, validates the journal/closure and
   evidence, then publishes the final checkpoint below. **No second delegation,
   no manual execution of another phase to evade the cap.** Each fix still requires
   subsequent fresh verification and independent review, in later slices.
8. When design-only closure completes, use outcome=complete with journal=null.
   This means Design complete, not implementation. Return final routing token
   `checkpoint` in design-only mode. Execution complete requires a replay-valid
   version-2 journal covering the scoped epic through reviewed MR preparation.
   All other safe outcomes also return `checkpoint`; persistence/identity failures
   return `blocked`. Detailed reports never belong in the final routing answer.

Without a controller envelope, use the native multi-step protocol. It continues
inside one session, not across sessions automatically. Never invent a controller
run ID. Chat agents cannot start flows themselves with their current tools.

## Final checkpoint note

Publish ONE final note on the resolved source issue, starting with exactly:

```text
<!-- ctx-execution-checkpoint:v1 -->
```

Follow it with one JSON code fence and no other text. `checkpoint_body` renders
the body and `parse_checkpoint` parses it. Full reports may be separate notes.
The required JSON fields are:

| Field | Value |
|---|---|
| version | 1 |
| run_id, attempt_id, request_sha256 | Exact controller envelope values |
| previous_checkpoint_sha256 | Envelope value, null only before first accepted checkpoint |
| session_id | Actual numeric current Duo session ID |
| candidate_sha | Independently observed full current epic branch HEAD |
| outcome | continue, complete, needs_decision, needs_access, or blocked |
| summary | At most 120 words: status, saved result, agent next, user action or none |
| next_action | One concrete next step or question, with evidence/report links |
| closure | Complete validated design-closure record, including active reservations and history |
| journal | Complete replay-valid version-2 execution journal, or null during design closure |

Read the entire saved note back. An acknowledgment alone is insufficient. If a
write is uncertain, search and reconcile before retrying: duplicate final notes
are ambiguous and block dispatch. Do not place secrets in any state/report.
Persist owned-resource manifests in ordinary source notes linked from next_action.

The controller independently fetches/read-verifies the note, checks its configured
service-account author, run/attempt/session, hash chain, current epic SHA, scope,
append-only histories and replay-valid journal. Unknown outcomes, stale receipts,
unverified completion and missing evidence fail closed. These consistency checks
do not themselves attest semantic correctness, actual CI truth, or reviewer
independence: the separate reviewer and coordinator retain that responsibility.

## Durable controller storage and failure behavior

### Persistent objective and decision resume (local revision)

An execute request may start with unfinished prerequisite design. `design_sha`
pins the observed starting revision, not a claim of design approval. The same
objective continues through closure, execution, tests, repairs and independent
review. Design completion alone cannot complete an execute request. Each dispatch
carries a derived `next_action` and any pending answers; these are frozen for that
session, then recomputed from the next accepted checkpoint.

For a terminated design reservation, independently read the native session,
branch head, diff and operation notes. Use `ctx_design_closure.py` with
`--current-sha SHA --reconcile-session OBSERVATION.json --report-url SOURCE_NOTE`.
The observation contains `session_id`, `project_id`, terminal `status` and
`observed_head`. Persist/read back the returned record. Interrupted repairs still
consume their reserved cycle even if no commit survived. Running, unknown or
unreadable sessions cannot be cleared. This helper validates a receipt; it is not
a replacement for remote ownership checks.

For a controller checkpoint requesting a decision, an authorized operator uses
`resume` with `CTX_DECISION_ANSWERS`, a JSON array of objects containing exactly
`id`, `question`, `answer`, `source_url`. IDs and questions must match the saved
checkpoint. Source URLs must identify readable notes on the source issue; the
adapter verifies attribution and the recorded question/answer. A worker's own
report is not user authorization. The protected operator action grants resume;
this is not an authenticated chat bridge. Partial batches may answer some
questions; the others remain unresolved.

Every checkpoint preserves unanswered IDs and exact questions. When a save
invalidates a design review, retain its outstanding decision findings with the old
review SHA until a fresh review incorporates them; do not erase them with
`review=null`. Only verified application receipts retire answered questions.

Answers are queued, not applied, on resume. The next design slice saves them in
scoped feature specifications/ticket documents and reads them back. Its final
checkpoint adds optional `decision_applications`, one object per pending answer:
`answer_sha256` (canonical answer-object hash), `candidate_sha`, `changed_paths`
and `report_url`. Before execution, they name the new current epic SHA. During
execution, they bind exactly to that target's replayed `resume-decision` receipt
and saved candidate, which may be on its ticket branch rather than epic HEAD.
Reports are always on the source issue; comparisons use the prior target candidate
for journal applications and the prior epic candidate before execution.
The controller checks the actual old-to-new diff, fully paginated tree identities
(diff responses can omit files at server limits), exact changed paths, saved file
identities/content hashes and reports before marking the batch applied. It uses
the documented [repository APIs](https://docs.gitlab.com/api/repositories/) and
[file readback API](https://docs.gitlab.com/api/repository_files/). This
slice cannot mix unrelated code, acceptance-manifest or policy changes into its
commit. Applied is not reviewed: fresh structural checks and independent design
review are still required. Unknown intent, scope or AC changes require an explicit
revision plan, not a forged application receipt.

After execution starts, use the replayable `resume-decision` journal transition
described in [single-shot development](single-shot-development.md). Scoped
technical findings use `technical_design` repair and return through independent
design review, tests, implementation and acceptance verification. Both preserve
the pinned request/manifest and consume existing repair/action budgets. General
cross-target design revision remains outside this bounded transition.

Native input/tool-approval pauses are different: resolve them in the existing
GitLab session, then `resume` reconciles that same session. It cannot approve tools
or substitute an issue-note answer for GitLab's native approval control.

State is `.ctx-controller/E<epic>.json` on **ctx/controller-state**, a separately
protected non-default branch. Only the trusted controller identity may write it;
the Duo service account must not. The adapter checks that it is protected and not
default, but permission membership must be checked during installation. It uses
[last_commit_id optimistic concurrency](https://docs.gitlab.com/api/repository_files/#update-existing-file-in-repository)
plus CI resource_group serialization. A loser cannot issue a dispatch. There is
one immutable active authorized request per epic; init never resets an active run.
An explicit new execute request is needed after a completed design-only request,
but not when the existing request already authorizes execution. The handoff keeps
the prior design receipt, histories and consumed controller
budgets; it cannot restart a completed application execution or change the epic.

Dispatch intent is committed/read back BEFORE POST. If the POST or state save is
interrupted, the next tick searches the exact attempt marker and adopts the one
matching session. It never repeats an uncertain POST. Zero matches are observed
for ten minutes, then require reconciliation; multiple matches block immediately.
An empty search is not proof that no session was created.

Running/created sessions wait. Paused/input/approval statuses retain the active
session and surface the actual control. A failed/stopped/finished session with a
valid final checkpoint can progress despite a lost routing tail. A terminal
session without a checkpoint consumes a recovery slot; its successor reconciles
the failed session before new work. No receipt means no completion claim. Request,
session, repair, research and transient-retry budgets survive every tick/restart.
Two consecutive continued slices without durable progress stop further automatic
spend. Unchanged running-session polls do not create empty state commits.
`resume` reconciles after human input without clearing active work or any limits.

## Installation (one-time, requires operator authority)

1. Source MR !28 is merged; Development v1.7.0 and Design v1.8.0 are published
   in their EXISTING entries. Full prompt/YAML readback, max_delegations=64 and
   existing tools were verified. MR !29 synchronized trusted E2 helpers after
   ownership checks. Controller-mode admission still limits a verified envelope
   to one unit; native execution does not require this installation. Do not start
   a paid run as part of installation verification.
2. Resolve the enabled **consumer ID**, exact **catalog version ID** and reporting
   service-account numeric user ID from GitLab. They are not the catalog item ID
   1016234. Fill `.gitlab/ctx/controller.json`, review it, set enabled=true and merge.
3. Pre-create/protect ctx/controller-state. Allow only the controller's identity
   to write; deny the Duo service account. Verify actual API start/status/note/file
   permissions, composite-identity requirements, account credits and branch rules.
   CI_JOB_TOKEN support is NOT assumed. Never bypass a GitLab authorization error.
4. Store CTX_CONTROLLER_TOKEN as a masked, hidden, protected GitLab variable with
   environment scope **ctx-controller**, NOT `*`. Restrict that environment and
   default-branch pipeline/schedule administration to trusted operators. Never
   expose the token to agent jobs or an untrusted branch's code. If identity or
   token permissions are unavailable, deployment is blocked; do not paste secrets
   into chat or committed JSON. Choose explicit allowed/pre-approved privileges;
   the default pre-approved list is empty, so GitLab tool approvals may still pause.
5. Create one default-branch schedule per authorized epic, every 2-5 minutes:
   CTX_CONTROLLER=1, CTX_CONTROLLER_ACTION=tick, CTX_EPIC=<actual epic IID>.
   The opt-in job exits after one bounded tick; schedule retries preserve remote
   state. It is excluded from MR, feature, push and ambient-agent pipelines.

## Start once; test recovery before trusting autonomy

After installation, run a default-branch **web pipeline** with CTX_CONTROLLER=1,
CTX_CONTROLLER_ACTION=init, CTX_EPIC=<IID>, and CTX_EXECUTION_REQUEST containing:

```json
{
  "version": 1,
  "run_id": "e2-approved-execution",
  "project_id": 87329027,
  "source_issue_iid": 10,
  "epic_issue_iid": 2,
  "branch": "ctx/epic-i2",
  "mode": "execute",
  "objective": "Complete the approved E2 tickets, tests, AC validation, fixes and independent reviews. Prepare the epic MR; do not merge or deploy.",
  "design_sha": "REPLACE_WITH_VERIFIED_FULL_CURRENT_SHA",
  "max_sessions": 64,
  "max_recoveries": 2
}
```

Use mode=design-closure and a smaller explicit session budget for a design-only
run; it cannot implement. This schema is an example, not authorization to execute
E2 now. Keep !8 open. The schedule owns subsequent ticks; no ticket-by-ticket
human invocations. Progress lives on the source issue and in controller job output.
After answering a real question/approval in the relevant issue/session, run one
web pipeline with action=resume and the verified `CTX_DECISION_ANSWERS` batch for
checkpoint questions. For native approvals or resolved access, reconcile the
existing control instead. Resume does not expand scope or reset budgets.

Local checks:

```sh
python scripts/ctx_workflow.py validate
python -m unittest discover -s tests/workflow -v
```

Live smoke on an explicitly authorized disposable epic: verify one phase per
session and automatic next phase; interrupt once after a saved commit; verify
reconciliation without duplicate writes and unchanged cumulative budgets; simulate
a lost final routing tail; verify saved checkpoint recovery; introduce an actual
failing AC, then observe fix -> new-SHA checks -> independent review. Confirm a
product question pauses, an answer resumes, and no merge/deploy occurs. Record
session/job IDs, note URLs, SHAs and state commits. Local fixtures and catalog
acceptance are not proof this live integration passed.
