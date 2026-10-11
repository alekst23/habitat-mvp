# CTX single-shot Development

**Local candidate v1.7.0 (not published): native multi-step execution is the default.**
One human invocation advances eligible phases/tickets, saving between delegations.
No controller, protected controller state, scheduler or new credential is required.
The published catalog is still v1.6.0 (one unit per session); merge/publication and
trusted helper synchronization must precede testing this candidate. Cross-session
auto-restart remains unavailable. [Durable execution](durable-execution.md) is optional,
deferred installation work, not a prerequisite for the native path.

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
   blocker, agent next, user action or none, and one copyable **resume** instruction
   with actual source/epic/branch, original run ID and checkpoint URL. A native resume
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
session**; a new trigger or issue-note answer cannot replace that control.

### Candidate smoke after publication

Use an explicitly authorized disposable epic to test one human invocation with no
controller configured: observe at least two delegations, a real failing AC followed
by a fix/new-SHA verification/independent review, then the next eligible ticket.
Check full source readbacks before/after each worker. Test a real product question
and one manual resume retaining run/manifest/history; test terminated-session
reconciliation without duplicating saved work. Stop on actual missing adapters or
permissions; preserve merge/deploy controls. Record session/job/note/SHA evidence.
These local changes and fixture tests do not count as that live smoke.

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
