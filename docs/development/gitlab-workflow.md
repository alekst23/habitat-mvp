# CTX native GitLab workflow implementation

## Status and boundaries

Planning has already run successfully in GitLab Duo through `/flow:ctx-planning`,
as confirmed by the user. The review-routing correction was published to Showcase's
CTX Development catalog entry as v1.1.0 on 2026-10-07; its saved YAML was read back
and matched the tested local definition. No execution of this corrected version
has been verified. Other unpublished changes and implementation limits below
remain separate from that catalog update. No external Claude runner is used. Duo runs
the native flow definitions in its CI execution environment. Normal GitLab CI jobs
run deterministic workflow checks and, once configured, application adapters.

| Native flow | Preserved process | Current boundary |
|---|---|---|
| `.gitlab/duo/flows/ctx-planning.yml` | Route → intake/intent → spec → epic/tickets and acceptance manifest | Prior planning version ran live; publish this revised version |
| `.gitlab/duo/flows/ctx-development.yml` | Coordinate → design → minimal tests → implementation → browser/AC checks → independent ticket review → integration → whole-epic review/close | One ticket per run; resumable handoffs, no autonomous retriggering or parallel dispatcher |
| `.gitlab/duo/flows/ctx-delivery.yml` | Six delivery operations, stage evidence and candidate readiness review | Read/comment only; application adapters and deployment/approval integration are missing |

Each of the 30 procedures is a repo skill at `skills/ctx-*/SKILL.md`, explicitly
referenced by its flow prompt. Skills supply instructions; flow components supply
tool permissions and routing. Only the three flows need catalog registration.
The superseded ticket/epic/project YAML is preserved under `.gitlab/duo/legacy/`
for reference, not registration. The operation-to-flow mapping is
`.gitlab/ctx/catalog.json`. Stages classify
evidence; they do not determine agent boundaries. Read the full contract in
`ctx-contract.md` and the prize coverage plan in `../hackathon-gitlab-workflows.md`.

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
each prompt's explicit `Terminal tokens: [...]` declaration to equal its router's
keys (excluding `default_route`) and the component's `terminal_tokens` entry in
the local catalog. Required skills with explicit terminal-token declarations may
only use tokens accepted by their consuming component. It is not a copy
of GitLab's server-side schema and cannot prove tool availability or authorization.
Official catalog validation and GitLab CI lint remain required.

The three flow graphs terminate on unknown or blocked results. Agents post detailed
operation reports to the source issue before returning a routing token. A GitLab
session ending in `abort` can mean a documented missing prerequisite, not a crash.
Resume with the explicit operation after resolving that blocker. There are no
automatic flow-retrigger or repair loops in this version.

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

The normalization revision is locally tested, not yet published or live-validated.
The local graph tests execute the literal commands from the YAML, including the
hash check, and simulate the file-tool acknowledgment from GitLab's Go executor.
They are not a substitute for catalog schema validation or a live executor test.
The implementation follows GitLab's [deterministic component](https://docs.gitlab.com/user/duo_agent_platform/flows/claude-edit-v1-flow-registry/#deterministicstepcomponent)
and [command executor](https://gitlab.com/gitlab-org/duo-workflow/duo-workflow-executor/-/blob/main/pkg/actions/run_command.go)
contracts; it does not add an unsupported custom router or response-schema field.

Publication order: independently review and merge the helper plus all three YAML
definitions, ensure the approved helper exists with the matching digest on each
execution branch, then publish new planning/development/delivery catalog versions
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

The development coordinator selects one ready ticket per invocation and stops after
its integration, unless the epic is ready for final review/close. Distinct tickets
can be started in separate human-triggered sessions with separate branches/checkouts;
do not run competing coordinators for the same epic. Integration uses ordinary
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

Publish the revised repository definitions and update the registered AI Catalog
flow versions (including the enabled project versions) before using new numbering.
Changing local YAML alone does not update the already registered CTX Planning flow.

## Application command and evidence contract

Workflow validation/self-tests remain opt-in with `CTX_WORKFLOW_CHECKS=1`. Set
`CTX_APPLICATION_CHECKS=1` in a pipeline to include `.gitlab/ci/delivery.yml`:

```text
verify + browser (when required) → acceptance → source-security → package → artifact-security → configure
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
2. Run GitLab CI lint and set `CTX_WORKFLOW_CHECKS=1` for a workflow-check pipeline.
   Static checks are not GitLab server-side schema validation.
3. Keep `.gitlab/duo/agent-config.yml` on default; GitLab reads that version. It is
   currently a Python environment, not a preinstalled browser environment. The
   browser CI job has its own Playwright image; see the browser guide for the distinction.
4. Update existing CTX Planning/Development registrations rather than creating
   duplicates. Development v1.1.0 is published as recorded above; Planning's local
   terminal-token declarations are not yet published. Check for a delivery
   registration before creating/enabling it, then verify the enabled versions.
   Do not register legacy YAML or individual skills.
5. Review service-account permissions and begin with human-invoked flows on issues
   or MRs. These definitions do not implement automatic pipeline-event triggering.
6. Verify branch/merge protections for the project's tier. Optional CI variables
   are not merge protection. No production job or enforced release approval exists yet.
7. Re-run `/flow:ctx-planning` for a scoped plan update; retain the successful
   session URL and confirm skill loading, numbering and acceptance-manifest creation.
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

- Live validation of the revised three-flow versions, skill loading and handoffs;
  the earlier planning execution is already confirmed.
- Automatic cross-flow ticket dispatch, concurrency leases and bounded repair
  accounting; current explicit handoffs are not end-to-end autonomous orchestration.
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
