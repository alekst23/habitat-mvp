# GitLab workflows for the HABITAT submission

This is the concise implementation plan for the [GitLab Transcend hackathon](https://gitlab-transcend.devpost.com/). The goal is to show GitLab agents taking a HABITAT change from intent to a tested, secure, observable release.

The GitLab submission is the agentic delivery workflow; HABITAT, the PayPal submission, is the application it builds and operates. Stage coverage must be demonstrated by actual workflow runs. Planning has already run in Duo via `/flow:ctx-planning`. This document describes the target behavior; the [implementation guide](development/gitlab-workflow.md) distinguishes that milestone from the new local revision and pending application/delivery adapters.

## Prize-critical requirements

The submission must:

- Use [GitLab Duo Agent Platform](https://docs.gitlab.com/user/duo_agent_platform/) features: agents, flows, or MCP clients.
- Choose one path and one autonomy level: Assisted, Supervised, or Hands-off.
- Use a public GitLab repository with an MIT `LICENSE` visible in the project About section.
- Show visible CI/CD pipeline history with the automation running.
- For Path B, start from an MIT-licensed open-source project, provide its original URL, and create the agentic automation and deployment on or after October 5, 2026.
- For Path B, provide a public deployment that remains available through the expected November 16 winner announcement.
- Provide a public YouTube demo under three minutes, plus English description and testing instructions.

Google Cloud deployment is optional and can add up to 0.2 points. The Most Stages Covered prize rewards one project from each path for touching the most lifecycle stages in the most creative way. A project can win one path prize and one special prize; the maximum combination is $10,000. See the [full prize inventory](hackathon-gitlab-prizes.md) and [official rules](https://gitlab-transcend.devpost.com/rules).

## The smallest credible workflow

Use one real, trust-critical issue: **enforce and surface a blocked over-budget inference request**.

```text
CTX Planning (Duo Chat) ↔ scope interview → approved scope, epic, tickets, dependencies
    ↓ human opens Design with saved plan references
CTX Design (Duo Chat) ↔ design interview → committed specs, ticket designs, AC manifest
    ↓ human starts development
ctx-development → design, lean tests, implementation, browser/AC evidence,
                  independent review ↔ bounded fixes, integration,
                  whole-epic validation/review ↔ bounded fixes, MR
    ↓ merge policy + human starts delivery
ctx-delivery → security, package, configuration, release, monitoring, outcome review
               (application/deployment adapters still required)
```

Planning is a conversational agent; execution remains in flows. There is no
one-agent/flow-per-skill or per-stage requirement:

| Trigger | Entry point | Output |
|---|---|---|
| New intent or a scope change | **CTX Planning** chat agent | Approved scope, epic/tickets, dependencies and plan state; Design pending |
| Scoped epic/tickets needing specification | **CTX Design** chat agent | Committed/read-back-verified specs, ticket designs and AC manifest; explicit open decisions/validation status |
| Ready ticket/epic, a fix, or a resume after CI/feedback | `ctx-development` | Verified ticket integration and ultimately a reviewed epic MR |
| Release candidate or deployment feedback | `ctx-delivery` | Candidate readiness, missing-stage blockers; eventual supervised release evidence |

**CTX Design** runs after Planning and before Development. It reuses spec-interview,
epic-design and ticket-design procedures across all scoped tickets, saves versioned
specs on the existing epic branch and verifies the saved files at the returned SHA.
Its issue note reports the save, not a substitute for it. It does not send users to
Planning or Development merely to save specifications. Only genuine scope changes
return to Planning. Chat checkpoints can be saved drafts with explicit open questions.
The original planning flow is retired, not another required background step.
The [Design closure contract](development/design-closure.md) retains stage ownership
through independent review, official-source research and bounded document repair.
Published Design v1.6.0/Development v1.5.0 use the existing background supervisor in explicit
design-only mode; it is not another bot or permission to implement. Saved artifacts
are review candidates, not completion. Catalog readback passed; the guide includes
the still-pending live E2 test.
The chat contributes Plan/design preparation; it does not establish implementation
or delivery-stage evidence. See [usage and boundaries](development/gitlab-workflow.md#ctx-design-conversational-entry-point).

Begin with human-invoked flows on issues/MRs. GitLab's documented flow triggers
require human action; these definitions do not automatically invoke another flow
or wake on a pipeline event. CI dependencies execute deterministic jobs; persistent
handoffs let a human resume the same flow after a blocker. Future scheduling must
be implemented explicitly, not implied by an agent's final message.

## Most Stages Covered plan

Target all nine stages from the [prize inventory's coverage plan](hackathon-gitlab-prizes.md#most-stages-covered-plan). These are lifecycle responsibilities, not nine separate agents or a requirement for nine sequential jobs. The same agents can coordinate multiple stages, with CI performing deterministic checks.

| Stage | Responsible agent or flow | Work performed and evidence retained |
|---|---|---|
| Plan | Habitat Planner | Turn the issue into acceptance criteria, a scoped plan, trust-boundary risks, and a test plan. Link the issue, specification, and implementation tickets. |
| Create | Habitat Builder | Implement code, tests, and documentation on a branch; open or update the MR. Retain agent execution records and the resulting commits. |
| Verify | Development verification/review components | Run the absolute minimum tests needed for changed behavior and material risks, reusing coverage and avoiding duplicated layers. Map every AC to current-SHA test/browser/inspection evidence; publish reports and link actual regressions to fixes. |
| Package | Package flow | Build and publish a versioned container or release artifact from the tested commit, with pinned dependencies and an SBOM. Record its immutable digest or checksum and registry/artifact URL. |
| Secure | Habitat Security/Release and security jobs | Run source, dependency, secret, and built-artifact checks. Interpret findings and remediate blocking issues; retain scan reports, remediation commits where needed, and passing reruns. Scan the built artifact before deployment. |
| Release | Release and promotion flows | Deploy the validated artifact to preview/staging, then promote that same artifact after the applicable outcome gate. Record environment URLs, deployment jobs, artifact identity, and smoke-test results. |
| Configure | Configure flow | Validate and apply reviewed environment settings, Habitat policy defaults, resource limits, and any required migrations or feature flags. Retain the manifest revision and a redacted validation/application report proving the configuration was applied. |
| Monitor | Habitat Security/Release coordinating monitor jobs | Observe the deployed application through smoke tests, health checks, redacted logs, and basic run metrics such as blocked requests and errors. Record the observation window, results, and response to unhealthy deployment; repeat health checks after promotion. |
| Govern | Habitat Security/Release and governance jobs | Check MIT license/DCO evidence and required branch, MR, and deployment controls before release. Enforce the selected autonomy gate and publish a final issue/MR summary linking the evidence for every stage and the approval or automatic release decision. |

For the over-budget demo, each stage must contribute to the same change: the plan defines rejection behavior, code implements it, tests verify it, the package contains it, scans assess it, configuration sets the allowance, release deploys it, monitoring observes the blocked request, and governance records the outcome.

The final summary must identify the source commit, pipeline, artifact, configuration revision, and deployment, with evidence links for all nine stages. Missing evidence is reported as incomplete coverage. An expected over-budget rejection is a passing behavior test; demonstrate failed pipelines using an actual regression and its repair. Failed checks block promotion, and a remediation commit must pass the affected checks and produce a newly verified artifact before release.

## GitLab technical pieces

### CTX operations and handoffs

Preserve the original Claude workflow's operations under the `ctx-` prefix, then
extend delivery. These are logical procedures reused by native GitLab Duo agents
and flows. Each is represented by a reusable `skills/ctx-*/SKILL.md` file, not a
separately registered flow or a requirement to install Claude skills.
The [shared contract](development/ctx-contract.md) records preserved behavior,
artifacts, supervision, and handoffs.

| Original workflow operation(s), renamed | Responsibility retained | Output / next handoff |
|---|---|---|
| `ctx-project-design` | Compare with existing design and active work; route to update, hotfix, or intake | Update route, `ctx-hotfix`, or `ctx-issue-new` and triage |
| `ctx-issue-new`, `ctx-issue-triage`, `ctx-spec-interview` | Separate intake from intent discovery and triage | Source issue, resolved behavior, feature specification, scoped plan |
| `ctx-epic-new`, `ctx-ticket-new`, `ctx-epic-design` | Decompose work and maintain the feature spec; reconcile tickets when intent changes | Epic/tickets, dependency graph, integration/wiring work |
| `ctx-ticket-design` | Define the solution approach and required contracts | Design artifacts ready for test preparation |
| `ctx-ticket-tests` | Map behavioral scenarios to tests and write collectible failing tests | Test plan and prerequisite test files |
| `ctx-ticket-start`, `ctx-branch-agent` | Check design/test gates and implement in isolation | Ticket branch and implementation evidence |
| `ctx-epic-run` | Schedule dependency waves and consolidate checked ticket results | Integrated epic branch and partial/failure status |
| `ctx-ci-check`, `ctx-browser-check`, `ctx-ticket-review` | Execute checks and review ticket behavior, architecture, tests, and security | Findings/evidence for repair or ticket close |
| `ctx-ticket-close` | Integrate a verified ticket into its epic and update status | Completed ticket on the epic branch |
| `ctx-epic-review`, `ctx-epic-docs`, `ctx-merge-queue`, `ctx-epic-close` | Review the whole feature, update docs, check merge order, and prepare its MR | Reviewed epic MR targeting the default branch |
| `ctx-hotfix`, `ctx-project-fix` | Route bounded fixes through appropriate spec, test, implementation, and review work | Scoped fix MR or the full epic path |
| `ctx-project-go`, `ctx-project-sleep` | Select and coordinate work; reconcile state, blockers, decisions, and handoff | Durable project state for the next execution |

Add six operations where the existing process lacks delivery coverage:

| New operation | Inputs | Work and completion evidence | Stages |
|---|---|---|---|
| `ctx-package` | Verified commit, build recipe and dependency locks | Published versioned artifact, immutable digest, SBOM and build result | Package |
| `ctx-environment-configure` | Target environment, reviewed configuration and limits | Validate/apply settings, secret references and migrations; record effective configuration | Configure |
| `ctx-security-check` | Candidate source or artifact, security policy | Execute scans, interpret findings, route repairs into tickets, and retain verified dispositions | Secure |
| `ctx-release` | Checked artifact/configuration, target and applicable approval | Deploy staging, promote the approved artifact, coordinate recovery; retain deployment records | Release |
| `ctx-monitor` | Deployment identity, health criteria and observation window | Smoke tests, logs, metrics and health verdict; actionable findings feed issue intake | Monitor |
| `ctx-release-review` | Candidate identity and development/delivery evidence | Check readiness and reconcile evidence for human approval; record the real final outcome | Verify, Govern |

The mistaken stage-named `.claude/skills/ctx-*/` files have been removed. CTX Planning
and CTX Design chat-agent records live under `.gitlab/duo/agents/`; development and
delivery definitions live under `.gitlab/duo/flows/`. The retired planning YAML is
retained there for regression tests/rollback, not publication. There are 30 focused
repo skills, an operation catalog, templates, dependency-wave helper, AC evidence
validator and Playwright CI harness. Legacy ticket/epic/project flows are archived.
The earlier planning flow ran live; the agent's approved artifact publication still
needs live validation. The local Development revision is a bounded single-shot
supervisor across scoped tickets/epics, with an explicit serial fallback. Its
progress journal enforces sequencing/identity, not external evidence or a remote
lease. The supervisor is published as Development v1.3.0 with full YAML readback;
actual native execution remains unverified.
The published v1.3.0 adds bounded in-session code/test/AC repair with
fresh evidence and independent review after every fix, for tickets and assembled
epics. It must still be live-tested before claiming this as demonstrated
Create/Verify coverage; no additional flow or bot per repair is required.
True parallel dispatch and application/deployment adapters remain gaps. See
[single-shot implementation](development/single-shot-development.md).

### Stage coverage over the operations

| Stage | Contributing operations |
|---|---|
| Plan | `ctx-project-design`, issue intake/triage, spec interview, epic/ticket planning, `ctx-project-go` |
| Create | `ctx-ticket-design`, `ctx-ticket-start`, `ctx-branch-agent`, `ctx-epic-run`, hotfix/fix paths |
| Verify | `ctx-ticket-tests`, `ctx-ci-check`, `ctx-browser-check`, ticket/epic review, `ctx-release-review` |
| Package | `ctx-package` |
| Secure | Security portions of ticket/epic review plus `ctx-security-check` |
| Release | `ctx-release`; epic close supplies the upstream MR, not a deployment |
| Configure | `ctx-environment-configure` |
| Monitor | `ctx-monitor`, with actionable findings routed into issue intake |
| Govern | Intent decisions, design/test gates, ticket/epic closure, project-state reconciliation, release review and human outcome approval |

Governance runs throughout the process. The final release review gathers its evidence;
GitLab controls enforce the required gates.

### Custom agents

Allocate agents around work and independence of review: intake/specification,
implementation, ticket review, epic integration review, and delivery coordination.
A flow may reuse a role across operations. Preserve the distinct ticket and
whole-epic review scopes, even if they use the same model.

The agents and active flow definitions make these boundaries explicit. Ticket and epic reviewers
are read-only except for reporting, while the browser component can execute checks.
Keep production credentials out of agent context; tool separation is not a substitute
for protected branches and human merge/release approval.

### Custom flows

A flow combines agents and deterministic tools. Use an **Agent** for multi-step reasoning, a **Tool** for fixed checks or commands, and an **AI Task** for one-shot classification or summarization. Configure custom flows in GitLab's AI Catalog and preserve the prompts/configuration in the public project materials for judging.

### Repository instructions

Add a root `AGENTS.md` containing:

- repository layout and service boundaries;
- commands for install, lint, test, security checks, and deployment;
- Habitat rules: fail closed, reserve budget before dispatch, never log secrets, and preserve tenant scope;
- which files an agent may modify and which actions require a human.

GitLab Duo uses `AGENTS.md` for flows and new agent sessions. Add component-level files only where different services need different instructions.

### CI/CD execution

Commit a normal `.gitlab-ci.yml` with visible jobs such as:

```text
minimal verification + required browser → AC coverage → source/dependency/secret checks
     → package/SBOM → artifact scan → configure/governance checks
     → deploy-preview → smoke/monitor → evidence summary
     → outcome gate → promote same artifact → health check
```

Use merge-request pipelines for review evidence and a protected deployment environment for the supervised gate. GitLab UI flows execute through CI/CD runners; verify hosted-runner availability or the supported group/instance runner configuration. `.gitlab/duo/agent-config.yml` is read from the default branch and configures the flow image, static dependency setup and network policy. Keep deployment credentials outside agent sessions; configure short-lived external-service identity in separately reviewed deployment jobs where supported.

The job names above describe intended responsibilities. Select commands and GitLab controls supported by the project's stack and access tier during implementation. Keep reports and artifact references accessible for judging. Configuration and governance checks run before deployment; the final evidence summary also records monitoring and the outcome decision.

Keep Habitat's own credentials behind its proxy. The GitLab flow may call a test-only Habitat MCP server to create a test tenant, run a budgeted request, inspect the activity log, and invoke the kill switch. It must not call production services or bypass Habitat policy.

## Autonomy choice

Target **Supervised** first: agents execute the complete multi-step workflow, deploy to preview/staging, and a human approves the outcome. This is aligned with HABITAT's trust story and is easier to demonstrate honestly.

Treat **Hands-off** as a stretch target only for a disposable, reversible environment. GitLab supports human-input components, but an agent's approval conversation is not a substitute for deployment authorization. Planning/design now resolve intent in chat and publish confirmed durable artifacts; background execution stops on missing prerequisites. Sensitive actions still require enforced environment/branch controls. Protected promotion is not implemented yet.

## Evidence judges should see

- The original issue and planner output.
- A real MR with agent-generated commits and review discussion.
- Passing and intentionally failing pipeline jobs, including over-budget, duplicate-reservation, concurrency, and revoked-access tests.
- Security scan results and a remediation commit.
- A versioned artifact and SBOM, immutable digest/checksum, deployment URL, and smoke-test output.
- Reviewed configuration and redacted evidence of applied policy defaults, resource limits, and any required migrations.
- Post-deployment health, redacted logs, and run metrics with a recorded observation window.
- License/DCO and branch/deployment-control checks, plus the outcome approval or automatic release record.
- Final issue/MR summary linking all nine stages to the same commit, pipeline, artifact, configuration, and deployment.
- The repository's MIT license, CI configuration, agent/flow configuration, and reproducible setup instructions.

The video should show one end-to-end run, not a tour of disconnected GitLab screens.

## References

- [GitLab Duo Agent Platform](https://docs.gitlab.com/user/duo_agent_platform/)
- [Flows](https://docs.gitlab.com/user/duo_agent_platform/flows/)
- [Custom flows](https://docs.gitlab.com/user/duo_agent_platform/flows/custom/)
- [Flow triggers](https://docs.gitlab.com/user/duo_agent_platform/triggers/)
- [`AGENTS.md` customization](https://docs.gitlab.com/user/duo_agent_platform/customize/agents_md/)
- [Flow CI/CD execution](https://docs.gitlab.com/user/duo_agent_platform/flows/execution/)
- [GitLab CI/CD pipelines](https://docs.gitlab.com/ci/pipelines/)
- [Agent tool governance](https://docs.gitlab.com/user/ai-governance/tool-governance/)
