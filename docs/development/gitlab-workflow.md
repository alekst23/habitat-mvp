# CTX native GitLab workflow implementation

## Status and boundaries

This is a locally implemented/tested workflow foundation, not a live GitLab run.
No Claude skill installation or external Claude runner is used. GitLab Duo runs
the native flow definitions in its CI execution environment. Normal GitLab CI jobs
run deterministic workflow checks and, once configured, application adapters.

| Native flow | Preserved process | Current boundary |
|---|---|---|
| `.gitlab/duo/flows/ctx-planning.yml` | Project routing, issue intake/triage, intent interview, spec, epic/ticket decomposition | Native prompts/tool routing; needs catalog registration and live validation |
| `.gitlab/duo/flows/ctx-ticket.yml` | Design → collectible red tests → implementation → independent ticket review → closure | Resume entry points retain prerequisites; closure waits for verified epic integration |
| `.gitlab/duo/flows/ctx-epic.yml` | Dependency waves, integration, separate whole-epic review, docs/merge order, epic MR | Wave calculation works locally; cross-flow dispatch is an explicit handoff, not automatic |
| `.gitlab/duo/flows/ctx-project.yml` | Project-go / project-sleep state and durable handoff | Records/coordinates work; no autonomous retriggering or periodic scheduler |
| `.gitlab/duo/flows/ctx-delivery.yml` | Six delivery operations, stage evidence and candidate readiness review | Read/comment only; application adapters and deployment/approval integration are missing |

The exact operation-to-flow mapping is `.gitlab/ctx/catalog.json`. Stages classify
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
tool separation, catalog coverage and CI evidence dependencies. It is not a copy
of GitLab's server-side schema and cannot prove tool availability or authorization.
Official catalog validation and GitLab CI lint remain required.

The five flow graphs terminate on unknown or blocked results. Agents post detailed
operation reports to the source issue before returning a routing token. A GitLab
session ending in `abort` can mean a documented missing prerequisite, not a crash.
Resume with the explicit operation after resolving that blocker. There are no
automatic flow-retrigger or repair loops in this version.

## Planning, identity and handoffs

Use the templates under `.gitlab/ctx/templates/`. The project state starts at
`docs/plan/project.md`; specs live in `docs/design/<feature>/`; epics and tickets
live in `docs/plan/EPIC-I<source-issue-iid>/`. Every ticket gets its own issue and
`T-I<ticket-issue-iid>.md`. All IIDs are scoped to the platform project ID.
The example state template contains placeholders and must be populated before use.

```sh
python scripts/ctx_workflow.py waves docs/plan/EPIC-I12/state.json
```

The wave helper rejects cycles, unknown dependencies, unsupported status, duplicate
tickets and premature integration. It lists independent ready tickets, excludes
running/blocked work, and requires integration/review references for `done`.
It does not contact GitLab or attest that those references are true. The coordinator
must reconcile them against remote commit ancestry, review and pipeline state first.
It does not start sessions or lock concurrent coordinators; use one coordinator per
epic until a transactional dispatch/lease adapter is implemented.

Distinct tickets can run in separate Duo CI sessions. Each gets its own branch and
checkout. Integration uses ordinary non-force Git pushes, rechecks target movement,
and reruns integration checks. A ticket MR is not a closed ticket; a closed epic is
not an approved deployment. Default-branch merges follow repository policy.

## Application command and evidence contract

`.gitlab-ci.yml` always runs workflow validation and self-tests. Set
`CTX_APPLICATION_CHECKS=1` in a pipeline to include `.gitlab/ci/delivery.yml`:

```text
verify → source-security → package → artifact-security → configure (validation only)
```

All command entries in `.gitlab/ctx/commands.yml` are intentionally `null` until
the application foundation provides real tools. `run verify` currently exits 2
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
| `source-security` | `checks` containing `source`, `dependency`, `secrets`, each `passed`; integer `blocking_findings: 0` |
| `package` | `artifact_digest` as `sha256:<64 hex>`, HTTPS `artifact_url`, HTTPS `sbom_url` |
| `artifact-security` | Same `artifact_digest`, `passed: true`, integer `blocking_findings: 0` |
| `configure` | Same `artifact_digest`, `environment: staging`, `passed: true`, 64-hex content hash `configuration_revision` |

The runner writes `.ctx/reports/<step>.json` with project ID, source SHA, pipeline
ID and observed status. Each downstream job requires every preceding report from
that same identity and checks artifact consistency. Job artifacts retain reports
for 30 days. Commands returning zero without fresh valid evidence are blocked.
`configure` validates only; it does not apply settings or migrations.

These checks establish consistency, not cryptographic provenance or complete test
coverage. A malicious adapter can invent evidence. Trust comes from independently
reviewed adapters, protected CI definitions, actual job results and access controls.
Never give a task agent deployment credentials or permission to weaken those controls.

## GitLab activation checklist

Observed on October 5, 2026: `creocortex-group1/hackathon-paypal` (project 87271414)
is private, on Free, and its repository is empty. AI → Agents → Managed says to
buy credits to start using agents. The local repository has no remote configured.
No billing, permissions, service accounts or remote repository content were changed.
Resolve Duo access/credits (including any organizer-provided entitlement) before
attempting a live flow run; this observation does not establish which grant is available.

1. Publish the foundation to the intended project default branch. No remote or push
   has been configured by this implementation. Preserve existing project history.
2. Run GitLab CI lint and the workflow pipeline. Confirm Duo entitlement/credits
   and supported runners. Static local checks do not prove availability.
3. Configure `.gitlab/duo/agent-config.yml` on default; GitLab ignores the version
   from a task branch. The setup installs only a pinned dependency, not task-branch
   scripts. Review runner network/secret exposure before enabling agents.
4. In GitLab AI Catalog, create one private custom flow per YAML file. Paste the
   corresponding full YAML and resolve server-side validation before enabling.
   Do not create nine stage-named skills or a separate external Claude executor.
5. Review the service-account permissions and enable the flows for this project.
   Initially enable **mention triggers only**. These definitions reject bare-IID
   assignment triggers and have not been adapted to pipeline event payloads.
6. Configure default-branch protection and merge controls. Confirm which controls
   the project tier actually supports. Never assume a manual CI button restricts
   who may approve a deployment. No production job is included yet.
7. On a real issue, mention the actual generated planning service account with
   `ctx-project-design issue=<iid>` and a scoped objective. Observe spec questions,
   persisted artifacts and the next handoff. Use a fixture-safe foundation change.
8. Start a ticket with `ctx-ticket-design issue=<ticket-iid>`. It proceeds through
   tests, implementation and review when prerequisites exist. If CI is still
   pending, resume with `ctx-ticket-review issue=<ticket-iid>` after completion.
9. Use `ctx-epic-run issue=<epic-iid>` to reconcile/integrate checked results.
   Resume `ctx-ticket-close`, `ctx-epic-review` and `ctx-epic-close` as directed.
   Record actual session/MR/pipeline URLs in the project plan.

The service-account handle is assigned by GitLab; do not use a guessed @handle.
Committing these files alone does not register or activate catalog flows.

## Remaining implementation for the full objective

- Live catalog and runner smoke test, tool compatibility and state persistence.
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
