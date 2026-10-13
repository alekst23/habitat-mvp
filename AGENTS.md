# Habitat development agents

## Project context

Read `docs/habitat-mvp.md` for the current product specification: a hosted
marketing-agent application with onboarding, delegated actions, and USD budgets.
The GitLab workflow builds and operates that application; it is separate from
the customer-facing agents. Read `docs/hackathon-gitlab-workflows.md` for the
nine-stage delivery plan.

## Workflow instructions

Local **Project v1.5.0 candidate** adds native session discovery/start/input and a
durable conversational handoff; read docs/development/project-session-handoff.md.
It is NOT published: live v1.4.0 still has 21 tools. After reviewed publication and
24-tool readback, Project starts approved Development work, returns a real session
link and handles **check progress** without copied commands/results. Status-only
remains read-only. One session mutation per user turn; native workers retain the
inner loop and cannot recursively start flows. Preserve scope, original authority,
cumulative budgets and explicit current approvals. No idle-chat auto-wake, duplicate
uncertain starts or controller activation. This narrowly supersedes the older
Project human-trigger-only statements below, not standalone Design/Planning limits.

Project v1.4.0 / Design v1.9.0 are published and enabled (2026-10-12 UTC).
Full saved prompts match reviewed source 0ab47996 after final-newline normalization;
private visibility, unchanged tools and no external MCP were read back. Source
MR !39 passed CI and independent Duo review, merging main at 661e5fdd. Publication
did not change the E2 branch or start execution; no helper synchronization is needed
for these chat-only prompt/shared-default-branch guide changes.
Read docs/development/next-action.md: do authorized work or give the exact required
human action in the same response as the result. Preserve read-only status, scoped
closure loops, cumulative budgets and human-triggered dispatch. Transcript-derived
live acceptance is pending; local prompt tests cannot prove conversational behavior.

Development v1.9.0 is published/enabled (2026-10-12 UTC): ctx_owner.py emits visible
handoff markers and explicitly migrates verified marker-stripped legacy notes.
Follow single-shot-development.md's recovery section; preserve full state and exact
readback. Source !35 and E2 helper sync !36 passed CI and independent Duo review,
merging at 9deb5530 and 9b4e8810. Full saved catalog YAML matches source 25649246
after final-newline normalization. E2 product docs/plan are unchanged from df380b13;
MR !8 stayed open. Project was then v1.3.0. References to v1.8.0 below are historical.
Actual note-tool migration/delegation remains unverified; no execution was launched.

Published resumable owner (Project v1.3.0 / Development v1.8.0): follow the handoff section
in docs/development/single-shot-development.md. A short continue request restores
the approved objective from source notes; scripts/ctx_owner.py validates the full
native handoff and scripts/ctx_development.py derives owner_action. Technical
recovery belongs to the supervisor, not the user. Preserve scope/history/answers/
budgets and current permission/merge gates. MR !31 merged main at 56d930d5; helper
sync !32 merged E2 at cbd92690. Both CI and independent follow-up reviews passed;
full catalog content/tools/enablement readback passed on 2026-10-11 UTC. Prior
version references below are historical. Live two-run acceptance remains pending.

Read `docs/development/ctx-contract.md` for the agreed workflow and
`docs/hackathon-gitlab-workflows.md` for the operation catalog and stage coverage.
Preserve the original issue, specification, epic, ticket, design, test, review,
and close operations under the `ctx-` prefix. Add the six delivery operations
listed there. Lifecycle stages classify evidence; they do not define agent or
operation boundaries.

Planning is conversational. **CTX Project v1.4.0** is published and enabled with
full catalog readback (2026-10-12 UTC); the chat picker was verified on v1.0.0.
The user's E2 progression defects motivated this revision; live behavioral proof remains pending.
It unifies Planning/Design procedures and project-status assessment in one chat;
read docs/development/project-owner.md. When using CTX Project, Planning
and Design are modes in the same conversation, not instructions to open another
agent. Status requests are read-only. Shared skills, evidence, scope and security
boundaries remain; published v1.4.0 has no shell, flow-start or controller-write tool.
The v1.5.0 candidate changes only the Project session handoff as described above.
CTX Planning and CTX Design remain available; do not retire them before live acceptance.
The two background flow entry points are `ctx-development` and `ctx-delivery` in
`.gitlab/duo/flows/`. Reusable instructions live in `skills/ctx-*/SKILL.md`;
`.gitlab/ctx/catalog.json` records the active entry points and operation mappings.
Read the named skills before acting. Do not register a bot/flow for every skill.
The retired `ctx-planning.yml` remains for historical regression tests and rollback,
not publication or normal use. Its successful earlier runs remain valid history.
Superseded ticket/epic/project definitions are retained in `.gitlab/duo/legacy/`.
Read `docs/development/gitlab-workflow.md` for activation and implementation limits.

The published Development revision is a bounded single-shot Duo supervisor; read
`docs/development/single-shot-development.md` before changing or running it. It
advances all explicitly scoped work through delegated SDLC phases, with an explicit
serial fallback (native parallel execution is unverified). Its progress journal
does not grant authority or attest evidence; remote review/CI/ancestry must still
be checked. Preserve ticket-only scope, respect active runs, and keep durable
checkpoints. Development v1.8.0 is published and enabled; full catalog YAML readback
passed after MR !31 merged. MR !32 synchronized E2 helpers without changing product
specs/plan; independent review confirmed marker escaping and trusted note authors.
Controller installation is NOT required. The historical v1.2.0 run stopped at preflight; delegated
ticket processing and the repair loop still need live validation. New runs use the
version-2 journal: pin the exact AC manifest, repair
actionable defects up to three times per target, and require fresh application/AC
verification plus independent review after every fix. Missing infrastructure, intent
or authority is still a blocker; no agent-driven flow retriggers or policy weakening.

Native execution is the default for this revision: repeated delegated phases/tickets
within one human-triggered session, up to 64 delegations and the admission clock in
single-shot-development.md. Save/read back every result, then reassess and continue;
an intermediate checkpoint is not a final response. Preserve cumulative run budgets
and explicit scope. Workers save coherent increments by their save_by soft target.
Do not implement in the coordinator or assume native cross-session auto-restart.
At a real blocker/runtime stop, provide one precise human resume with saved state.
The optional controller remains disabled/deferred; only a verified controller
envelope uses durable-execution.md's one-unit compatibility protocol. Do not demand
admin protection/credential/scheduler setup for ordinary native execution. Never
expose controller tokens to agents or let them write ctx/controller-state.

CTX Planning and CTX Design prompts/registration records live in
`.gitlab/duo/agents/`. The order is Planning -> Design -> Development. Planning
publishes approved scope, epics, tickets, dependencies and state, marking Design
pending. Design interviews and commits specs, technical/ticket design and the
acceptance manifest on the epic branch, verifying files at the returned commit SHA.
Design owns progression across the scoped session: map independent features,
interview, specify contracts, reconcile tickets/ACs, self-check and hand off. After
each answer, advance unblocked work and ask the next question in the same response
as the save receipt; no routine "continue" prompts. Track Design progress in the
epic, use feature-local spec/technical pairs and version-2 design.json mappings,
and preserve IDs/decisions when splitting old umbrella documents. Version-1 designs
remain readable as legacy_unclassified; semantic feature boundaries need review.
An issue note reports that save; it does not replace it. Neither starts
implementation or flows. Both return ordinary prose and wait when asking a question
or facing a real blocker, not merely after a routine Design checkpoint;
terminal-token and checkpoint/abort rules apply to ambient components, not chat.
Neither chat agent has a shell: helper validation requires actual runner/human
evidence. Pending checks do not prevent scope/design saves or design conversation,
but must not be reported as implementation readiness. Only real scope/decomposition
changes return to Planning; never send users there merely to save Design's work.

The CTX Project agent follows the same order and artifact ownership as modes
within one chat. It uses the existing interview/planning/design skills directly,
not the standalone registrations as subagents. Reads of protected controller state
are for assessment only; writes stay with the controller. Missing direct chat
dispatch is an unpublished v1.5.0 candidate as described above. The published revision keeps one
approved objective across design/execution, verifies answer application, reconciles
terminal reservations and supports bounded target-local technical design addenda
through independent re-review. Pinned ACs/history/budgets stay intact; cross-target
or scope-changing revisions need a separate plan. None of this activates the controller.

Read docs/development/design-readiness.md for restored interview/contract/wiring
requirements and docs/development/design-closure.md for Design-owned review,
public-documentation research and bounded document repair. Specified means a
review candidate, not Design complete. The existing supervisor's explicit
mode=design-closure cannot claim tickets or implement the app; it ends with a
verified checkpoint after closure or a precise decision/access blocker. The new
Design v1.8.0/Development v1.7.0 are published/enabled with full readback; native
design-closure behavior still needs the live test in that guide.
Generated E-numbered plans and design handoffs are checked by
scripts/ctx_design.py in CI. Structural checks do not replace independent semantic
design review. Chat Design owns typed contract documentation; Development's design
worker creates/reuses executable contract stubs and minimal port fakes before tests.
The completion repair adds --handoff for specified design with explicit later
gates; --ready remains all-clear and conservative. The runner obtains independent
design review/repair under Design ownership, then historical execution reviews
before ticket claims, publishing source-issue receipts.
Missing execution/enablement evidence alone does not keep complete design in draft.
Historical rollout: CTX Design v1.6.0 and Development v1.5.0 were read back on 2026-10-09 UTC; native
behavior validation remains pending. Workflow MR !20 merged into main at 2ffcb740;
helper-sync MR !21 merged into ctx/epic-i2 at 849c3450. Both pipelines passed, as
did 139 local workflow tests. This synchronization did not change E2 product docs.
Six canonical feature pairs, 48 scenarios, 14 criteria and ticket states remain intact. The handoff
check passes while Q2 enablement and E2-1 remain open. No chat/flow was launched,
and product MR !8 has not been merged by this repair.
The revised Planning prompt remains a publication candidate; do not infer activation
or successful execution merely from merge or catalog acceptance.

Before publishing issue/MR descriptions or comments, follow "Publishing GitLab
Markdown" in `docs/development/ctx-contract.md`: use real multiline Markdown,
serialize only once, and read back the saved body and links before reporting success.

## Lean testing and acceptance

Write the absolute minimum meaningful tests needed to prove the changed behavior
and its material risks. Reuse existing coverage; one test may prove several ACs.
Prefer a focused test at the lowest sufficient layer, small fixtures and direct
observable assertions. No test-per-function/AC quotas, coverage-percentage targets,
duplicated test layers, speculative matrices or assertion-free smoke tests.
Do not delete unrelated tests. Documentation-only changes can use justified
inspection; behavioral changes need a valid red baseline and final passing evidence.

Review every AC against its committed acceptance manifest, current SHA and actual
evidence. UI criteria need real browser evidence, not just code inspection or a
green unit-test job. Missing/skipped/stale checks block completion. See
`docs/development/acceptance-evidence.md` and `docs/development/browser-checks.md`.

## Product invariants

- Derive tenant identity from authentication; never trust a tenant ID from a tool payload.
- Reserve the bounded maximum cost before billable dispatch. Unknown prices,
  missing policy, failed authorization, or uncertain quota checks deny dispatch.
- Agents may propose actions but cannot approve themselves or widen authority.
- Keep provider, payment, deployment, and connection secrets in the designated
  control-plane services, outside agent context and runtime.
- Preserve idempotency, outstanding reservations for unknown outcomes, and the
  append-only activity record. Sandbox receipts do not increase real cost limits.
- Development checks use fixtures, test accounts, or explicitly authorized staging
  resources. Live ads, payments, and customer actions are not development tests.

## Current implementation status

The earlier planning flow ran successfully. CTX Planning now replaces that entry
point with chat; CTX Design supports detailed design interviews. Their read-only
chat behavior is live-tested, but approved planning writes still need a live test.
Design saved E2 artifacts in MR !8; this repair addresses their incomplete contracts
and inconsistent state/acceptance mappings, rather than claiming save alone suffices.
Revised development/delivery definitions have separate publication/live-validation
status in the implementation guide. Local workflow validation, dependency-wave
planning and fail-closed evidence adapters are provided.

Workflow development commands (Python 3.12):

```sh
python -m pip install -r requirements-workflow.txt
python scripts/ctx_workflow.py validate
python -m unittest discover -s tests/workflow -v
python scripts/ctx_workflow.py waves docs/plan/E<epic-issue-iid>/state.json
```

Application install/test/build/scan/deployment adapters are not configured yet.
The acceptance validator and browser CI harness exist; the latter still needs the
application, its pinned Playwright dependency, startup command and real UI tests.
Establish reviewed argument arrays and evidence writers in `.gitlab/ctx/commands.yml`
as part of the application foundation. `python scripts/ctx_workflow.py run verify`
currently returns blocked (exit 2), correctly. Workflow self-tests are not application
tests. Workflow self-checks run automatically on merge requests and the default
branch; `CTX_WORKFLOW_CHECKS=1` also enables them on other branches. Set
`CTX_APPLICATION_CHECKS=1` for the application CI lane; until configured,
its first job fails closed. Make the lane mandatory before implementation MRs merge.

The application lane's `ctx:delivery-readiness` job collects prerequisite receipts
and produces a nine-stage evidence summary, even for incomplete candidates. Read
`docs/development/delivery-readiness.md`. Receipt consistency cannot attest real
jobs or authorize deployments; actual CI, control and approval readback is required.

Agents may edit scoped planning/application files on ticket/epic branches, create
issues/MRs and publish redacted evidence. They may not change workflow policy,
CI controls, command adapters or runner configuration to make a failing check pass;
those require an explicitly scoped foundation/policy change and independent review.
Never push directly to default, force-push, self-approve, expose secrets or deploy
from an agent session. Do not add deployment credentials before protected target
and approver controls have been configured and verified.
