# CTX Project: the conversational project owner

Status: **local v1.0.0 candidate, not registered or enabled; no live smoke has run**.
The existing CTX Planning and CTX Design registrations remain unchanged and usable.
This is the unified conversational entry point, not a claim that the controller,
chat-to-controller bridge or development-to-design revision loop is operational.

## Preserve the original project-go behavior

The reference is the original at-project-go process: read project state, reconcile
reality, resolve necessary intent interactively, execute approved work, consolidate,
and reassess. Preserve the separation of interviews and background execution.
Do not port direct default-branch commits, implicit merges, unsafe cleanup or
unproven parallel fan-out. The current controller is single-epic and serial; project
assessment can cover more than one epic without authorizing their execution.

CTX Project applies Planning and Design procedures in the same conversation. It
does not call the separately registered chat agents as subagents. Those agents
remain optional specialist entry points during migration, not extra required steps.
The prompt explicitly loads the existing skills by mode; it does not copy their
full interview/contract bodies or create a new set of stage-named skills.

The native flow supplies actual design, test, implementation, verification and
review workers. The external controller persists attempts and launches bounded
sessions. The conversational agent owns intent and explanation, not the execution
journal, machine checkpoints or protected controller state.

## One conversation, distinct authority boundaries

- **Status:** read-only. Reconcile plan, issues, artifacts, branches, MRs, CI and
  available controller/session evidence. Do not publish a note, update the plan or
  start work just because the user asks "where are we?".
- **Planning:** investigate intent, deduplicate and preview scope/tickets/dependencies.
  Confirm the batch before creating or changing it. Detailed design can be pending.
- **Design:** keep the ordered interactive interview and ordinary draft saves.
  Ask only what the user must decide; complete technical document work yourself
  when ownership permits. Save feature-local specs/contracts and stable AC mappings.
- **Execution handoff:** record the requested scope and use the existing controller
  installation protocol. Design approval alone is not execution authorization.
- **Decision/resume:** read the actual question, capture its answer and affected
  scope, persist it with honest provenance, and retain the run's history/budgets.

"Go" is not permission to start the whole backlog. Resolve the objective/epic and
approved scope first. After each interview answer, reconcile/save the affected
artifacts, advance unblocked work and ask the next material question in the same
response. Do not ask for routine "continue" or another approval to save that answer.
Respect explicit plan-only, read-only and pause requests. A scoped product question
does not require the user to open a different agent.

## Shared state and evidence

Use the existing records, not a new competing project database:

1. `docs/plan/project.md` records objective, active work, backlog, decisions and
   handoff. Read the default revision, then reconcile unmerged epic-branch changes.
2. `docs/plan/E<epic-IID>/` records stable identities/dependencies and the Design
   progress cursor. Feature specs and `design.json`/`acceptance.json` bind intent
   to ticket criteria. Scope-only plans can legitimately lack design artifacts.
3. GitLab issues, commits, MRs, jobs and source-issue reports establish observed
   state. Paginate relevant results; read full linked reports. A green pipeline
   without application checks is not verified application acceptance.
4. `.ctx-controller/E<epic-IID>.json` on protected `ctx/controller-state` records
   controller ownership and progress. Chat may read it, never write it. Source
   checkpoint notes are read back with run/attempt/source/epic identity and SHA.

Each status claim names an exact SHA and evidence link where relevant. Keep
observed facts, unverified reports, proposed next work and authorization distinct.
No global "ready" flag: saved/specified/reviewed, execution-ready, MR-ready, merged
and deployed have different evidence. Current-SHA review is not a retrospective
pass for old work. Preserve historical merges while reconciling missing evidence.

An active writer owns its files and claims. Read notes, branch movement and
controller state before editing; if ownership is uncertain, do not race or replace
that work. Without a live session-read tool, chat cannot assert there are no other
runs. A missing controller file is not proof of no manual session. Report the
observed access limit and exact reconciliation owner/action, not a fabricated status.
Likewise enabled=true alone does not prove the scheduler is installed or running.

Read-only restart is a required smoke: a fresh CTX Project chat reconstructs the
same project state from those records, without asking the user to paste prior
conversation, without re-asking settled questions and without changing anything.

Project-plan writes remain on an explicitly authorized non-default branch. Keep
branch/revision provenance when reconciling several epics. Do not pick one epic's
stale project.md and overwrite other progress. Re-read before scoped edits; preserve
unrelated sections and use commit concurrency guards. Only approved/reconciled
scope may be persisted. An observed project-wide frontier is not a dispatched wave.

## Technical work versus user decisions

Classify an actual finding rather than trusting the words "blocked" or "design":

- **Technical defect:** inconsistent contracts, missing specified fields, wiring
  details, code/test failures. It is agent-owned within approved behavior and scope;
  repairs need fresh verification and independent review.
- **Research:** an external provider fact. The design research worker gets exact
  official URLs/questions, deliverable and safe disabled fallback. Unavailable
  facts stay unverified; account permissions/testing are separate access actions.
- **Product decision:** behavior, scope, budget authority, privacy/security policy
  or another consequential intent choice. Ask one focused question here, with a
  recommendation and impact. Never infer spending or access approval.
- **Access, ownership, approval or orchestration gap:** name the precise missing
  control, affected scope and remedy. Do not reclassify it as a product interview.

Do not send a user between agents to collect review text or choose technical
operations. Read the records yourself and continue unrelated permitted work.
Preserve stable finding/decision IDs and links across sessions. A chat-authored
decision report records the conversation; it is not authenticated controller-start
authorization or a GitLab merge approval.

The existing pre-execution design-closure loop already defines research, review
and document repair. **A general design revision after the execution journal is
pinned is not yet implemented.** It requires a versioned journal transition,
affected-evidence invalidation, independent re-review and restoration of the
affected ticket's phase without resetting budgets or changing approved intent.
Neither the project agent nor this document supplies that transition. Preserve
the existing journal and expose that exact boundary; never "fix" it by starting
a new run, editing the pinned request or dropping acceptance criteria.

## Execution connection: explicit current limitation

The candidate uses the existing 19-tool Planning capability set: GitLab reads,
scoped issues/comments, branches, commits and draft MRs. There is no shell, public
web tool, live session-list tool, controller-start/resume tool or external MCP server.
Path and intent restrictions are prompt rules; GitLab permissions remain essential.

When the [durable controller](durable-execution.md) is actually installed, use one
explicit default-branch pipeline action to initialize the scoped design-closure
or execute request. For a paused run, record the answer safely and use one explicit
resume action. Show verified identities/current SHA and preserve the existing run,
reservations and consumed limits. No automatic continuation is claimed until the
installation and live run prove it. If it is not installed, give that operator
setup action once, not a sequence of manual worker invocations.

The future chat-to-controller bridge is **not yet implemented**. It must authenticate
the requesting user, enforce project/scope/version/allowed-action checks, reject
duplicate/uncertain dispatch and leave controller credentials outside chat/agent CI.
An issue note or prompt cannot grant this authority. Do not expose an arbitrary HTTP
or shell tool as a shortcut. The current init/resume fallback remains explicit;
merely answering in chat does not wake the controller.

Worker continuation is the controller's job. Chat cannot remain alive unattended
or promise proactive push updates. Returning to CTX Project for status is read-only;
it must not create a new run. Merge, release and provider enablement remain separate.

## Publication and live acceptance

The candidate prompt and registration are `.gitlab/duo/agents/ctx-project.md` and
`ctx-project.json`. The catalog marks this entry as candidate; no catalog URL/version
or enabled state has been invented. Existing specialist prompts/registrations,
Development YAML and controller configuration are unchanged by this front-door work.

1. Review/merge the candidate and shared procedures. Check for an existing CTX
   Project catalog entry before creating one; update it if present. Publish the
   exact prompt, private visibility, listed tools and no external MCP servers.
2. Read back the entire saved prompt/tool set/version/enablement. Record actual
   catalog identity and hashes. Do not overwrite publication history or imply a
   repository push updates a catalog agent. Sync trusted instructions before use.
3. In an explicitly authorized scope, smoke status-only assessment, Planning batch
   confirmation, feature-level Design interview, coherent save/readback and next
   question in the same conversation. A plan-only request must stop at the plan.
4. Verify a read-only restart reconstructs decisions, artifacts and blockers. Test
   stale review at a newer SHA, an active/uncertain writer, missing session access,
   and an unavailable controller. None may cause a duplicate run or false completion.
5. With controller setup separately verified, test one init, automatic technical
   continuation, a genuine product question and one resume without resetting
   history. Retain job/session/note/SHA evidence. This step cannot claim the missing
   post-pinned-design revision or chat bridge works.
6. Only after the relevant smokes pass consider retiring standalone Planning/Design
   entry points with explicit operator approval. Keep rollback registration history.

Local prompt/registration checks are not proof of interview quality, tool-scoped
permissions, remote saves or live orchestration. Do not mark these smokes passed
from string tests, local CI or configuration acceptance.
