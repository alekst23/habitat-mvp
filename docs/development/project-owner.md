# CTX Project: the conversational project owner

Status: **v1.1.0 published and enabled on 2026-10-11 UTC**. Full prompt/tool/version
readback passed. The v1.0.0 chat picker was verified on 2026-10-10; subsequent E2
feedback motivated persistent objectives, saved decisions and stale-worker recovery.
The revised agent's behavioral acceptance remains pending.

## Open the agent

Open [CTX Project](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/automate/agents/1016538),
refresh GitLab, then choose **Add new chat → CTX Project**. No bot mention or slash
command is required. For the existing work, start read-only:

> Assess E2 using source issue #10 and MR !8. Reconcile the latest saved design,
> review and execution state. Tell me what is complete, the next agent-owned work,
> and decisions you need from me. Do not modify files, start execution or merge.

Then continue in that same chat:

> Continue E2 design here. Preserve prior decisions, ask only unresolved product
> questions, and save and verify feature-level specifications on the existing epic
> branch when no active writer owns them. Keep !8 open; do not implement.

This is the conversational entry point, not an activated autonomous execution
loop. The controller is still disabled; technical background dispatch and the
chat-to-controller bridge need separate setup and live validation.
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
that work. List Duo Sessions (project-filtered, paginated) and Get Duo Session
provide live read-only evidence for accessible runs. Listing excludes Duo Chat;
empty results cannot prove no other identities have active work. Missing access or
a missing controller file is not proof of no manual session. Report the
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

The local revision preserves one authorized objective across prerequisite design,
execution and repair. “Fully implement E2” is an execution objective, not a choice
between design and execution. Closed design remains a gate before code work;
finishing it does not require another “go.” Explicit design-only requests still
stop at design. Controller installation remains a separate operational boundary.

The journal now supports bounded target-local `technical_design` repair and
`resume-decision`, invalidating affected evidence and requiring independent design
review before fresh tests/implementation. It preserves the pinned request,
acceptance manifest and cumulative budgets. General cross-target or scope/AC
revision still requires an explicit plan; never start a new run to bypass it.

Distinguish decisions acknowledged in chat, queued for application, saved at a
verified SHA, and independently reviewed. Distinguish running/waiting sessions,
terminal failures and unreadable status. A failed reservation requires actual
session/head/diff/note reconciliation, not an indefinite “active” label or an
unverified claim that no other writers exist.

## Execution connection: explicit current limitation

The agent uses 21 tools: the 19-tool Planning capability set (GitLab reads,
scoped issues/comments, branches, commits and draft MRs), plus read-only List Duo
Sessions and Get Duo Session. There is no shell, public web tool, flow/session-start,
session-input, controller-start/resume tool or external MCP server.
Session-read coverage follows the [GitLab MCP tool contracts](https://docs.gitlab.com/user/model_context_protocol/mcp_server_tools/#list_duo_sessions).
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

The prompt and registration are `.gitlab/duo/agents/ctx-project.md` and
`ctx-project.json`. Source MR !23 merged after pipeline 2934622560 passed at
033dc8da20002486a6d18269b64e443191eebc20. Agent 1016538 v1.0.0 was private and
enabled in Showcase. Its complete saved prompt equaled that source with the final
newline trimmed; the record contains both hashes. All 21 tools, no external MCP
and the refreshed chat picker were verified. No model prompt was submitted during
that publication check; the subsequent user-supplied E2 transcript is behavioral
feedback, not a passed acceptance test for the revision.

MR !25 passed pipeline 2935078543 at e1788add0101097c797b7516d295e21c5175b2a9
and merged at d121a1ba5f4025b322bb2fb3fcdea2094c3b0538. On 2026-10-11 UTC,
Project v1.1.0 was published/enabled in the same entry. The full 17866-byte saved
prompt matches that source after final-newline normalization, with SHA-256
197e9f37dcc9483a7310d599290e0c1730cb2be2d6a790e4b773e2a6978ef8ff.
Private visibility, the same 21 tools and no external MCP were verified. Design
v1.7.0 and Development v1.6.0 were also published/read back. The 169 workflow
tests passed; no agent conversation or E2 execution was started. Specialists stay
enabled, controller stays disabled, and the chat dispatch bridge is not implemented.
The following live behavior checks remain required, not implied by publication:

1. For future updates, review/merge the prompt and shared procedures. Check for an existing CTX
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
   history. Include target-local technical design repair and decision application,
   stale failed-session recovery and continuation after design closes under an
   execute objective. Retain job/session/note/SHA evidence. This does not validate
   a chat bridge or unrestricted cross-target revision.
6. Only after the relevant smokes pass consider retiring standalone Planning/Design
   entry points with explicit operator approval. Keep rollback registration history.

Local prompt/registration checks are not proof of interview quality, tool-scoped
permissions, remote saves or live orchestration. Do not mark these smokes passed
from string tests, local CI or configuration acceptance.
