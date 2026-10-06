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

The mistaken stage-named Claude skills have been removed. Native GitLab Duo
definitions live in `.gitlab/duo/flows/`, with operation mapping in
`.gitlab/ctx/catalog.json`. Read `docs/development/gitlab-workflow.md` for actual
implementation boundaries, activation and commands. These are not Claude skills.

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

Native flow definitions, workflow CI validation/tests, dependency-wave planning,
and fail-closed CI command/evidence adapters are implemented locally. Catalog
registration, GitLab CI lint and live flow execution are not yet verified.

Workflow development commands (Python 3.12):

```sh
python -m pip install -r requirements-workflow.txt
python scripts/ctx_workflow.py validate
python -m unittest discover -s tests/workflow -v
python scripts/ctx_workflow.py waves docs/plan/EPIC-I<issue>/state.json
```

There are no application install/test/build/scan/deployment commands yet.
Establish reviewed argument arrays and evidence writers in `.gitlab/ctx/commands.yml`
as part of the application foundation. `python scripts/ctx_workflow.py run verify`
currently returns blocked (exit 2), correctly. Workflow self-tests are not application
tests. Set `CTX_APPLICATION_CHECKS=1` for the application CI lane; until configured,
its first job fails closed. Make the lane mandatory before implementation MRs merge.

Agents may edit scoped planning/application files on ticket/epic branches, create
issues/MRs and publish redacted evidence. They may not change workflow policy,
CI controls, command adapters or runner configuration to make a failing check pass;
those require an explicitly scoped foundation/policy change and independent review.
Never push directly to default, force-push, self-approve, expose secrets or deploy
from an agent session. Do not add deployment credentials before protected target
and approver controls have been configured and verified.
