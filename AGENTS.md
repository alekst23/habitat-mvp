# Habitat development agents

## Current local workspace

On 2026-10-23 the current application was consolidated into `habitat-ai/habitat-mvp`
on local `main`, preserving the former `e11-epic-completion` working changes.
Use this checkout's `.venv`. Google Cloud delivery and the independent
`habitat-dev` implementation are archived outside this application checkout.
See `docs/development/repository-consolidation.md` for the migration record.
Historical publication and E11 acceptance records below apply to their named
revisions, not to every later application change. Local consolidation is not
remote merge, current CI acceptance, or deployment evidence.

## Project context

Read `docs/plan/E11/_epic.md` and `docs/design/README.md` for the current AICL
MVP scope and contracts, `docs/aicl-mvp.md` for running the application, and
`docs/plan/E11/completion.md` for candidate-specific evidence. E11 implements owner
controls and creation/management pages with simulated provider/work execution;
`docs/habitat-mvp.md` is the historical marketing/PayPal proposal. The GitLab
delivery workflow is separate from the customer-facing application. Read
`docs/hackathon-gitlab-workflows.md` for the nine-stage delivery plan.

## Workflow instructions

Current release: **Project v1.12.0 / Development v1.14.0**, published/read back
2026-10-17 UTC. See the interruption-evidence handoff release at the end of this
file and the normative Project/session and single-shot guides. Project collects
and transfers authenticated observed evidence; Development refreshes live gates
without demanding human log-line confirmation. Earlier release entries below
are history, not requests to republish or change existing recovery budgets.

Published/read back **Project v1.11.0 / Development v1.13.0** (2026-10-16 UTC).
Scoped maintenance D-E11-REVIEW-RESUME-1 supersedes the recovery policy below:
read single-shot-development.md. New `resume-interrupted` transitions allow only
verify/review, ONCE per target/phase, and consume one journal action before the
normal subsequent claim. Preserve old events/counters; legacy recoveries replay
unchanged but count toward this cap. No write-phase or defect recovery, changed
candidate/manifest/verification, application merge, E11 start or CI waiver.
Source !67 and coordinator-only E11 sync !68 merged with independent local review
and passing pipelines 2957153072/2957153152. Full saved prompt/YAML matches source
45d5719 after final-newline removal; tools/access/triggers unchanged. The ticket
stays 1e866717; checkpoint 4032513487 is untouched. Live recovery remains pending;
old release proofs below are historical, not the current transition policy.

Published/read back **Project v1.10.0 / Development v1.12.0** (2026-10-16 UTC):
read single-shot-development.md's interrupted-phase recovery protocol. Source !64
and coordinator-only E11 sync !65 passed CI and independent local review and merged.
`resume-interrupted` reopens only an unfinished read-only phase at the unchanged
candidate/manifest, after terminal session/job, ownership and missing-result
verification. Two recoveries per target/phase accumulate across SHAs/sessions;
old retries, repairs, actions and notes remain unchanged. A failed session can
have a successful wrapper job with a lost delegation stream; elapsed time alone
does not prove a hard limit. Reviewers use exact-SHA bounded retrieval and save
partial progress without claiming approval. Ticket ctx/ticket-i13 stays 1e866717;
no E11 continuation, checkpoint rewrite, application merge or deployment occurred.
The source-security application gate remains unconfigured and unwaived. Live
interrupted-review recovery remains pending. Earlier publication records below
are historical, not current versions or fresh runtime evidence.

Published/read back **Project v1.9.0 / Development v1.11.0** (2026-10-16 UTC):
read docs/development/automatic-acceptance.md. Acceptance scope/browser requirements
come from committed plan/branch/candidate context, not manual pipeline variables.
Persistent objectives retain budgets/history across sessions; supported evidence,
maintenance-adoption and human-integration recovery still require actual current-SHA
CI and independent review. Source !60 merged main f4c7f09; maintenance sync !61
merged E11 318d2883 and !62 merged the ticket ee86c6b2, all with passing CI and
independent local reviews. Native Duo reviews failed (502/review lock and 503),
not native approval. Full saved Project/Development definitions matched reviewed
source 4f56e11 after final-newline removal; unchanged tools, visibility, enablement,
service identity and triggers were read back. Numeric consumer 12316920 is retained
from its reviewed binding, not freshly API-queried; verify live eligibility before use.
Final ticket marker candidate 1e866717 passed independent full maintenance review
and local tests. Pipeline 2956291204 finished: workflow checks, 47 application tests
and E11-2 acceptance passed; browser was expected N/A, not browser execution.
The pipeline FAILED overall: source-security is unconfigured (exit 2), a remaining
gate, not a waived check. Maintenance review !59 note 4031054561 is not application
or native approval. Live journal recovery and independent ticket review remain pending. No E11
agent continuation, checkpoint/budget reset, application MR merge or deployment is
authorized by this publication record. Earlier version/publication statements below
are historical; their enduring scope, evidence and security controls still apply.

Checkpoint identity repair: read docs/development/checkpoint-publication.md.
GitLab composite OAuth may resolve `/user` to the triggering human. The helper
verifies the service-account OAuth owner and scoped-user binding using read-only
introspection; it does NOT accept personal tokens or human-authored checkpoints.
Use its safe `identity` diagnostic, never inspect/print tokens. No E11 continuation
is authorized by this maintenance change; preserve checkpoint 4019881978, notes,
budgets, exclusions and application MRs !45/!48. Catalog v1.10.0 is unchanged.

Model compatibility update (2026-10-15 UTC): read the first section of
docs/development/project-discovery.md before diagnosing recurring session filters.
GitLab's upstream GPT/Responses optional-argument defect has a merged, feature-flagged
gateway fix (!7436), but its companion rollout MR !261800 remained open. A bounded
same-chat comparison found GPT-6.1 Sol reporting required optional fields without
calling, while Claude Sonnet 5.5 - Default successfully sent the canonical request.
Do not claim the historical failed chat's model is known or that the upstream fix
is enabled here. Give the guide's exact model-switch/read-only-preflight instruction,
not a request to find a maintainer. No schema/permission bypass or E11 execution.
Project stays v1.8.0 with the same published prompt and tools; this is guide guidance,
not a new catalog release or proof of full preflight/launch.

Published/read back **Project v1.8.0** (2026-10-15 UTC): use the exact project-only
session-discovery payload, correct malformed read-only arguments once without
human intervention, and distinguish caller mistakes from proven platform failures.
Read docs/development/project-discovery.md. Source !54 merged at 33c6545e after
independent review and passing workflow CI. A fresh ordinary-Continue read-only
test omitted both filters and traversed two session pages; it did not reproduce
the old failure. Exact page-size compliance and unprompted full preflight were not
proven; failure-injection recovery and launch/input/re-entry remain pending.
No E11 execution, checkpoint, budget, credential, tool or merge/deployment change.

Previous **Project v1.7.0** repaired discovery using the existing 24 native tools,
not unavailable GraphQL. Read docs/development/project-discovery.md for the reviewed
project/consumer binding and release-time versus live evidence distinction.
Full catalog readback and a fresh discovery-only chat passed on 2026-10-15 UTC.
Source !52 merged main at eca18641 after independent review and passing workflow
checks; the unconfigured application verify failure remains a separate limitation.
Live launch/input/re-entry and application recovery are still pending.
No E11 continuation, checkpoint/budget/credential change, merge/deployment authority
or Development flow change. Preserve publication history and keep acceptance read-only.

Published/read back 2026-10-15 UTC: Project v1.6.0 requires one direct **Do this now**
instruction; Development v1.10.0 uses scripts/ctx_checkpoint.py read/assemble/publish
for file-based checkpoint transfer with exact readback. Read
docs/development/checkpoint-publication.md. Only seven reviewed E11 notes are
excluded by .gitlab/ctx/checkpoint-exclusions.json, without deleting evidence or
resetting history/budgets. Use the existing injected flow OAuth credential only
inside the reviewed helper, never a human/controller token or model-transcribed
payload. No new tools, scopes, controller or execution authority. Source !49 merged
main at 75442835; helper sync !50 merged E11 at 71016e8b without product/adapter
changes. Independent reviews and workflow CI passed; separate application verify
jobs failed. The user explicitly approved these workflow-only merges without
changing CI controls. Full saved catalog definitions match reviewed source 9522bf6c.
No application run started; live recovery acceptance remains pending. Older version
references below are historical; use checkpoint-publication.md for this release.

Published **Project v1.5.0** adds native session discovery/start/input and a
durable conversational handoff; read docs/development/project-session-handoff.md.
Full prompt/description, 24 tools, private visibility, no MCP and enablement were
read back on 2026-10-13 UTC. Source !42 passed CI and independent Duo review, merging
main at ec89eb3. Project starts approved Development work, returns a real session
link and handles **check progress** without copied commands/results. Status-only
remains read-only. One session mutation per user turn; native workers retain the
inner loop and cannot recursively start flows. Preserve scope, original authority,
cumulative budgets and explicit current approvals. No idle-chat auto-wake, duplicate
uncertain starts or controller activation. This narrowly supersedes the older
Project human-trigger-only statements below, not standalone Design/Planning limits.
Live launch/input/re-entry acceptance remains pending; no E2 run was started.

Previous rollout: Project v1.4.0 / Design v1.9.0 were published and enabled (2026-10-12 UTC).
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

Planning is conversational. **CTX Project v1.5.0** is published and enabled with
full catalog readback (2026-10-13 UTC); the chat picker was verified on v1.0.0.
The user's E2 progression defects motivated this revision; live behavioral proof remains pending.
It unifies Planning/Design procedures and project-status assessment in one chat;
read docs/development/project-owner.md. When using CTX Project, Planning
and Design are modes in the same conversation, not instructions to open another
agent. Status requests are read-only. Shared skills, evidence, scope and security
boundaries remain. Previous v1.4.0 had no flow-start tool; v1.5.0 adds only the
native session tools described above, with no shell or controller-write tool.
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
are for assessment only; writes stay with the controller. Direct native chat
dispatch is published in v1.5.0 as described above. Project v1.5.0 keeps one
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

All five E11 tickets are integrated into `ctx/epic-i11`. E11-5 source
`5960066639a243e617c17b42630655a7135045fc` passed all mandatory candidate jobs in
pipeline 2959692439 and independent review (issue #11 note 4036851846), then merged
through MR !76 at `ce3ddcce189ff923464c216859e6c8b8efaad56e`. Whole-epic acceptance
and final review are separate gates recorded on draft MR !45. See
`docs/plan/E11/completion.md`; do not infer readiness from historical E2 receipts. The application
has real SQLite-backed control behavior, magic-link authentication, wizard/chat
creation and management pages. OAuth providers, chat model and external work stay
fake-only. Runtime/provider enablement, PayPal and deployment are outside E11.

Historical catalog publication and live-validation records above and in the
implementation guides remain evidence for their named revisions. They do not
certify a newer application candidate or grant new execution/merge authority.

Workflow development commands (Python 3.12):

```sh
python -m pip install -r requirements-workflow.txt
python scripts/ctx_workflow.py validate
python -m unittest discover -s tests/workflow -v
python scripts/ctx_workflow.py waves docs/plan/E<epic-issue-iid>/state.json
```

The backend verification, acceptance, browser, source-security, packaging,
artifact-security and configuration-validation adapters are implemented and passed
real CI at the E11-5 source SHA above. Configuration validation is isolated and
applies no cloud configuration. Each new epic candidate still requires its own
mandatory jobs and independent review; source-ticket evidence is not final epic
acceptance or deployment evidence.
Workflow self-tests are not application tests. Workflow self-checks run automatically
on merge requests and the default branch; `CTX_WORKFLOW_CHECKS=1` also enables them
on other branches. Application checks activate automatically wherever committed
version-2 plans exist. Unconfigured adapters fail closed. Scope/manifest/browser
needs come from committed plan/branch identity, not manually supplied pipeline variables.
Read docs/development/acceptance-evidence.md. The candidate-data file
`.gitlab/ctx/verification-context.json` is the narrow exception to workflow-policy
write restrictions: ticket implementation runs `scripts/ctx_ci_context.py prepare`
and commits it before verification/review; epic docs runs `prepare --whole-epic`
before final verification. This does not authorize any other CI/policy changes.

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
# Interruption evidence handoff release (2026-10-17 UTC)

Project v1.12.0 / Development v1.14.0 are published and enabled, with complete
saved prompt/YAML readback matching reviewed source de2cec76 after final-newline
removal. Tools, visibility, service account, triggers and existing limits are
unchanged. Source !70 passed pipeline 2957542026 and independent local review
4033373727, merging main d9d78d12. Coordinator-only sync !71 passed pipeline
2957542093 and review 4033373771, merging ctx/epic-i11 abde5c05. Source/sync local
suites passed 248/253 tests. Old publication records below remain history.

Project owns evidence collection under docs/development/project-session-handoff.md.
Development consumes authenticated structured log_evidence under the single-shot
guide, refreshing live ownership/identity instead of requiring duplicate denied
log reads or human line-number confirmation. Source note4033375909 preserves the
directly observed session9621826/job17244915866 messages with honest maintainer
attribution; exact payload and server author were read back. This is not approval,
a current ownership grant or passing review. Native consumption remains pending.

No E11 run was started. Ticket1e866717 and checkpoint4032513487, all history/budgets,
product/plan/AC/manifest and CI controls remain untouched. One recovery per target
verify/review phase still costs one action plus the next claim; no refunds.
Application MRs !45/!59 were not merged; source-security stays unwaived. Maintenance
CI is not application acceptance. Resume the same authorized objective through a
fresh CTX Project chat; do not ask the user to collect technical evidence.
