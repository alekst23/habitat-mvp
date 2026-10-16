# CTX single-shot Development

**v1.10.0 published/read back on 2026-10-15 UTC:** read
[checkpoint-publication.md](checkpoint-publication.md). The new file-based
read/assemble/publish path supersedes manual note transcription for native owner
checkpoints. It preserves exact readback and all history/budgets, and excludes only
the seven reviewed corrupt E11 notes without deleting them. Source !49 and E11
helper sync !50 are merged; full saved catalog YAML matches reviewed source 9522bf6c.
Workflow checks/reviews passed; separate application verification failed and the
user explicitly approved workflow-only merging. No CI controls changed. Project is
v1.6.0. No application run started; live verification remains pending.

**Historical v1.9.0: transport-safe native handoffs.** Session 9303064 reported
HTML-comment delimiter loss. The new codec emits visible markers, retains intact
legacy reads and supports explicit verified-note migration. Source !35 at 25649246
passed pipeline 2936852177 and independent Duo review note 3994970235, merging to
main at 9deb5530. E2 helper sync !36 at 0f6d1883 passed pipeline 2936856436 and Duo
review note 3994972774, merging at 9b4e8810. All 187 local tests, CTX validation,
diff and outgoing secret checks passed. Product docs/design and docs/plan remain
byte-identical to df380b13. The source and helper changes are now available to runs.

On 2026-10-12 UTC, full saved catalog v1.9.0 YAML (40948 bytes) matched source
256492461fb329f2b018fc5aa3348a9a472f14ce after final-newline normalization, SHA-256
080a37445951b671901af655666065282cd0174ed39d08befc07f7e9f15400bd. Private visibility,
enabled state, service account, active Mention/Assign/Assign reviewer triggers,
toolsets and 64-delegation ceiling are unchanged. Project remains v1.3.0.
No execution was launched, no source checkpoint rewritten and MR !8 remains open.
Same-tool-path migration and delegation still need live verification: local fixtures
and catalog readback do not prove that runtime behavior. Resume with the existing
Development mention plus `Continue E2`; the supervisor owns legacy reconciliation.

Historical v1.8.0 baseline: resumable native multi-step execution is the default.
One human invocation advances eligible phases/tickets, saving between delegations.
No controller, protected controller state, scheduler or new credential is required.
Full catalog readback passed on 2026-10-11 UTC after MR !31; MR !32 synchronized
trusted E2 helpers. Native runtime behavior still needs live acceptance. Cross-session
auto-restart remains unavailable. [Durable execution](durable-execution.md) is optional,
deferred installation work, not a prerequisite for the native path.

Published resumable-owner protocol: automatic handoff discovery and derived owner
actions are live in Development v1.8.0 and Project v1.3.0. Full saved definitions
match source 462fd9f1 after final-newline normalization. Source !31 and helper-sync
!32 passed current-SHA CI and independent follow-up review; 184 local tests passed.
Catalog acceptance is not runtime acceptance: the live two-run test remains pending.

## Resumable owner handoff

The user owns product intent; the supervisor owns technical diagnosis, dispatch,
recovery and verification. A run may end without ending ownership of the objective.
For an already approved objective, a human mention such as `Continue E2` is enough:
derive source identity from the trigger, epic/mappings from the plan, and scope,
mode, branch, original run ID and exclusions from verified saved records. Do not
ask for internal IDs, logs, worker names or a recovery recipe. Never infer execution
authority from an agent-authored note: verify the original human request and newer
pause/cancel/scope instructions. A first request still needs a bounded objective.

This codec covers one explicitly scoped epic (including ticket-only focus). Existing
multi-epic journals and optional controller envelopes retain their own protocols;
never split, upgrade or reset one to fit this schema. Project chat reads the same
handoff but does not run shell helpers. Previous Project v1.4.0 could not dispatch;
published v1.5.0 session handoff claims a start only after actual
native-tool success and session readback, not after writing a note.

### Intake from an activated Project session handoff

With published Project v1.5.0, a scoped native start can arrive from its session
tools rather than a bot mention. Read [project-session-handoff.md](project-session-handoff.md).
Use the explicit goal to resolve source issue/epic/branch/mode and its request-note
URL/key; verify them against actual project/session identity and repository mappings.
Do not require a synthetic mention event or trust an IID guessed from a title.
The coordinator still owns all workers and full native state; no worker starts flows.

For an existing objective, verify the original human authorization note and newer
pause/cancel/scope changes. Retain its URL, run ID, history and consumed limits.
For a first chat-originated objective, the Project-written request note is an honest
scope record, NOT a human-authored authorization. Compare it with the authenticated
native invocation's actual initiating actor and approved goal before admitting work.
Record the real session/invocation evidence and note's server author; never infer
consent solely from text in the note or a bot's launch. If the runtime does not expose
sufficient provenance, save one precise native confirmation/access request; do not
fabricate identity or proceed. Only after remote verification may authorization_url
point to that source scope record. The codec validates URL syntax, not consent.

Apply the same rule to chat-recorded answers: stable question/answer identity and
verifiable user/input provenance, never a summary presented as human consent.
Native input/approval must use the existing waiting session. Current explicit
approval is required for an approval gate; an execution goal or check-progress
request does not satisfy it. General technical feedback can be agent-attributed.
No merge/deploy/spend/policy authority is added. These intake changes require a live
provenance/start/input smoke; local prompt checks cannot prove API behavior.

### Reconstruct, act, verify, save, continue

1. Use the reviewed `ctx_checkpoint.py read` file download described in
   checkpoint-publication.md for full native source state; do not manually transcribe
   note arrays. Read all relevant source notes with pagination, verified authors and server IDs,
   linked reviews, original authorization, actual branch/MR heads and session status.
   Serialize source notes as `[{id, url, body, author_id}]`, using server-returned
   authors, never IDs claimed inside a note. Resolve trusted checkpoint writer IDs
   from actual flow registration/session evidence (including verified prior writers).
   Pass each separately via `--trusted-author-id`; do not trust every commenter or
   derive the allowlist from the checkpoint being selected. Untrusted-author notes
   are ignored as state, but human decisions still need separate source verification.
   Run (replace WRITER_ID with the verified numeric ID):

   ```sh
   python scripts/ctx_owner.py resume NOTES.json --source-issue 10 --epic E2 --trusted-author-id WRITER_ID
   ```

   Substitute actual identities. The helper selects the newest full compatible
   `ctx-owner-handoff:v1` block, rejects ambiguous/malformed state and history loss,
   and replays the embedded journal. It cannot authenticate the fetched data.
   Older prose/closure checkpoints return `reconcile_legacy`: reconstruct their full
   records and original authority yourself, preserving attempts, active reservations,
   settled answers and evidence. Missing JSON is not permission for a new run or a
   request for the user to paste logs. Conflicting records need agent investigation;
   ask only a genuinely ambiguous objective/access question after that investigation.
2. Inspect changes since the saved record before using its proposed next action.
   A saved `next` sentence is advisory; derive work from closure/journal instead.
   A failed session is terminal, not an active writer. Reconcile its notes, commits,
   diff and reservation. Use `ctx_owner.py recover-closure HANDOFF.json --observation
   OBSERVATION.json --report-url SOURCE_NOTE` for an interrupted closure claim;
   observation is the existing terminal-session shape below. Consume reserved repair
   budget. For execution claims, adopt a verified result or publish an attributed
   failure receipt and use the existing journal transition. Never clear unknown or
   running work, duplicate a saved write, or restart closure after journal pinning.
3. Use `ctx_owner.py next HANDOFF.json` and the journal's derived `owner_action`.
   Repair actionable defects before requesting another plan; continue ready work
   even if another target needs a decision. `reconcile_retry` means inspect fresh
   evidence before spending the permitted retry. `reconcile_interruption` uses the
   bounded read-only phase recovery below, even when that retry is spent.
   `reconcile_blocker` means inspect
   and resolve evidence/dependency/technical gaps within authority, not ask the user
   which phase to run. If no safe transition exists, save the attempted remedy and
   precise access/approval/scope boundary; do not repeatedly inspect unchanged state.
   `reconcile_answers` verifies exact questions, provenance, targets and saved files
   before applying queued answers. Never reapply an old answer to a different question.
4. Delegate, verify actual reports/CI/ACs and independent review, record the result,
   then save/read back the full handoff and derive the next action again. Keep the
   native admission clock, delegation reservations and cumulative repair/action caps.
   Routine saves, a worker's final response or a repair finding do not end the run.
5. Stop only at completion, a material product question, genuine access/approval or
   ownership uncertainty, or an execution limit. Finish other eligible work first.
   Ask product questions in plain language with options/recommendations, checking
   prior answers first. Keep the interview in Project; source-note questions provide
   durable context. Published Project v1.5.0 can retrieve this checkpoint and take
   one eligible continuation on check progress; do not ask for copied results.
   Without that capability, at a limit the user only needs the verified trigger handle plus
   `Continue E2` on the source issue. The next agent run, not the user, reads the
   technical handoff. A native tool-approval pause must use the existing session's
   UI or supported input API with explicit current human approval, never a new run.

### Native payload (not a controller checkpoint)

`ctx_checkpoint.py publish HANDOFF.json` transports the generated file directly,
validates the latest parent and verifies exact saved body AND parsed payload equality;
see checkpoint-publication.md. Never retype full state into a note/file tool or
heredoc. `ctx_owner.py render HANDOFF.json` remains the underlying codec and formats one JSON block between
standalone visible `CTX_OWNER_HANDOFF_V1_BEGIN` and `CTX_OWNER_HANDOFF_V1_END`
lines, separated from the fence by blank lines. Never use HTML comments for new
handoffs: the observed note-tool path drops them. This changes framing, not the
version-1 payload. Intact old HTML-comment frames remain readable. The publisher puts it below
the <=120-word status/result/agent-next/user-action summary. Its direct GET readback
and `ctx_owner.py parse` compare the entire payload to the intended generated value.
Do this before dispatch and after each result, including final run boundaries.
Do not truncate the journal or keep durable state solely in `.ctx`.

### Recover a marker-stripped legacy note

The supervisor owns this migration; do not ask the user to copy JSON or run helpers.
Read the complete original note through the source-note tool and verify its server
author/ID/URL, original authorization and later evidence. For one known legacy
checkpoint whose markers were stripped, add `--legacy-note-id NOTE_ID` to the
`resume` command above. Repeat only for independently verified legacy checkpoints
needed to check their history. This opt-in accepts exactly one fenced JSON block,
validates the entire ordinary payload and applies the same author/scope/continuation
checks against marked notes. Unknown/untrusted IDs, multiple fences, duplicate JSON
keys, malformed state and scope/history/budget loss fail closed. Ordinary `parse`
does not accept markerless JSON, and unknown/mixed markers cannot use migration.

Reconcile later stop notes, reservations and real sessions before acting. Render
the recovered full payload in the new format, publish it with the legacy source
links, read the saved note back through the same tool path and compare parsed values
exactly. Continue the existing objective only after this succeeds. Do not modify or
delete old notes, commit checkpoint-only files that move the design SHA, reset
budgets, start another run, or skip persistence. If the new frame also fails, retain
the failed note ID and stop without repeated probes; report the actual tool boundary.

For the reported session 9303064 stop, inspect checkpoint 3994579905 and earlier
record 3994455813 on #10, plus later stop/decision notes. Preserve design-closure
scope, both consumed repairs, queued Q6/NR-12 answers from 3994412271, original
run ID and the reserved-but-undispatched slot in session 9302989. Do not infer a
new reservation for 9303064 or mark answers applied. This is a recovery lead from
the report, not live verification of those notes or authority to widen E2 scope.

### Payload fields

The payload has:

- `version: 1` and `objective`: original `run_id`, project ID/path, source IID, epic,
  branch, `mode: execute|design-closure`, `goal`, verified request `authorization_url`
  (human source note, or scope-record pointer only under the intake rule above),
  `ticket_ids` (null for whole epic) and scope `exclusions`.
- `closure`: the full existing design-closure record and histories, retained as the
  baseline after execution starts; `journal`: the full replay-valid progress journal
  or null before execution preflight. No second set of ticket statuses.
- `closure_returns`: append-only `{reservation, result_sha, report_url}` receipts
  for read-verified worker returns, including research/review before subsequent
  checks. Copy the exact reserved identity. Interrupted claims instead use the
  closure's existing reconciliation history. Repair cycles remain consumed there.
- `session`: actual `session_id`, `started_at` epoch and all reserved `delegations`.
  A new verified session gets a new session clock, not fresh cumulative budgets.
- `resources`: the complete append-only ownership manifest; append release events,
  don't erase provenance or delete foreign/dirty resources.
- `decisions`: stable `id`, exact `question`, `answer`, source-note `source_url`,
  `targets`, and `state: acknowledged|queued|saved|reviewed`. Saved/reviewed entries
  also have `saved_sha`. Preserve answers and honest provenance; states do not
  authenticate consent or replace real artifact/readback/review checks.

The objective is immutable for a simple resume. A genuinely revised scope/objective
needs an explicit human-authorized reconciliation with retained history; never pick
the newest of competing objectives or reset a journal to obtain fresh limits.

Required live acceptance: two runs using the same source issue; the second
receives only a short continue request, recovers a terminal reservation or restores
a failing-test journal, repairs and re-verifies, advances the next ticket, and asks
only a genuinely unanswered product question. Preserve original scope, every AC,
prior answers, evidence and budgets. Local codec/journal tests are not this live test.

## Native session protocol

1. Establish explicit scope and actual project/source/epic/branch/session identity.
   Read trusted default-revision instructions/helpers; verify the working epic has
   compatible helpers without overwriting product changes. Never self-edit policy
   or weaken CI to make a run proceed. Respect active/uncertain writers. Missing
   controller configuration/state is not itself a blocker or proof of no active work.
2. Reconcile source-issue notes, branch/MR head and actual session/job evidence.
   On resume read the **full** last verified ordinary checkpoint plus newer claims,
   receipts and commits, not only the summary. Preserve its original request/run_id,
   full closure record, exact acceptance-manifest text, replay-valid v2 journal,
   repairs/research/retries, resource manifest and pending decisions. Before journal
   initialization persist the explicit objective/scope and closure with journal=null.
   Never start a replacement journal to evade exhausted limits. A terminated session
   requires saved-result reconciliation; active or uncertain claims cannot be cleared
   merely because this checkout is fresh. Adopt only read-verified remote work.
3. Persist one session budget record `{session_id, started_at, delegations}` in the
   ordinary source checkpoint. Use the actual session's observed start epoch (or
   record the runtime clock once on first coordinator entry if unavailable). Count
   **every reserved delegate_task**, including closure, research, review and failures.
   Reuse that start/count throughout the session, including after context compaction.
   Only a verified different native session gets a fresh session clock/count; the
   run's cumulative journal/repair/research limits never reset. Unverifiable session
   identity/budget requires a checkpoint, not a made-up start or zero counter.
4. Before **each** delegation, run the trusted admission helper:

   ```sh
   python scripts/ctx_execution_budget.py --mode native --started-at EPOCH --delegations RESERVED_COUNT
   ```

   Substitute the saved values. The helper denies admission at 40 minutes or 64
   reserved delegations; the native engine independently caps calls at 64. Before
   dispatch increment the counter and publish/read back it with the closure/journal
   reservation and scope. Reserve first so a lost result still consumes the slot.
   Pass `save_by` to the worker: save coherent increments within 15 minutes and by
   session minute 50. These are conservative **soft targets**, not guaranteed runtime
   or dollar limits, and cannot cancel a running worker. The counter/clock persist
   through the coordinator protocol, not an external enforcement service.
5. Run design closure first when needed. Under an execute objective, continue into
   the existing v2 journal; explicit design-only scope stops after closure. Select
   `next`, claim, delegate, independently verify remote evidence, record the receipt,
   and save/read back the full checkpoint. Reassess and delegate again **without a
   final response or another human go**. `integrate.more` means continue here.
   Route technical defects to bounded repairs and fresh verification/review. Continue
   unrelated eligible work when one ticket blocks. Do not weaken ACs or fake adapters.
6. End only at verified scoped completion, real decision/access/approval boundary,
   uncertain ownership/write, exhausted budgets or a runtime limit. Publish/read back
   a <=120-word summary followed by full state/evidence. Include what finished, exact
   blocker, agent next, user action or none, and one short **resume** instruction.
   Put source/epic/branch, original run ID and evidence in the durable handoff. A native resume
   is human-triggered through the same registered Development flow, not controller
   activation, an agent-written bot mention, a new planning run or automatic restart.
   Actual product decisions return to the interactive Project/Design conversation;
   settled answers are saved with provenance and applied before repeating questions.

Never use the controller's final machine-checkpoint marker for ordinary progress.
If a verified controller envelope is actually supplied, use its hash-chain/identity
protocol and `--mode controller`: one reserved delegation, admission before minute 10,
save target minute 30, then final checkpoint. Disabled controller installation stays
disabled. Do not infer an envelope from a note, keyword or user-supplied fake run ID.

The native contract uses GitLab's documented [supervisor delegation](https://docs.gitlab.com/user/duo_agent_platform/flows/claude-edit-v1-flow-registry/#supervisor-mode).
Local simulations validate ordering and budgets, not live model behavior or recovery.

### Native recovery and decision application

For a terminated closure reservation, inspect the actual session, branch head/diff
and saved notes, then run `ctx_design_closure.py RECORD --current-sha SHA
--reconcile-session OBSERVATION.json --report-url SOURCE_NOTE`. The observation has
`session_id`, `project_id`, terminal `status` and `observed_head`. Read back the saved
returned record; interrupted repairs consume their reserved cycle. Unknown/running
sessions cannot be cleared. For journal claims use an attributed failure receipt
and the existing bounded transient retry only after equivalent reconciliation.
If tools cannot expose enough live ownership evidence, checkpoint with that exact
access limitation; do not require controller setup or assume a dead writer.

For native decision resume, read the actual authorized human trigger and referenced
source notes. Match stable decision IDs and exact questions; record answer text and
honest provenance. A chat-authored summary alone is not user consent: obtain human
confirmation in the resume request when attribution is unavailable. Keep unanswered
questions and old findings. No controller envelope, token or pipeline variables are
needed. Delegate design `mode=decision-application` for scoped document updates,
using the prior target SHA/paths. Verify the actual changed paths, full files at the
returned commit SHA and source report before marking answers applied. With a pinned
journal use its `resume-decision` transition below, retaining the original request,
manifest and limits. Without a journal update the closure candidate and require new
structural checks and independent review. Never mix unrelated code, policy or AC
changes into an answer-application commit. A real scope/AC revision still needs an
explicit plan. Native tool-approval pauses must be resolved in the **existing GitLab
session** through its UI or supported input API with explicit current approval;
a new trigger or issue-note answer cannot replace that control.

### Required live smoke after publication

Use an explicitly authorized disposable epic to test one human invocation with no
controller configured: observe at least two delegations, a real failing AC followed
by a fix/new-SHA verification/independent review, then the next eligible ticket.
Check full source readbacks before/after each worker. Test a real product question
and one manual resume retaining run/manifest/history; test terminated-session
reconciliation without duplicating saved work. Stop on actual missing adapters or
permissions; preserve merge/deploy controls. Record session/job/note/SHA evidence.
Publication and fixture tests do not count as that live smoke.

Previous publication (v1.8.0): !31 pipeline 2936414071 passed at 462fd9f1; independent Duo
review 3994185023 confirmed the delimiter/provenance fixes, then main merged at
56d930d5. Helper-sync !32 pipeline 2936414062 and review 3994187239 passed at
039ccb54; E2 merged at cbd92690. Product specs/plan are byte-for-byte unchanged.
Full 40873-byte saved Development v1.8.0 YAML matched the source with its final
newline trimmed. Same private visibility, tools, 64-delegation ceiling, service
account and active Mention/Assign/Assign reviewer triggers. No application run,
product MR !8 merge or controller activation. Live two-run acceptance is pending.

Historical publication: source MR !28 at c1a472a passed pipeline 2936042723 and Duo
review note 3993463855, then merged at 64738d8. Full saved YAML (40838 bytes) matched
that source after final-newline normalization. Helper-sync MR !29 passed pipeline
2936095389 at e86612d and merged at d2ebf02; its independent follow-up review
note 3993535891 confirmed the stale-question correction. E2 docs/design and
docs/plan remain byte-for-byte unchanged, including the existing Q6 decision.
No application execution, product MR !8 merge or controller activation occurred.

## Earlier publication history

Historical status: **CTX Development v1.5.0 published and enabled on 2026-10-09**, retaining
version-2 repair/verification and adding Design-only closure and token-match routing.
[MR !20](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/20)
merged at `2ffcb740`; [pipeline 2932009307](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2932009307)
passed. MR !21 synchronized E2 helpers at `849c3450`, with pipeline
2932047796 passing. All 139 local workflow tests and outgoing secret scans passed.
Full saved YAML matched the tested source, with only its final newline trimmed.
Private visibility, enabled state, service account and active triggers were preserved.
Source and saved hashes are recorded in `.gitlab/ctx/catalog.json`.

No application work or flow run was dispatched by publication. Native repair-loop
execution, Design closure and checkpoint routing still need live validation;
application execution also requires its adapters. This replaces v1.4.0; the historical
v1.2.0 run stopped at preflight. Old sessions/journals retain their own rules.

GitLab rejected the initial `on_delegation_error` UI logging event. The published
definition removes that unsupported event, and the local validator now rejects
unsupported/duplicate event names. This compatibility correction is included in
MR !7; it does not change the runtime helpers already merged by !6.

## What is preserved from the original process

The behavioral references are the original `at-project-go` and `at-epic-run`
procedures: assess reality, respect in-flight work, pin the authorized objective,
identify independent work, execute the SDLC, consolidate, then reassess until the
scope is complete or real blockers require input. Planning and design interviews
remain in their chat agents, before background execution.

| Original behavior | CTX implementation |
|---|---|
| One project-go invocation | One native Duo supervisor session for explicit epic/project focus |
| Project state assessment | Read project plan, issue mappings, branches, MRs, jobs and active sessions |
| All remaining tickets | Bounded journal advances every authorized ticket, not one ticket per invocation |
| Parallel waves | Complete ready frontier is computed; **serial fallback** for the current native supervisor runtime |
| Isolated workers | Explicit ticket worktrees/branches and delegated subsessions; coordinator owns shared state |
| Test, implement, review, integrate | Separate delegated components; reviewer has no code-write/shell tools |
| Partial failures | Block affected dependents; continue unrelated ready work |
| Repair loop | Up to three evidenced code/test/AC repair cycles per ticket or assembled epic; fresh checks and independent review after each fix |
| Final consolidation | Docs, current-SHA whole-epic review, then MR preparation |
| Durable project state | Coordinator updates approved non-default branch and verifies source-issue checkpoint |
| Safe cleanup | Explicit ownership manifest, no force removal, no cleanup of dirty/foreign work |

We deliberately do not port direct commits to main, automatic merges/releases,
force/glob cleanup, arbitrary backlog expansion or merging partial unreviewed work.
Existing GitLab identity, evidence and protected-merge rules take precedence.

## One invocation, multiple delegations

Published v1.5.0 adds [Design-owned closure](design-closure.md) before execution.
Explicit mode=design-closure uses the same supervisor for review, public research
and bounded document repairs, then checkpoints WITHOUT ticket claims/application
implementation. Ordinary authorized execution continues through historical-evidence
reconciliation and scoped gates only after reviewed closure. Merge, helper sync and
full catalog readback are complete; that does not establish a passing native run.
Review reports go to the source issue, which chat can read; do not require the user
to manually transcribe an MR review or repeat the Design interview. Later enablement
gates remain enforced and cannot replace actual AC evidence with fixture claims.

The existing `ctx-development` entry point becomes an `AgentComponent` supervisor
using `subagents`, `delegate_task`, `final_response_tool` and `max_delegations: 64`.
GitLab documents these in its [flow registry](https://docs.gitlab.com/user/duo_agent_platform/flows/claude-edit-v1-flow-registry/).
No extra flow/bot is registered for each skill, ticket or reviewer. Review remains
a separate read/comment-only component, not GitLab MR approval.

The supervisor delegates these phases for each ready ticket:

```text
committed-design preflight → minimal red tests → implementation
    → verify every AC/test/browser requirement → independent review → verified integration
         ↑                                     │
         └── implementation fix ← scoped defect┘
    → reassess ready frontier and continue in the SAME session

all epic tickets integrated → documentation → full-epic verification → epic review → MR-ready
                               ↑                                │
                               └── assembled-epic fix ← defect ┘
```

An explicit ticket-only request retains its narrow scope and does not close the
epic. An explicit project focus can include multiple epic snapshots from approved
active work; it does not implicitly authorize the entire backlog. A missing product
decision goes to Design, a changed scope/decomposition to Planning. Development
prepares tests itself; users do not need separate test-skill invocations.

The documented supervisor returns control after a managed delegation. True
parallel delegation is **not verified** on Showcase. GitLab's relevant
[parallel-delegation implementation](https://gitlab.com/gitlab-org/modelops/applied-ml/code-suggestions/ai-assist/-/merge_requests/6172)
was still presented as a draft when inspected. This is evidence of a capability
gap, not proof that no GitLab deployment supports concurrency. Do not market this
revision as full parallel parity. A CI fan-out executor or a verified parallel
native runtime requires additional isolation, leases, result collection and tests.

## Progress journal protocol

`scripts/ctx_development.py` owns the local bounded progression. It does not launch
agents, call GitLab, certify model reports, or grant merge/deployment authority.
The supervisor owns actual delegation and remote verification. A local file lock
prevents two writers to the same journal; **it is not a distributed epic lease**.
Before dispatch, reconcile remote sessions/MRs. If exclusive epic coordination
cannot be established, checkpoint rather than take over another run's work.

The coordinator creates a request object using verified remote values (the values
below are schematic, not permission to operate on a project):

```json
{
  "version": 2,
  "project_id": "87329027",
  "project_path": "gitlab-ai-hackathon/transcend-october-2026/43066631/showcase",
  "source_issue_iid": 10,
  "run_id": "session-ACTUAL-ID",
  "session_url": "https://gitlab.com/PROJECT/-/automate/agent-sessions/ACTUAL-ID",
  "epics": [
    {
      "state": "REPLACE_WITH_THE_FULL_VERIFIED_VERSION_2_STATE_OBJECT",
      "branch": "ctx/epic-i2",
      "base_sha": "REPLACE_WITH_OBSERVED_40_HEX_SHA",
      "design_sha": "REPLACE_WITH_VERIFIED_40_HEX_DESIGN_SHA",
      "acceptance_manifest": "REPLACE_WITH_EXACT_COMMITTED_ACCEPTANCE_JSON_TEXT_INCLUDING_WHITESPACE"
    }
  ]
}
```

For a ticket-only focus, add `"ticket_ids": ["E2-2"]` to that epic entry. Dependencies
outside that focus must already be integrated; the helper never widens the request.
Unknown/duplicate identities, cycles, missing committed SHAs and changed pinned
request contents fail closed. Existing running/blocked work is preserved, not seized.
Cross-epic prerequisites must be verified/integrated during preflight; the existing
state format models internal ticket dependencies and does not encode a global DAG.
The embedded manifest is the exact UTF-8 text fetched at the pinned design revision,
not a parsed/reserialized copy: CI hashes the original file bytes. Its ACs must cover
exactly the epic's planned ticket IDs. Pin it for the entire run; changes to intent,
required methods or scope require reconciliation, never an automatic repair waiver.
Version-1 journals still replay with their original rules, but have no automatic
repair authority. Do not edit their version or reset them to obtain fresh budgets.

Run from the trusted coordinator checkout, not a mutable ticket worktree:

```sh
python scripts/ctx_development.py init .ctx/development/RUN.json .ctx/development/RUN.request.json
python scripts/ctx_development.py next .ctx/development/RUN.json
python scripts/ctx_development.py claim .ctx/development/RUN.json E2-1
# Delegate the returned component with exact active identity and worktree.
# Version 2 maps phase=verify to the existing browser component (no new bot).
# Read back its report, verify GitLab evidence, then serialize the receipt:
python scripts/ctx_development.py record .ctx/development/RUN.json .ctx/development/RUN.receipt.json
```

`claim` consumes a bounded action before dispatch and permits only one active claim
in serial mode. Never discard an active claim after a timeout: reconcile its actual
completion first. Publish a durable checkpoint before dispatch and after each result.
The request, journal, receipts and resource ownership manifest must survive the CI
checkout in source-issue notes or committed run documents on the authorized branch.
An existing journal cannot be initialized over. `.ctx` alone is not durable state.
On load, the helper replays receipts to reconstruct progress and rejects mismatching
derived state; editing a status field cannot skip phases. Replay still does not
prove that an evidence URL was fetched or its contents were true.

Receipt fields are `run_id`, `target`, `phase`, `attempt`, raw `response`, saved
`report_url`, `report_readback: true`, and `candidate_sha` (also required for blocked
version-2 receipts). The supervisor
must actually read the note; it cannot invent that boolean. Integration additionally
requires `integration` with `source_sha`, `epic_sha`, `pipeline_url`, and the previously
recorded independent `review_url`. Report URLs must name the run's source issue.
Version 2 also requires `integration.verification` for the actual resulting
`epic_sha` and ticket scope. A pre-merge candidate pass is not post-merge evidence.
If a merge already happened but its verification fails, record the outcome as a
conflict for reconciliation; never pretend it did not merge or blindly retry it.

The raw response is normalized with the existing strict last-token/JSON parser.
Unknown/conflicting signals fail closed. A token never substitutes for the saved
operation report or actual evidence. Review/browser/integration receipts must match
the delegated candidate SHA. Only successful integration unlocks dependents. An
integration token `complete` does not independently certify the whole run complete.

If a delegation has verifiably failed without publishing a report, the coordinator
may publish/read back its own clearly attributed failure note and record a `blocked`
receipt. This cannot create a passing review or successful worker result. An
uncertain/still-running delegation remains active until reconciled; never abandon it
just to launch another. Other ready work continues after a confirmed failure is recorded.

A `blocked` receipt requires `reason` and `blocker_kind`: `decision`, `evidence`,
`ci_pending`, `transient`, `conflict`, or version-2 `defect`. Unrelated work remains eligible. A waiting
or transient target can receive one reconciled retry using a freshly observed
same-project pipeline/report URL:

```sh
python scripts/ctx_development.py retry .ctx/development/RUN.json E2-1 --observation-url VERIFIED_URL
```

`retry` re-observes a wait/transient condition; it does not authorize code repair or
prove that the supplied URL was visited. The supervisor must inspect new evidence.
An evidence-blocked verification phase uses the distinct `resume-evidence`
transition below, not a relabeled transient retry or a manual status edit.
The journal stops at 60 actions, below the engine's 64-delegation cap. A budget,
unresolved CI wait, decision or conflict results in a truthful durable checkpoint.
The invocation may span multiple tickets but cannot promise unlimited execution.

The supervisor's final token is `complete`, `checkpoint` or `blocked`. Its existing
deterministic routing adapter normalizes that one final response. Managed workers
return to the supervisor, not through standalone graph routers. `checkpoint` ends
the session successfully without asserting the implementation is complete.

Published v1.5.0 uses fixed token-match probes and the framework's documented
execution_result success/failed, not equality with tool_responses. The actual
[deterministic node](https://gitlab.com/gitlab-org/modelops/applied-ml/code-suggestions/ai-assist/-/blob/main/duo_workflow_service/agent_platform/v1/components/deterministic_step/nodes/deterministic_step_node.py)
sets this status on tool success/exception; the
[command executor](https://gitlab.com/gitlab-org/modelops/applied-ml/code-suggestions/ai-assist/-/blob/main/duo_workflow_service/executor/action.py)
raises action errors. Parser source is hash-pinned, model text remains file data,
unknown/conflicting signals abort, and success consumes only that scratch file.
Regression tests include decorated output and command/write/parser failures.
Native deployment still needs a checkpoint smoke; session 9270082 failed after
prepare and before capture, so the new adapter removes output-format dependence
without claiming the old runtime's exact wrapping was observed.

## Version-2 verification and repair

### Recovering a platform-interrupted read-only phase

The old one-per-target transient `retry` remains unchanged. It is not the recovery
budget for every review in a multi-session objective. An idle v2 journal whose
latest receipt is `blocked/transient` at `verify` or `review`
exposes `owner_action.action=reconcile_interruption`. This does
not establish eligibility by itself. The coordinator must first reconcile the
actual failed/canceled session, its terminal runner job, current head/manifest,
ownership, reports and artifacts. Adopt a valid saved final result rather than
duplicating it. Unknown/running/paused work, permissions, auth failures, deliberate
human cancellation, findings and missing required evidence are not platform-retry
authority. Writing, integration and close phases are excluded.

After verifying the platform interruption and absence of a final phase result,
publish/read back a fresh source report binding the exact blocked claim to the
session/job and its termination evidence. Use the trusted helper:

```sh
python scripts/ctx_development.py resume-interrupted .ctx/development/RUN.json TARGET --receipt RECOVERY.json
```

The exact receipt fields are `run_id`, `target`, `phase`, `blocked_attempt`,
`blocked_report_url`, `candidate_sha`, `acceptance_manifest_sha256`, `report_url`,
`report_readback: true`, `remote_readback: true`, `ownership_verified: true`, and
`interruption`. The last object contains string `project_id`, `session_id`,
`session_url`, `status` (failed/canceled), `job_url`, `job_status`, `cause`,
`terminal_reason`, `evidence_url` (that job's `#L<number>` log line), nonempty
`detail`, `result_absent: true`, and `claim`. The claim is the blocked receipt's
exact run_id/target/phase/attempt/candidate_sha/report_url. Cause is
`execution_limit`, `runner_failure` or `stream_lost`; terminal_reason matches
cause except stream_lost uses `delegation_result_missing`. Job status is
failed/canceled, or success ONLY for evidenced stream_lost. Bind project/session
and job through actual remote readback, not their URL syntax alone. Read the
report and log; never fabricate attestations. A passed wrapper job is not session
success: session 9621826 failed while job 17244915866 exited zero, reporting a
lost stream and an unfinished review delegation. Record `stream_lost` for that
case; do not infer a hard execution limit merely from elapsed time.

Recovery appends an `interruption_resume` event with the next integer `action`
and reopens the SAME phase; it never advances it or grants a passing verdict.
There is ONE recovery per target/phase, cumulative across SHAs and sessions,
separate from the unchanged old retry counter. The transition consumes one
journal action; the subsequent claim also consumes its normal action and session
allowances. No fallback to the old retry after this recovery cap is spent.
Do not refund actions, repairs or reservations; checkpoint when a limit is spent.
Review requires the unchanged saved current-SHA passing verification. Reverify remote evidence and
independent-review provenance before delegating. A changed candidate is not
eligible for this same-SHA transition.

Persist/read back the entire updated owner handoff before dispatch. Pass the
reviewer's saved partial checks and exact remaining work, candidate SHA and
`save_by`; follow ctx-ticket-review's bounded retrieval and partial-save rules.
The independent reviewer still owes a complete AC matrix/verdict. All security,
merge and deployment controls remain in force, including source-security.
If the next attempt is interrupted, reconcile saved work but do not reopen that
target/phase again. Never reuse session/job evidence for another phase. Exhaustion needs a precise
maintenance/access handoff, not a recommendation to bypass independent review.

For the E11 repair, sync the coordinator helper/guides from reviewed workflow
maintenance into `ctx/epic-i11`, not the unchanged `ctx/ticket-i13` application
candidate. The flow reads trusted default-revision coordination code. Preserve
candidate `1e86671774206eb0cb7eb4c97867fc91a8c6a401`, its evidence and existing
checkpoint notes; only the next authorized native continuation creates a new
receipt/checkpoint. Publishing maintenance does not itself resume E11.

Decision D-E11-REVIEW-RESUME-1 (source #11 note 4032629864) narrows the earlier
published two-recovery policy. For checkpoint 4032513487, retain all 17 consumed
actions, E11-2 retry 1, repairs 0 and every event. A valid recovery of review
attempt 17 charges action 18; the following review claim charges action 19.
Do not edit that checkpoint or failure report 4032512218. Preserve candidate
1e866717 and the pinned manifest SHA-256; no ticket-branch helper sync is needed.

Legacy unmetered `interruption_resume` events remain replayable under their
original rules (including their original phases/cap); never rewrite or recharge
them. They count toward the new one-use cap. New CLI transitions always emit a
metered event; legacy events cannot follow a metered recovery. The compatibility
reader is not permission to append old-format events or hand-edit counters.
Remote checkpoint provenance and full history-prefix checks remain mandatory.

### Automatic CI scope and evidence recovery

Read [acceptance-evidence.md](acceptance-evidence.md). The worker prepares and
commits candidate context before verification/review; branch/plan identity selects
scope and manifest, whose criteria select browser checks. No manual CI switches
or variable-bearing Run pipeline links. A default-target epic MR has a separate
mandatory whole-epic scope gate; intermediate ticket evidence is not epic readiness.

For an idle v2 target blocked with `blocker_kind=evidence` at `verify`, `next`
returns `owner_action.action=reconcile_evidence`. The coordinator reads actual
current branch/MR, successful required CI jobs and full artifacts, then saves and
reads back a recovery report. A correct pipeline alone does not change the journal.
Once those observations supply a complete passing bundle, run:

```sh
python scripts/ctx_development.py resume-evidence .ctx/development/RUN.json TARGET --receipt RECOVERY.json
```

The receipt has exactly `run_id`, `target`, `phase: verify`, `blocked_attempt`,
`blocked_report_url`, `candidate_sha`, `report_url`, `report_readback: true`, and
`verification` (the complete existing bundle documented below). Bind the latest
recorded blocked attempt/report and the current target. The saved recovery note
must be newer than recorded source reports; its pipeline must be newer than
recorded verification pipelines for that target. Independently check actual remote
ownership, head, job/artifact results and provenance; monotonic IDs and JSON are
consistency checks, not authentication or evidence that a tool read occurred.

This appends a replayable event and reopens **verify**, not review/integration.
Persist/read back the full owner checkpoint, claim verify normally, then require
fresh independent review. Actions already consumed, transient retries, repairs,
manifest bytes, request identity, dependencies and history never reset. No active
claim, exhausted budget, wrong scope/SHA/hash, missing browser report, decision or
conflict can be bypassed. An unresolved prerequisite still checkpoints truthfully.

If separately authorized workflow maintenance changed the candidate SHA, add
`candidate_update` containing `previous_sha`, `reviewed_sha`, `changed_paths`,
`acceptance_manifest_sha256`, `review_url`, `authorization_url`, and
`remote_readback: true`. The previous SHA must equal the blocked candidate;
reviewed SHA must equal the new candidate. Every changed path must be in the
helper's exact `EVIDENCE_MAINTENANCE_PATHS` allowlist. The independent review must
be a readable same-project MR note for that exact maintenance candidate; human
maintenance authorization must have readable provenance on the source issue and
precede the recovery report. The coordinator verifies ancestry, COMPLETE diff,
exact paths/content, unchanged pinned manifest and actual authority/reviewer,
not just those receipt booleans. This adopts an already saved reviewed fix; it
does not give the executing agent permission to edit workflow policy.

When `.gitlab/ctx/verification-context.json` changed, include its exact saved
contents as `candidate_update.verification_context`; it must still identify the
same blocked project/epic/target. Confirm with the resolver at the new candidate.
No product code, plan/AC changes, command-adapter edits, credential/checkpoint
policy or unrelated changes may ride along. Those require their own authorized
repair/revision, not this transition. A same-SHA receipt cannot pretend a sync
never happened. A maintenance SHA change invalidates old verification/review;
the new bundle and subsequent independent application review remain mandatory.

### Resume after an actual human merge

If a reviewed ticket stopped at `integrate` with an evidence/access blocker,
`next.owner_action` requests `reconcile_integration`. The coordinator reads the
actual MR and current epic head, confirms the exact reviewed source was merged
into its mapped epic, and collects passing ticket-scoped post-merge CI/AC/browser
evidence. It must verify ownership and ancestry; a human's "merged" message alone
is not a receipt. A changed reviewed source or moved/unknown target is not silently
accepted. No merge command is issued by this recovery.

Publish/read back a fresh source report and run:

```sh
python scripts/ctx_development.py resume-integration .ctx/development/RUN.json TARGET --receipt MERGE_RECEIPT.json
```

The receipt binds `run_id`, `target`, `phase: integrate`, `blocked_attempt`,
`blocked_report_url`, unchanged reviewed `candidate_sha`, `report_url`, and
`report_readback`, `remote_readback`, `ownership_verified` all true. Its
`merge_request` contains the same-project `url` and `project_id`, `state: merged`,
mapped `source_branch`/`target_branch`, reviewed `source_sha`, observed `merge_sha`
and `target_head_sha`. Its `integration` contains `source_sha`, `epic_sha`, the
post-merge `pipeline_url`, saved independent `review_url`, and full `verification`
bundle for that target at the resulting epic SHA. The coordinator independently
reads every referenced fact; JSON booleans cannot establish remote truth.

This reopens integration in `read-only-reconciliation` mode, without marking the
ticket done, moving the recorded epic head or unlocking dependents. Persist/read
back, claim normally (consuming the normal action), recheck remote truth, and
record the exact observed integration. Do not run merge again, substitute another
candidate/result, reclassify the blocker or reset any counters/history. Existing
review and source verification remain bound to the original candidate; missing
post-merge evidence, active claims, exhausted budgets or uncertainty still block.

### Durable goal, bounded session

Use one approved objective and the native continuation protocol, not a new task
per technical finding. Save/read back small coherent worker increments before
`save_by`; partial saves never pass a phase. The admission helper's soft targets
do not cancel workers or prove a crash's cause. After a terminal interruption,
reconcile actual saved work and claims before adopting or retrying anything.
Keep a verified execution-limit checkpoint distinct from an application defect
or an abrupt session without verified checkpoint. No automatic chat wake-up,
recursive flow launch or budget renewal is installed by this change.

Tests passed, implementation saved, AC verified, independently reviewed and
integrated are separate milestones. Continue eligible technical work under the
same authorization; ask only at real product/access/approval/limit boundaries.
Project's next human instruction must name one exact action/control, not ask the
user to configure scope, diagnose logs or transfer reports between agents.

### Verification bundle

All managed workers obey the shared identity, authority and publication contract.
Leave the coordinator journal/project index, other tickets and foreign resources
alone. Only explicitly delegated integration/docs/close or an assembled-epic repair
may consolidate the named epic. Repair is permission for approved application/test
behavior, not workflow policy, CI, adapters, credentials, payments or deployment.
The coordinator owns state and checks remote evidence; reviewers remain read/comment
only. Write-capable workers retain their verified note URL in `.ctx/session.json`;
the coordinator persists the durable copy. Implementation, verification and review
run as separate fresh delegations.

### Verification receipt

The `verify` phase uses the existing browser component for **all** AC methods,
including backend tests and justified inspection. It does not skip backend-only
tickets. Run the reviewed application commands or observe their real CI jobs;
collect `.ctx/acceptance.json` and `.ctx/browser/acceptance.json` when applicable.
The operation report contains the common receipt plus this `verification` object:

```json
{
  "pipeline_id": "ACTUAL_PIPELINE_ID",
  "pipeline_url": "https://gitlab.com/PROJECT/-/pipelines/ACTUAL_PIPELINE_ID",
  "jobs": {
    "ctx:verify": {
      "project_id": "ACTUAL_PROJECT_ID",
      "source_sha": "ACTUAL_40_HEX_CANDIDATE_SHA",
      "pipeline_id": "ACTUAL_PIPELINE_ID",
      "status": "success",
      "allow_failure": false,
      "url": "https://gitlab.com/PROJECT/-/jobs/ACTUAL_JOB_ID"
    },
    "ctx:acceptance": "REPLACE_WITH_ITS_FULL_JOB_RECORD",
    "ctx:browser": "REPLACE_WITH_ITS_FULL_JOB_RECORD_IF_REQUIRED"
  },
  "acceptance": "REPLACE_WITH_FULL_PARSED_ACCEPTANCE_REPORT",
  "browser": "REPLACE_WITH_FULL_PARSED_BROWSER_REPORT_OR_NULL"
}
```

These are normalized **observed** job records, not fabricated metadata: obtain the
job's name, status, allow-failure setting, pipeline and commit SHA from GitLab and
confirm the project. Read the artifacts themselves. The helper checks mandatory
verify/acceptance job success, required browser success, current SHA/project/pipeline,
every scoped AC and method, raw-manifest hash and evidence links to their producer
jobs. IDs in reports are strings. Browser evidence must come from its separate
producer, not a builder's assertion. Test/browser URLs may name the corresponding
job, a `#` anchor or its `/artifacts/` path. Inspection needs its actual rationale/link.

Workflow self-tests cannot fill these records. Later delivery jobs are separate
gates; verify their outcomes before delivery, and never bypass mandatory MR controls.
The helper validates consistency, not the truth of network data or reviewer identity.
The coordinator must independently fetch it. A review receipt binds
`verification_url` to this saved report. Epic close binds `review_url` to the saved
independent whole-epic review. No old-SHA pass or review carries across a fix.

### Actionable defects and bounded repairs

For confirmed in-scope application/test/AC failures in `implementation`, `verify`,
`review` or `epic_review`, save a `blocked` receipt with `blocker_kind: defect`,
current `candidate_sha`, a clear `reason` and nonempty `findings`, for example:

```json
{
  "findings": [{
    "id": "budget-regression",
    "ac_ids": ["E2-2.AC1"],
    "summary": "Expected denial at exhausted allocation; observed successful dispatch",
    "evidence_url": "https://gitlab.com/PROJECT/-/jobs/ACTUAL_JOB_ID"
  }]
}
```

Each unique finding names ACs within the delegated scope and a same-project job,
artifact or issue/MR note with observed failure evidence. Expected red tests during
test preparation are not defects; actual assertions failing after implementation
are. Missing setup, unknown intent, stale/missing reports, permission failures and
uncertain writes are **not** defect classifications just because a job is red.

The supervisor verifies the findings, takes the target from `next.repairable`, then:

```sh
python scripts/ctx_development.py repair .ctx/development/RUN.json E2-2
python scripts/ctx_development.py claim .ctx/development/RUN.json E2-2
```

Persist/read back before delegation as usual. `repair` consumes one of three
repair cycles per target, preserves the failure history, invalidates passing
verification/review/integration receipts and schedules implementation. The worker
reproduces the defect using the smallest meaningful existing/new regression test,
fixes approved behavior, commits a **new** candidate SHA, and reports
`resolved_findings` containing all supplied finding IDs. That claim is still subject
to fresh full-scope tests/AC validation and independent review. If defects remain,
return evidenced findings rather than a passing claim. Never weaken ACs, delete
assertions, skip required checks or replace a real boundary with a mock to pass.

For an assembled-epic defect, implementation works on the owned non-default epic
consolidation branch. It preserves integrated ticket history, then returns through
docs, verification of **all** epic ACs, separate epic review and MR preparation.
Only this explicit repair delegation grants assembled-epic editing scope.

The three-cycle limit is cumulative across all failure phases for a target, not
reset by new commits. Every delegation also consumes the global 60-action budget;
preflight counts against the engine's 64. A no-op fix cannot advance. Exhaustion
checkpoints with remaining findings, attempted SHAs, receipts and precise next
action; it never reports completion. Keep processing unrelated ready targets.

## Persistent-objective addenda and decision application (local revision)

The request and acceptance manifest remain pinned. For a target-local technical
specification defect, return `blocked`, `blocker_kind=technical_design` and the
existing evidenced `findings`. `repair` schedules `design_revision` (design
worker), then `design_review` (separate epic-review worker), then fresh tests and
implementation for a ticket, or implementation for assembled-epic repair. It
invalidates old verification/review/integration receipts without deleting history.

The design receipt must contain a new `candidate_sha`, `resolved_findings`,
`affected_targets: [TARGET]`, exact `changed_paths`, and the unchanged
`acceptance_manifest_sha256`. Allowed paths are feature-local `spec.md`,
`technical.md`, `research.md` and that target's existing ticket document. The
review receipt binds `design_report_url` to the saved addendum report, the exact
candidate SHA, affected target and manifest hash. Read actual files/diffs and
check every contract consumer; a helper validating JSON does not establish
semantic correctness or independent review. Cross-target changes or changes to
approved intent/ACs require an explicit revision plan.

A genuine product blocker records `decisions: [{"id": "Q6", "question": "..."}]`.
Once authorized answers have been saved into scoped documents and read back:

```sh
python scripts/ctx_development.py resume-decision .ctx/development/RUN.json TARGET --receipt ANSWER_RECEIPT.json
```

The receipt contains `answers` (each with `id`, exact `question`, `answer`,
`source_url`), new `candidate_sha`, source `report_url`, `report_readback: true`,
`affected_targets`, `changed_paths` and unchanged `acceptance_manifest_sha256`.
All of that target's questions must be answered. The transition schedules
independent design review, not implementation or completion, and is replayed from
the append-only journal. In controller mode the checkpoint also supplies the
decision-application receipts described in [durable execution](durable-execution.md).

Use `ctx_development.pending_decisions` to read pending questions from the current
blocker receipt. Legacy node caches can retain answered questions for replay
compatibility; they are not the pending-question source. A new prose-only blocker
requires explicit question reconciliation, never reapplication of an old answer.

Technical addenda and decision application share the existing three-repair-cycle
limit per target and global action budget. They cannot reset retries, narrow
scope, weaken criteria or reuse old passing evidence. Legacy prose-only questions
must first be reconciled into explicit decision identities; do not guess answers.

## Activation and verification

1. Review and publish the repository helper, updated skills and flow definition.
   Preserve the old chain at `.gitlab/duo/legacy/ctx-development-single-ticket.yml`.
2. Validate locally and exercise the journal fixtures, including unrelated-work
   continuation, dependency blocking, stale/replayed receipts, narrow scope and limits.
3. Catalog publication/readback completed for v1.3.0 after MR !12. GitLab accepted
   the full definition; this is schema acceptance, not execution evidence.
4. Run a read-only/dry-run session to confirm actual supervisor availability and
   resolved scope. Configuration tests are not evidence that delegation ran live.
5. Use an explicitly authorized foundation slice for the first real execution.
   Verify actual delegation, worktree isolation, note readback, CI/acceptance and
   independent review. Application command adapters are still required.

Example human invocation after activation: use the existing enabled Development
mention/flow entry point on the source issue with `ctx-epic-run epic=2`, the design
commit/epic branch, and "advance all scoped tickets through review and integration;
prepare the epic MR; do not merge or deploy." Do not use that example to claim the
catalog acceptance proves successful single-shot execution.
