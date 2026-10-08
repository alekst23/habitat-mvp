# CTX single-shot Development

Status: published as CTX Development v1.2.0 on 2026-10-08 UTC (October 7 Eastern),
after repository helpers landed through MR !6. Full saved YAML readback matched
the tested source except for GitLab trimming its final newline. Private visibility,
enabled state, service account and triggers were preserved. No application work or
flow run was dispatched; native execution still requires validation.

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
| Final consolidation | Docs, current-SHA whole-epic review, then MR preparation |
| Durable project state | Coordinator updates approved non-default branch and verifies source-issue checkpoint |
| Safe cleanup | Explicit ownership manifest, no force removal, no cleanup of dirty/foreign work |

We deliberately do not port direct commits to main, automatic merges/releases,
force/glob cleanup, arbitrary backlog expansion or merging partial unreviewed work.
Existing GitLab identity, evidence and protected-merge rules take precedence.

## One invocation, multiple delegations

The existing `ctx-development` entry point becomes an `AgentComponent` supervisor
using `subagents`, `delegate_task`, `final_response_tool` and `max_delegations: 64`.
GitLab documents these in its [flow registry](https://docs.gitlab.com/user/duo_agent_platform/flows/claude-edit-v1-flow-registry/).
No extra flow/bot is registered for each skill, ticket or reviewer. Review remains
a separate read/comment-only component, not GitLab MR approval.

The supervisor delegates these phases for each ready ticket:

```text
committed-design preflight → minimal red tests → implementation
    → browser/acceptance evidence → independent review → verified integration
    → reassess ready frontier and continue in the SAME session

all epic tickets integrated → documentation → whole-epic review → MR-ready
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
  "version": 1,
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
      "design_sha": "REPLACE_WITH_VERIFIED_40_HEX_DESIGN_SHA"
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

Run from the trusted coordinator checkout, not a mutable ticket worktree:

```sh
python scripts/ctx_development.py init .ctx/development/RUN.json .ctx/development/RUN.request.json
python scripts/ctx_development.py next .ctx/development/RUN.json
python scripts/ctx_development.py claim .ctx/development/RUN.json E2-1
# Delegate the returned phase with the exact active identity and worktree.
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
`report_url`, `report_readback: true`, and `candidate_sha` for success. The supervisor
must actually read the note; it cannot invent that boolean. Integration additionally
requires `integration` with `source_sha`, `epic_sha`, `pipeline_url`, and the previously
recorded independent `review_url`. Report URLs must name the run's source issue.

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
`ci_pending`, `transient` or `conflict`. Unrelated work remains eligible. A waiting
or transient target can receive one reconciled retry using a freshly observed
same-project pipeline/report URL:

```sh
python scripts/ctx_development.py retry .ctx/development/RUN.json E2-1 --observation-url VERIFIED_URL
```

This is not a retry of an uncertain write, an automatic code-repair loop, or proof
that a supplied URL was visited. The supervisor must inspect the new evidence.
The journal stops at 60 actions, below the engine's 64-delegation cap. A budget,
unresolved CI wait, decision or conflict results in a truthful durable checkpoint.
The invocation may span multiple tickets but cannot promise unlimited execution.

The supervisor's final token is `complete`, `checkpoint` or `blocked`. Its existing
deterministic routing adapter normalizes that one final response. Managed workers
return to the supervisor, not through standalone graph routers. `checkpoint` ends
the session successfully without asserting the implementation is complete.

## Activation and verification

1. Review and publish the repository helper, updated skills and flow definition.
   Preserve the old chain at `.gitlab/duo/legacy/ctx-development-single-ticket.yml`.
2. Validate locally and exercise the journal fixtures, including unrelated-work
   continuation, dependency blocking, stale/replayed receipts, narrow scope and limits.
3. Catalog publication/readback completed for v1.2.0. GitLab accepted managed agents
   and the delegation bound; this is schema acceptance, not execution evidence.
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
