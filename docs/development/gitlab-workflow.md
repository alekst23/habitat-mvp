# CTX native GitLab workflow implementation

## Status and boundaries

Design repair (2026-10-08): restored interview/technical-contract/wiring
procedures, generated-artifact CI checks and explicit Development contract-stub
preparation. Read [design handoff requirements](design-readiness.md). Planning
v1.1.0 remains published, with its repair candidate pending catalog publication.
Development v1.3.0 is published/enabled after MR !12 merged at `04a57ddb`; its full
YAML readback matches the tested source except the final newline. It adds bounded
repair and strict current-SHA AC verification. CTX Design v1.3.0 is also published/enabled; its full saved prompt
matches the merged source. Private visibility, tools and external-server settings
were unchanged. Subsequent MR !8/chat inspection found fragmented continuation and
one umbrella feature pair. **Design v1.4.0 is now a local publication candidate**:
guided progression, explicit feature/ticket mapping, feature-local documents and
clear pause/completion rules. It is not yet the registered prompt, and this repair
does not reorganize !8 while its Design chat has a pending write. See
[session/layout and publication requirements](design-readiness.md).

Workflow [MR !9](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/9)
merged into main at 090d153. E2 repair
[MR !10](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/10)
merged into ctx/epic-i2 at 2578695, including the updated helpers. Both MR pipelines
passed; the E2 check covers 46 scenarios and 14 criteria. MR !8 remains an open draft.
These are structural checks, not independent semantic approval or application tests.

Live evidence since the earlier setup checks: MR !8 saved E2 ticket designs at
89c3018, but its state/manifest and design completeness were defective. Development
session 9174694 stopped at preflight with no worker delegation. The repair validates
saved artifacts, not just registration wording; it does not turn old runs into passes.

Planning originally ran successfully through `/flow:ctx-planning`, as confirmed
by the user. That background entry point is now retired in favor of the
conversational **CTX Planning** agent. CTX Design is the detailed interview/design
partner; development and delivery remain background flows. The review-routing
correction was published to Showcase's
CTX Development catalog entry as v1.1.0 on 2026-10-07; its saved YAML was read back
and matched the tested local definition. This was superseded by the single-shot
supervisor v1.2.0 on 2026-10-08 UTC, after MR !6 merged. Its saved YAML was read
back in full (only the trailing newline was trimmed). Its observed native run stopped
at preflight; delegated ticket execution remains unverified. Other limits remain separate
from catalog acceptance. No external Claude runner is used. Duo runs
the native flow definitions in its CI execution environment. Normal GitLab CI jobs
run deterministic workflow checks and, once configured, application adapters.

| Native flow | Preserved process | Current boundary |
|---|---|---|
| CTX Planning chat agent | Scope interview → epic/tickets, dependencies and plan state | Publish approved scope first; detailed design follows |
| CTX Design chat agent | Design interview → committed spec, technical/ticket design and acceptance manifest | Owns file persistence/readback; no implementation or flow start |
| `.gitlab/duo/flows/ctx-development.yml` | Single-shot supervisor → ticket SDLC/repair → reassess → epic validation/repair/MR | Published v1.3.0; serial fallback; historical preflight observed, delegated repair execution unverified |
| `.gitlab/duo/flows/ctx-delivery.yml` | Six delivery operations, stage evidence and candidate readiness review | Read/comment only; application adapters and deployment/approval integration are missing |

Each of the 30 procedures is a repo skill at `skills/ctx-*/SKILL.md`, explicitly
referenced by its agent/flow prompt. Skills supply instructions; agent registrations
and flow components supply tool permissions. Active entry points are two chat
agents and two background flows, not one registration per procedure. The retired
planning YAML and its catalog operation mapping remain for regression tests and
rollback; do not republish or invoke it. The validator's count of three YAML flow
definitions includes this retained historical definition, not three active flows.
The superseded ticket/epic/project YAML is preserved under `.gitlab/duo/legacy/`
for reference, not registration. The operation-to-flow mapping is
`.gitlab/ctx/catalog.json`. Stages classify
evidence; they do not determine agent boundaries. Read the full contract in
`ctx-contract.md` and the prize coverage plan in `../hackathon-gitlab-workflows.md`.

## CTX Planning: scope and tickets first

[CTX Planning](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/automate/agents/1016257)
owns scope, epics, tickets, dependencies and planning state. Its five procedures
are project design, intake, triage, epic creation and ticket creation. Open
**Add new chat → CTX Planning**, provide the source issue, review its scope and
decomposition preview, then say **"Publish this plan."**

It saves the approved plan on the verified non-default epic branch, preserves
`E2-1` identities and real issue-IID mappings, verifies artifacts, and reports
**scope saved; design pending**. Detailed specs and a final acceptance manifest
are not prerequisites for creating tickets. Existing designs/evidence survive replans.
Next open CTX Design with the saved plan/epic/commit links—not Development directly.

The exact prompt/registration are `.gitlab/duo/agents/ctx-planning.md` and
`ctx-planning.json`. Its 19 tools allow remote reads, issue publication, branches,
commits and draft MRs. No command, merge or flow/pipeline-start tool is selected.
No shell means helper validation must be reported pending without real evidence;
that does not prevent publication or proceeding to the design conversation.

The old Showcase planning flow (catalog `1016235`) and its trigger were disabled
on 2026-10-07. Its definition/history remain for rollback; no issues/branches were
deleted. The historical project was untouched. Do not re-enable it for normal use.

## CTX Design: owns specifications and saving

[CTX Design](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/automate/agents/1016255)
runs **after Planning and before Development**. It applies `ctx-spec-interview`,
`ctx-epic-design` and `ctx-ticket-design` across all scoped tickets in an epic.

It owns the behavioral spec, technical design when needed, ticket Design sections
and final acceptance manifest. It commits these files on the existing epic branch,
reads each file back at the returned commit SHA, then posts a report linking the
saved files/commit. A note or chat answer is not a saved specification.

A scoped design request authorizes routine design-document saves unless the user
explicitly requests read-only brainstorming. Useful draft checkpoints can be saved
with open questions clearly marked. Unresolved decisions block dependent execution,
not persistence. A direct "save" request should not cause another approval loop.

The v1.4.0 candidate also owns progression after each answer: save/read back,
advance unblocked work, then ask the next question in the same response. Its
_epic.md Design progress cursor tracks feature-level behavior/contracts/AC mapping
and the next action. Distinct capabilities use separate concept directories, with
version-2 design.json mapping them to tickets. Shared contracts are linked, not
copied. Routine saves do not end the session or require another "continue".
Configured GitLab tool approvals still apply; prompt changes do not bypass them.

After the candidate is merged, trusted epic helpers synchronized and the existing
agent republished/read back, start a **new chat → CTX Design** with the plan:

> Design the scoped tickets for this epic. Read the existing plan and design note,
> reuse settled decisions, map the distinct features, and guide me through only
> unresolved choices. After each answer, advance the design and ask the next
> question without waiting for "continue". Save feature-local specs/technical
> designs, ticket Design sections and the acceptance manifest on the
> existing epic branch. Verify saved files and return their links and commit SHA.
> Preserve scenario/AC IDs when reorganizing existing documents. Do not implement
> or start a flow.

For existing E2, supply the verified epic/source/note links instead of recreating
the plan. The agent must verify the source issue separately from epic #2. Only
real scope/decomposition changes go back to Planning; never a request merely to
save design. Next is human-invoked Development with the saved design revision.

The prompt/registration are `.gitlab/duo/agents/ctx-design.md` and
`ctx-design.json`. Its revised 18-tool set adds branch/commit/draft-MR publication,
existing-issue updates and branch/MR/pipeline reads. It cannot create new issues,
execute shell commands, merge or start flows. No external MCP server is configured.

Both agents are private and project-enabled. These restrictions are prompt rules,
not tool-level path/project permissions; underlying GitLab access controls remain
essential. Commits/MRs may cause ordinary repository pipelines. The exact published
version, prompt digest and verification status are tracked in each JSON record.
Publishing repository files alone does not update the registered agent. New chats
avoid carrying old handoff instructions forward; chats do not implicitly share memory.

Published 2026-10-07: Design **v1.2.0**, Planning **v1.1.0**. Their full prompts,
tool sets, private visibility, enablement and updated chat-picker entries were
read back and matched. A fresh read-only Design chat correctly described its own
commit/readback responsibility, draft saves and no detour to Planning/Development.
A fresh Planning chat confirmed scope/tickets first, Design pending, and Design
ownership of specification publication. Neither smoke test changed product artifacts.
Those configuration/conversation checks alone did not prove write behavior.
Subsequent MR !8 demonstrates saved Design artifacts, but not a complete, valid
design handoff. The repaired agent and an approved Planning batch still need live
verification. Do not create fake product decisions just to smoke-test saving.

### Single-shot Development: local supervisor revision

The local flow now owns a complete invocation across explicitly scoped tickets/epics.
It delegates separate SDLC phases, continues after integration, isolates blockers,
and performs final epic docs/review/MR preparation. The progress helper pins scope,
stage order, active claims, candidate SHAs and bounded retries. It does not replace
independent remote evidence or merge controls. The original process is parallel by
default; this revision honestly uses a serial runtime fallback, not full parallel
parity. See [the implementation and activation protocol](single-shot-development.md).

Published Development v1.3.0 closes the development loop with version-2
requests: exact committed AC manifests, complete verification receipts, and up to
three scoped defect repairs per ticket or assembled epic. Each fix returns through
current-SHA testing/AC validation and a fresh independent review. Missing setup,
intent, permissions or evidence still blocks; global action limits and durable
checkpoints remain. Existing journals retain their version-1 rules. Local fixtures
exercise the loop; real application adapters and a live catalog run remain required.

Development v1.3.0 is now registered and enabled. GitLab rejected the initially
configured `on_delegation_error`; removing that unsupported UI logging event let
catalog validation pass. The local validator now checks the accepted event enum.
Private visibility, the service account and active triggers were preserved. The
old single-ticket chain remains under
`.gitlab/duo/legacy/ctx-development-single-ticket.yml` for regression tests/rollback.

## What is executable now

Using Python 3.12 in an isolated environment:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-workflow.txt
.venv/bin/python scripts/ctx_workflow.py validate
.venv/bin/python -m unittest discover -s tests/workflow -v
```

The local validator checks our supported custom-flow subset, prompt inputs,
restricted fields, reachable/acyclic routing, fail-closed status routes, reviewer
tool separation, catalog coverage and CI evidence dependencies. It also requires
each routed prompt's explicit `Terminal tokens: [...]` declaration to equal its
router's keys (excluding `default_route`) and catalog `terminal_tokens`. Managed
agents match `managed_terminal_tokens` and return to their sole bounded supervisor,
without standalone routers. Required skills with explicit terminal-token declarations may
only use tokens accepted by their consuming component. It is not a copy
of GitLab's server-side schema and cannot prove tool availability or authorization.
Official catalog validation and GitLab CI lint remain required.

The supervisor's final routing and standalone graphs fail closed on unknown or
blocked results. A managed worker's blocked result checkpoints that target while
unrelated ready work continues in the supervisor. Flow components post detailed
operation reports to the source issue before returning a routing token. A GitLab
session ending in `abort` can mean a documented missing prerequisite, not a crash.
Resume with the explicit operation after resolving a genuine blocker. No flow
automatically retriggers another flow. Historical v1.2.0 lacks the new bounded repair
loop; published v1.3.0 repairs evidenced scoped defects internally
in the same supervisor session, then re-verifies and obtains independent review.

### Final results are not handoff destinations

Producer contract: post the complete operation report to the source issue/work
item, read the saved note back by ID, verify its body/identity/SHA/links and retain
the note URL in the durable handoff. Then emit exactly one allowed token with no
Markdown or extra prose. Failed publication/readback requires `blocked`.

Consumer contract: `scripts/ctx_routing.py` returns a structured result containing
`routing_token` and `informational_output`. It accepts either a strict JSON object
with those fields, or the last non-empty line of a text response. Surrounding
whitespace is normalized; earlier prose is information, not a routing failure.
Different standalone routing tokens outside code examples, mixed JSON/plain
signals, duplicate JSON fields, unknown fields/tokens and trailing prose are
rejected. The routing token itself must be outside code fences. No aliases,
case-folding or guesses at intent are allowed.

Every agent is followed by three fixed `DeterministicStepComponent` steps:

1. `<agent>_routing_prepare` refuses an existing/symlinked scratch path.
2. `<agent>_routing_capture` saves the raw final answer using the file tool. Only
   its exact successful write acknowledgment permits normalization; a handled
   tool-error string must not count as success.
3. `<agent>_routing_token` runs the pinned parser, consumes the scratch file and
   emits only the `routing_token` field, without a newline. The native router
   reads `context:<agent>_routing_token.tool_responses`, never the raw answer.

These are tool steps, not more bots or LLM prompts. Review agents still have only
read/comment permissions. Normalizer commands and paths are fixed by the catalog
definition; model text is passed as file contents, never shell arguments or code.
Python runs in isolated mode and checks the parser's SHA-256 before executing the
exact checked bytes, so editing a task-branch helper cannot change routing policy.
Each component uses its own `ctx-routing-<agent>.input` scratch file outside the
ignored `.ctx/` directory (GitLab file tools reject ignored paths). The parser
rejects symlinks, non-regular files and oversized responses. Successful consumption
removes only that scratch file; failed normalization retains it for inspection.
Never commit these files. Reconcile a retained file before an explicit resume;
there is no automatic overwrite, cleanup sweep or retry loop.

The raw response remains in the session log. Normalization is not proof that a
report was actually posted, evidence passed or a human approved a change; those
remain operation responsibilities and existing gates. Missing/changed parser,
tool errors and unknown output all fail closed.

For ticket review, an approved review emits `ready`; the router sends that result
to the `integrate` component. A non-passing review emits `blocked`. The reviewer
must never emit `integrate`. That token belongs to the coordinator's router, while
the integration component itself emits `more`, `complete` or `blocked`.
Unknown output must still abort; do not fix this by adding an `integrate` alias
to the review router or weakening its fallback.

The validator checks prompt/catalog/normalized-router token agreement, the exact
fixed adapter wiring and pinned command bytes. After changing the parser or token
allowlists, regenerate the mechanical YAML sections and run the tests:

```sh
python scripts/ctx_workflow.py sync-routing
python scripts/ctx_workflow.py validate
python -m unittest discover -s tests/workflow -v
```

Normalization is included in published Development v1.3.0, but has not been
live-executor-validated there. Delivery catalog publication remains separate.
The local graph tests execute the literal commands from the YAML, including the
hash check, and simulate the file-tool acknowledgment from GitLab's Go executor.
They are not a substitute for catalog schema validation or a live executor test.
The implementation follows GitLab's [deterministic component](https://docs.gitlab.com/user/duo_agent_platform/flows/claude-edit-v1-flow-registry/#deterministicstepcomponent)
and [command executor](https://gitlab.com/gitlab-org/duo-workflow/duo-workflow-executor/-/blob/main/pkg/actions/run_command.go)
contracts; it does not add an unsupported custom router or response-schema field.

Publication order: independently review and merge the helper plus the active flow YAML
definitions, ensure the approved helper exists with the matching digest on each
execution branch, then publish new development/delivery catalog versions
and verify each project's enabled version. Test the native tool schemas and exact
write/command response shapes with a scoped run before relying on this revision.
Executor variants returning decorated output must fail closed, not gain permissive
substring matching. Verify note readback and that summary-plus-token reaches the
next component; verify blocked/unknown responses stop. Repository edits alone do
not update registered definitions, and historical failed runs do not change
retroactively. Reconcile persisted work before resuming; never rerun integration
blindly. Retain the previous catalog version for rollback.

## Planning, identity and handoffs

Use the templates under `.gitlab/ctx/templates/`. The project state starts at
`docs/plan/project.md`; specs live in `docs/design/<feature>/`; epics and tickets
live in `docs/plan/E<epic-issue-iid>/`. Ticket IDs are `E2-1`, `E2-2`, etc.,
where `2` is the actual parent epic issue IID, not the intake request IID. Each
ticket has a separate GitLab issue, mapped by `issue_iid` in version-2 state,
and a matching `E2-1.md` file. Use the ID in its issue title and document heading.
All identities are scoped to the platform project ID.
The example state template contains placeholders and must be populated before use.

```sh
python scripts/ctx_workflow.py waves docs/plan/E2/state.json
```

The wave helper rejects cycles, unknown dependencies, unsupported status, duplicate
tickets and premature integration. It lists independent ready tickets, excludes
running/blocked work, and requires integration/review references for `done`.
It does not contact GitLab or attest that those references are true. The coordinator
must reconcile them against remote commit ancestry, review and pipeline state first.
It does not start sessions or lock concurrent coordinators; use one coordinator per
epic until a transactional dispatch/lease adapter is implemented.

The local development supervisor delegates all scoped ready work in the same
invocation, not one ticket per user trigger. It uses verified isolated worktrees;
do not run competing coordinators for the same epic. The registered v1.3.0 has
this supervisor definition; verify actual execution before relying on it. Integration uses ordinary
non-force Git pushes, rechecks target movement,
and reruns integration checks. A ticket MR is not a closed ticket; a closed epic is
not an approved deployment. Default-branch merges follow repository policy.

### Stable numbering and additions

For epic issue `#2`, the first ticket is `E2-1` even if GitLab assigned it issue
`#3` or `#103`. Invocations still use the actual ticket IID, for example
`ctx-ticket-design issue=3`. Do not pass `issue=1` based on the ticket ordinal.
Version-2 state validates the parent prefix, unique issue mappings, and a
`next_ticket_number` greater than every allocated number. Waves sort numerically,
so `E2-2` comes before `E2-10`.

After verifying the GitLab issue for an added ticket, preview its allocation:

```sh
python scripts/ctx_workflow.py add-ticket docs/plan/E2/state.json --issue-iid 9 --depends-on E2-3
```

This prints updated JSON; it does not write files or contact GitLab. Review and
persist the returned state, ticket file and issue title together before dispatch.
Repeated allocation for the same issue preserves its ID and does not consume
another number. Reordering/closing tickets never renumbers them; keep retired
records and never decrement the counter. Run only one planning writer per epic.
The helper is not an atomic remote allocator or concurrency lock.

### Migrating an existing plan

The wave helper accepts legacy version-1 states without modifying them. Migration
is explicit: verify the actual parent and intake issue, pause planning writers,
and work on the existing epic branch. Never infer the parent from the old prefix:
earlier definitions sometimes used the intake issue IID for that prefix.

For the observed `ctx/epic-i2` plan (epic `#2`, source request `#1`):

```sh
python scripts/ctx_workflow.py migrate-numbering docs/plan/EPIC-I2/state.json --epic-issue-iid 2 --source-issue-iid 1
```

This is a read-only preview. It assigns numbers in stored ticket order, rewrites
dependency IDs, preserves statuses/evidence/other metadata, and retains old IDs
as `legacy_id` / `legacy_epic_id`. Repeating it on migrated state is idempotent;
conflicting parent/source identity is rejected. It does not rename any file or
GitLab issue. The expected mapping for the existing six-ticket plan is:

| Existing ID | New ID | GitLab issue (unchanged) |
|---|---|---|
| T-I3 | E2-1 | #3 |
| T-I4 | E2-2 | #4 |
| T-I5 | E2-3 | #5 |
| T-I6 | E2-4 | #6 |
| T-I7 | E2-5 | #7 |
| T-I8 | E2-6 | #8 |

Apply the preview in a reviewed change: move `docs/plan/EPIC-I2/` to
`docs/plan/E2/`, rename ticket files/headings, and update project/spec/epic/ticket
references and dependency tables. Preserve issue URLs, branch names, MR targets,
evidence and actual issue numbers. Then rename the existing issue title prefixes
to match; do not recreate issues or rewrite historical comments. Verify waves
and all links, then record the migration commit and issue-title readback before
resuming. The next new ticket is `E2-7`, regardless of its GitLab issue IID.

Publish revised repository definitions and the CTX Planning agent prompt before
using changed numbering. Changing local files does not update the registered agent.
The old planning flow is retired; do not reactivate it for numbering changes.

## Application command and evidence contract

Workflow validation/self-tests run automatically for MRs and the default branch;
`CTX_WORKFLOW_CHECKS=1` also enables them on other branches. Set
`CTX_APPLICATION_CHECKS=1` in a pipeline to include `.gitlab/ci/delivery.yml`:

```text
verify + browser (when required) → acceptance → source-security → package → artifact-security → configure
    → delivery-readiness (default-branch release pipeline only)
```

The `acceptance` command is implemented. Application command entries in
`.gitlab/ctx/commands.yml` remain `null` until the foundation provides real tools.
The browser harness needs app startup and actual tests. `run verify` currently exits 2
with a retained blocked report. There are no success placeholders. Do not interpret
a green workflow-only pipeline as a tested application. Once the foundation exists,
make these checks unconditional/required through a reviewed CI change before
allowing implementation merges; an optional variable is not a merge safety gate.

Each command is a reviewed argument array, executed without shell interpolation
and with a timeout. It must write fresh JSON to `CTX_OUTPUT`. The adapter also
receives `CTX_SOURCE_SHA` and `CTX_STEP`. Exit codes: 0 passed, 1 command failed or
timed out, 2 blocked/malformed/missing evidence. Normal command output is captured
by GitLab job logs; adapters must redact secrets.

Commit the candidate before running adapters. The runner requires a clean checkout
and rejects an adapter that changes HEAD or leaves tracked/unignored changes. This
prevents attaching evidence from uncommitted work to the previous commit's SHA.
Keep generated test/scan outputs in ignored paths such as `.ctx/`.

All output evidence requires `source_sha` matching the checkout and an HTTPS
`report_url`. Additional fields:

| Command | Required evidence |
|---|---|
| `verify` | `passed: true`, positive integer `tests_total` for actual application tests |
| `acceptance` | `passed: true`, positive `criteria_total`, ticket/epic `scope`, 64-hex `manifest_sha256`; validates per-AC evidence from verify/browser artifacts |
| `source-security` | `checks` containing `source`, `dependency`, `secrets`, each `passed`; integer `blocking_findings: 0` |
| `package` | `artifact_digest` as `sha256:<64 hex>`, HTTPS `artifact_url`, HTTPS `sbom_url` |
| `artifact-security` | Same `artifact_digest`, `passed: true`, integer `blocking_findings: 0` |
| `configure` | Same `artifact_digest`, `environment: staging`, `passed: true`, 64-hex content hash `configuration_revision` |

The runner writes `.ctx/reports/<step>.json` with project ID, source SHA, pipeline
ID and observed status. Each downstream job requires every preceding report from
that same identity and checks artifact consistency. Job artifacts retain reports
for 30 days. Commands returning zero without fresh valid evidence are blocked.
`configure` validates only; it does not apply settings or migrations. Configure
`CTX_AC_MANIFEST` and `CTX_AC_SCOPE` for the candidate. UI criteria additionally
require `CTX_BROWSER_CHECKS=1`; skipping the browser job does not waive them.
See [the exact evidence schema](acceptance-evidence.md) and
[browser setup](browser-checks.md). The verify adapter publishes `.ctx/acceptance.json`;
the browser job independently publishes `.ctx/browser/acceptance.json`.

These checks establish consistency, not cryptographic provenance or complete test
coverage. A malicious adapter can invent evidence. Trust comes from independently
reviewed adapters, protected CI definitions, actual job results and access controls.
Never give a task agent deployment credentials or permission to weaken those controls.

The new `ctx:delivery-readiness` job collects these reports on the default branch,
including failures, and writes `.ctx/reports/delivery-readiness.json`. It checks
the candidate identity, design/merge/governance receipts and all prerequisite
evidence. It also exposes all nine stage statuses without claiming that configuration
validation applied settings or that a verified package was deployed. The checker
supports later staging/promotion/production receipts but does not implement their
executors or provide approval authority. See [delivery readiness](delivery-readiness.md).

## GitLab activation checklist

The earlier empty-repository/credits observation is superseded by the successful
planning run in the original project, `creocortex-group1/hackathon-paypal`.
The migration destination is
`gitlab-ai-hackathon/transcend-october-2026/43066631/showcase`
(project ID `87329027`). Catalog registrations are project-specific; check the
destination registrations before invoking a flow.

The checkout's `origin` fetch/push remote is
`git@gitlab.com:gitlab-ai-hackathon/transcend-october-2026/43066631/showcase.git`;
`main` tracks `origin/main`. The original project remains the separate `source`
remote for historical reference, not the publication target.

On 2026-10-07, the existing
[CTX Development registration](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/automate/flows/1016234)
was updated from v1.0.0 to v1.1.0 and its enabled project page was verified.
Private visibility, the `@ai-ctx-development-gitlab-ai-hackathon` service account,
and active Mention/Assign/Assign reviewer triggers were preserved. No flow run,
ticket integration or default-branch merge was triggered. The repository-side
skill, validator and test changes still require independent review and merge;
catalog publication does not merge those files into the checkout used by agents.

1. Review and publish this revision, including `skills/`, templates and CI helpers.
   Preserve the existing numbering migration and remote history.
2. Run GitLab CI lint and verify automatic MR/default-branch workflow checks.
   For a separate branch pipeline, set `CTX_WORKFLOW_CHECKS=1`.
   Static checks are not GitLab server-side schema validation.
3. Keep `.gitlab/duo/agent-config.yml` on default; GitLab reads that version. It is
   currently a Python environment, not a preinstalled browser environment. The
   browser CI job has its own Playwright image; see the browser guide for the distinction.
4. Use CTX Planning/Design chat agents and update their existing registrations
   rather than creating duplicates. Keep the old planning flow disabled.
   Development v1.3.0 is published/read back as recorded above. Check for a delivery
   registration before creating/enabling it, then verify the enabled versions.
   Do not register legacy YAML or individual skills.
5. Review service-account permissions and begin with human-invoked flows on issues
   or MRs. These definitions do not implement automatic pipeline-event triggering.
6. Verify branch/merge protections for the project's tier. Optional CI variables
   are not merge protection. No production job or enforced release approval exists yet.
7. Use **Add new chat → CTX Planning** for a scoped plan update; confirm skill
   loading, explicit publication approval, numbering, acceptance-manifest creation,
   saved-artifact readback and actual helper validation evidence.
8. Once enabled, invoke `/flow:ctx-development` on the selected issue, e.g. with
   `ctx-ticket-design issue=<actual-ticket-iid>`. It handles the internal operations.
   If CI is pending or a prerequisite is missing, resolve it and invoke the same flow
   with the recorded resume operation. Browser evidence precedes independent review.
9. Reconcile the epic through the same development flow. Record session/MR/pipeline
   URLs, review all epic criteria and prepare its MR. Use `/flow:ctx-delivery` for
   release readiness; absent deploy/monitor adapters must remain explicitly blocked.

The service-account handle is assigned by GitLab; do not use a guessed @handle.
Committing these files alone does not register or activate catalog flows.

## Remaining implementation for the full objective

- Live validation of development/delivery versions and the planning agent's first
  approved publication; the earlier planning-flow execution remains historical evidence.
- Live-test the published bounded native Development supervisor. Real parallel
  workers and distributed concurrency leases remain gaps; the local journal is
  not either. No cross-flow mention/retrigger workaround is implemented.
- The hosted app foundation and real test/security/build/SBOM/configuration adapters.
- Deterministic attestation of design/red-test/review prerequisites beyond prompts.
- Staging preflight, actual configuration application/deploy/migrations/recovery,
  smoke/log/metric monitoring, outcome evidence and deduplicated findings intake.
- Enforced human approval bound to exact artifact AND production configuration,
  same-digest promotion, post-promotion monitoring and final nine-stage evidence.

No deploy/promote job exists until those target/credential/approval controls are
implemented. The delivery flow reports those missing stages as blocked.

## Official implementation references

- [Custom flow schema and restrictions](https://docs.gitlab.com/user/duo_agent_platform/flows/custom_flows_schema/)
- [Flow components, prompts and routing](https://docs.gitlab.com/user/duo_agent_platform/flows/claude-edit-v1-flow-registry/)
- [Agent execution configuration](https://docs.gitlab.com/user/duo_agent_platform/flows/execution/agent-config-yaml/)
- [Register and enable custom flows](https://docs.gitlab.com/user/duo_agent_platform/flows/custom/)
- [CI syntax](https://docs.gitlab.com/ci/yaml/)
