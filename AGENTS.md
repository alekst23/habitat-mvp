# Habitat development agents

## Project context

Read `docs/habitat-mvp.md` for the current product specification: a hosted
marketing-agent application with onboarding, delegated actions, and USD budgets.
The GitLab workflow builds and operates that application; it is separate from
the customer-facing agents. Read `docs/hackathon-gitlab-workflows.md` for the
nine-stage delivery plan.

## Workflow instructions

Read `docs/development/ctx-contract.md` for the agreed workflow and
`docs/hackathon-gitlab-workflows.md` for the operation catalog and stage coverage.
Preserve the original issue, specification, epic, ticket, design, test, review,
and close operations under the `ctx-` prefix. Add the six delivery operations
listed there. Lifecycle stages classify evidence; they do not define agent or
operation boundaries.

Planning is conversational: use the **CTX Planning** agent in Duo Chat. The two
background flow entry points are `ctx-development` and `ctx-delivery` in
`.gitlab/duo/flows/`. Reusable instructions live in `skills/ctx-*/SKILL.md`;
`.gitlab/ctx/catalog.json` records the active entry points and operation mappings.
Read the named skills before acting. Do not register a bot/flow for every skill.
The retired `ctx-planning.yml` remains for historical regression tests and rollback,
not publication or normal use. Its successful earlier runs remain valid history.
Superseded ticket/epic/project definitions are retained in `.gitlab/duo/legacy/`.
Read `docs/development/gitlab-workflow.md` for activation and implementation limits.

The local Development revision is a bounded single-shot Duo supervisor; read
`docs/development/single-shot-development.md` before changing or running it. It
advances all explicitly scoped work through delegated SDLC phases, with an explicit
serial fallback (native parallel execution is unverified). Its progress journal
does not grant authority or attest evidence; remote review/CI/ancestry must still
be checked. Preserve ticket-only scope, respect active runs, and keep durable
checkpoints. This local revision is not yet the published catalog version.

CTX Planning and CTX Design prompts/registration records live in
`.gitlab/duo/agents/`. The order is Planning -> Design -> Development. Planning
publishes approved scope, epics, tickets, dependencies and state, marking Design
pending. Design interviews and commits specs, technical/ticket design and the
acceptance manifest on the epic branch, verifying files at the returned commit SHA.
An issue note reports that save; it does not replace it. Neither starts
implementation or flows. Both return ordinary prose and wait for replies;
terminal-token and checkpoint/abort rules apply to ambient components, not chat.
Neither chat agent has a shell: helper validation requires actual runner/human
evidence. Pending checks do not prevent scope/design saves or design conversation,
but must not be reported as implementation readiness. Only real scope/decomposition
changes return to Planning; never send users there merely to save Design's work.

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
