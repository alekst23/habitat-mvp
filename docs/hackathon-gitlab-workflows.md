# GitLab workflows for the HABITAT submission

This is the concise implementation plan for the [GitLab Transcend hackathon](https://gitlab-transcend.devpost.com/). The goal is to show GitLab agents taking a HABITAT change from intent to a tested, secure, observable release.

The GitLab submission is the agentic delivery workflow; HABITAT, the PayPal submission, is the application it builds and operates. Stage coverage must be demonstrated by actual workflow runs. This document describes the target behavior; the [implementation guide](development/gitlab-workflow.md) distinguishes the local foundation from pending adapters and live validation.

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
Issue created
    ↓
Planner Agent → acceptance criteria, risk, test plan
    ↓
Developer Flow → branch, code, tests, merge request
    ↓
Review/Verification Flow → review, tests, source scans, remediation
    ↓
Package/Security Flow → versioned artifact, SBOM, artifact scan
    ↓
Configure/Release Flow → validate configuration, check governance, deploy preview
    ↓
Smoke/Monitor Agent → health, logs, run metrics, lifecycle evidence
    ↓
Human outcome approval → promote verified artifact (Supervised)
or automatic promotion after checks (Hands-off)
```

Recommended flows:

| Trigger | Flow | Output |
|---|---|---|
| Work item created | Planner + Developer agents | Plan and merge request |
| Merge request created or marked ready | Code Review/Security agents | Review comments, scan interpretation, fixes |
| Pipeline failed | Fix CI/CD flow | Diagnostic and remediation commit |
| Verification and source scans passed | Package/Security flow | Versioned artifact, SBOM, artifact scan results |
| Package and artifact scans passed | Configure/Release flow | Validated environment configuration, governance checks, preview/staging deployment |
| Deployment complete | Monitor/Governance agent | Smoke tests, health, redacted logs, run metrics, and lifecycle evidence summary |
| Outcome approved (Supervised), or checks passed (Hands-off) | Promotion flow | Same verified artifact promoted, deployment record, post-promotion health result |

GitLab flows can be triggered by work-item events, merge-request events, pipeline state, mentions, assignments, or reviewer assignments. Keep the number of flows small and make every flow contribute to the same issue-to-release story.

## Most Stages Covered plan

Target all nine stages from the [prize inventory's coverage plan](hackathon-gitlab-prizes.md#most-stages-covered-plan). These are lifecycle responsibilities, not nine separate agents or a requirement for nine sequential jobs. The same agents can coordinate multiple stages, with CI performing deterministic checks.

| Stage | Responsible agent or flow | Work performed and evidence retained |
|---|---|---|
| Plan | Habitat Planner | Turn the issue into acceptance criteria, a scoped plan, trust-boundary risks, and a test plan. Link the issue, specification, and implementation tickets. |
| Create | Habitat Builder | Implement code, tests, and documentation on a branch; open or update the MR. Retain agent execution records and the resulting commits. |
| Verify | Verification flow and Builder remediation | Run unit, integration, contract, concurrency, and end-to-end tests, including insufficient budget, duplicate requests, and revoked access. Publish test reports and link any failed run to its fix and passing rerun. |
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
extend delivery. These are logical procedures to implement in native GitLab Duo
flows, not a requirement to install Claude skills or create one agent per operation.
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

The mistaken stage-named `.claude/skills/ctx-*/` files have been removed. Five native
flow definitions now live under `.gitlab/duo/flows/`, with an explicit operation
catalog, planning templates, dependency-wave helper, CI checks and evidence adapters.
This is a locally tested foundation, not an activated end-to-end workflow. Automatic
cross-flow dispatch and application/deployment adapters remain implementation gaps.

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

The eventual agent count and flow grouping are implementation decisions. Define
each role with the tools needed for its work; keep production credentials out of
agent context.

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
lint → unit/integration/contract/e2e → source/dependency/secret checks
     → package/SBOM → artifact scan → configure/governance checks
     → deploy-preview → smoke/monitor → evidence summary
     → outcome gate → promote same artifact → health check
```

Use merge-request pipelines for review evidence and a protected deployment environment for the supervised gate. GitLab UI flows execute through CI/CD runners; verify hosted-runner availability or the supported group/instance runner configuration. `.gitlab/duo/agent-config.yml` is read from the default branch and configures the flow image, static dependency setup and network policy. Keep deployment credentials outside agent sessions; configure short-lived external-service identity in separately reviewed deployment jobs where supported.

The job names above describe intended responsibilities. Select commands and GitLab controls supported by the project's stack and access tier during implementation. Keep reports and artifact references accessible for judging. Configuration and governance checks run before deployment; the final evidence summary also records monitoring and the outcome decision.

Keep Habitat's own credentials behind its proxy. The GitLab flow may call a test-only Habitat MCP server to create a test tenant, run a budgeted request, inspect the activity log, and invoke the kill switch. It must not call production services or bypass Habitat policy.

## Autonomy choice

Target **Supervised** first: agents execute the complete multi-step workflow, deploy to preview/staging, and a human approves the outcome. This is aligned with HABITAT's trust story and is easier to demonstrate honestly.

Treat **Hands-off** as a stretch target only for a disposable, reversible environment. GitLab supports human-input components, but an agent's approval conversation is not a substitute for deployment authorization. This implementation persists unresolved intent on issues and stops; sensitive actions still require enforced environment/branch controls. Protected promotion is not implemented yet.

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
