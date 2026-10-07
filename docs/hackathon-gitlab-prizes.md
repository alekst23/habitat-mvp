# GitLab Transcend hackathon prize inventory

Verified October 5, 2026 against the [hackathon overview](https://gitlab-transcend.devpost.com/), the [official rules](https://gitlab-transcend.devpost.com/rules), and the linked [GitLab Duo Agent Platform documentation](https://docs.gitlab.com/user/duo_agent_platform/).

The event is **Life After Code: The path to production at the speed of imagination**, the GitLab Transcend Hackathon. It asks builders to use GitLab Duo Agent Platform features to automate the post-code DevSecOps lifecycle: code review, testing, security, compliance, deployment, monitoring, and related work. The published prize pool is **$45,000 USD cash** across **8 prize categories and 10 awards**.

## Habitat recommendation

Enter **Path B: Bring Your Own**. HABITAT is already an existing project and its strongest story is what GitLab adds after code exists: a coordinated set of agents and flows that takes a trust-sensitive change from an issue through review, verification, security, packaging, deployment, monitoring, and governance.

The current HABITAT repository does not yet contain a visible `LICENSE` file, so Path B is not submission-ready. Before importing it to GitLab, add an MIT license, make the project publicly accessible, and record the original project URL. The GitLab rules require the Path B project to be MIT-licensed, updated with new agentic automation and deployed on or after October 5, 2026.

The recommended prize posture is:

1. **Primary path target:** Path B — Best Supervised Agent ($4,000). This matches HABITAT's trust model: agents perform the multi-step work, while a human approves the outcome at the appropriate gate.
2. **Stretch path target:** Path B — Best Hands-off Agent ($5,000). Pursue this only for a bounded, reversible demo environment where the entire code-to-deployment loop really runs without a human in the middle. Do not call a workflow hands-off if it still requires approval.
3. **Primary special-prize target:** Most Stages Covered ($5,000). Aim to touch all nine GitLab DevSecOps lifecycle stages in a coherent way.
4. **Optional special-prize target:** Most Environmentally Impactful ($5,000), only if we can measure a credible baseline and improvement using current public measurement methods and Software Carbon Intensity (SCI).

A project may win **one prize from Path A or Path B and one Special Prize**. The largest possible combination for one HABITAT submission is therefore **$10,000**: a $5,000 autonomy prize plus a $5,000 special prize.

## Complete prize list

Amounts below are per winning project. If a prize is awarded to a team, the cash is paid to the designated representative, who is responsible for distributing it among participating members.

| # | Group | Award | Per winner | Winners | Category pool |
|---|---|---|---|---:|---|
| 1 | Path A: Start Fresh | Best Assisted Agent | $4,000 cash | 1 | $4,000 cash |
| 2 | Path A: Start Fresh | Best Supervised Agent | $4,000 cash | 1 | $4,000 cash |
| 3 | Path A: Start Fresh | Best Hands-off Agent | $5,000 cash | 1 | $5,000 cash |
| 4 | Path B: Bring Your Own | Best Assisted Agent | $4,000 cash | 1 | $4,000 cash |
| 5 | Path B: Bring Your Own | Best Supervised Agent | $4,000 cash | 1 | $4,000 cash |
| 6 | Path B: Bring Your Own | Best Hands-off Agent | $5,000 cash | 1 | $5,000 cash |
| 7 | Special | Most Stages Covered | $5,000 cash | 2, one from each path | $10,000 cash |
| 8 | Special | Most Environmentally Impactful | $5,000 cash | 1 | $5,000 cash |
| 9 | Special | Most Creative | $4,000 cash | 1 | $4,000 cash |
| **Total** |  | **8 categories / 10 awards** |  |  | **$45,000 cash** |

Source: [official rules, section 8](https://gitlab-transcend.devpost.com/rules), cross-checked against the [overview prize listing](https://gitlab-transcend.devpost.com/#prizes).

## Totals by group

| Group | Categories | Awards | Cash |
|---|---:|---:|---:|
| Path A: Start Fresh | 3 | 3 | $13,000 |
| Path B: Bring Your Own | 3 | 3 | $13,000 |
| Special prizes | 3 | 4 | $19,000 |
| **Total** | **8** | **10** | **$45,000** |

These totals are calculated from the published prize table. There are no separate sponsor-tool prize categories; the GitLab Duo Agent Platform is part of the project eligibility and judging requirements.

## What the hackathon requires

Every project must use the [GitLab Duo Agent Platform](https://docs.gitlab.com/user/duo_agent_platform/), including features such as agents, flows, or MCP clients. The project must choose one path and one autonomy level.

| Requirement | Path A: Start Fresh | Path B: Bring Your Own |
|---|---|---|
| Starting point | New AI-powered project on GitLab | Existing MIT-licensed open-source project, yours or a fork |
| Required new work | App, CI/CD pipeline, and post-code automation created for the hackathon | GitLab-based post-code automation and deployment created on or after October 5, 2026 |
| Deployment | Optional, but Google Cloud can add up to 0.2 bonus points | Required; deploy anywhere, with Google Cloud eligible for up to 0.2 bonus points |
| Extra URL | None | URL to the original MIT-licensed project |
| Best fit for HABITAT | Weaker, because the project already exists | Stronger, provided the license, import, automation, and deployment requirements are satisfied |

### Autonomy levels

| Level | Meaning in the rules | HABITAT interpretation |
|---|---|---|
| Assisted | Agents propose each step and wait for approval before proceeding | Owner approves the plan, MR, fixes, scans, and release steps individually |
| Supervised | Agents execute a multi-step workflow and the human approves the outcome | GitLab agents take a change through the pipeline and report a release candidate; the owner approves the final outcome |
| Hands-off | The intent starts a full code-to-production loop with no human in the middle | A bounded issue triggers agents to plan, code, verify, secure, merge, deploy, validate, and summarize without a manual gate |

The examples in the rules are illustrative. The judges expect a non-trivial workflow that goes beyond a single review comment or one generated code change.

## HABITAT + GitLab agent strategy

HABITAT should be the product being improved and operated; GitLab should be the agentic delivery system that governs what happens after code is written. The demo should make this distinction visible.

### Proposed agent and flow set

| GitLab component | Responsibility in the HABITAT demo | Evidence to show |
|---|---|---|
| Habitat Planner Agent | Reads a GitLab issue, turns it into acceptance criteria, identifies affected trust boundaries, and proposes a plan | Issue comment with the plan, risk classification, and test plan |
| Habitat Builder Agent | Creates a branch and merge request, implements the change, and updates tests and documentation | A real MR with commits and changed files |
| Review and Security Agent | Reviews the MR, checks policy and secrets handling, interprets scan results, and either approves or commits a fix | Review findings, security scan output, and a remediation commit |
| Verification Flow | Runs unit, integration, contract, and end-to-end checks, including an over-budget or revoked-access case | Visible pipeline history with passing and intentionally failing checks |
| Release Flow | Builds the artifact, publishes the package or image, deploys a preview/staging environment, and runs smoke tests | Build/package evidence, deployment link, and smoke-test result |
| Monitor and Governance Agent | Checks health, summarizes changes and evidence, verifies license/DCO/branch policy, and posts an auditable outcome | Issue or MR summary with links to pipeline jobs and deployment evidence |

If the Habitat MCP server is ready, expose a small test-only interface so a GitLab agent can create a test tenant, run a budgeted request, inspect the activity log, and invoke the kill switch. Otherwise, keep the same product-specific checks in CI scripts. Agents must never receive production secrets or bypass Habitat's policy boundary.

### The best demo scenario

Use one trust-critical but compact change, such as **“enforce and surface a blocked over-budget inference request.”** Start with a GitLab issue and show the complete sequence:

1. The planner agent writes the acceptance criteria: reserve before dispatch, reject when allocation is insufficient, append an activity event, and show the owner why it was blocked.
2. The builder agent opens an MR that changes the controller, ledger, gateway, and dashboard as needed.
3. The review/security agent finds or confirms the important failure modes: fail-open behavior, duplicate reservations, missing tenant scope, secret leakage, and insufficient test coverage.
4. The verification flow exercises successful, over-budget, concurrent, duplicate, and revoked-access cases.
5. The package and release flow builds a reproducible artifact and deploys a preview or staging instance.
6. The monitor/governance step checks health, collects evidence, and posts a plain-language summary to the issue.

For a supervised submission, the human approves the release candidate after reviewing the summary. For a hands-off submission, run the same workflow against a disposable demo environment and let the flow complete the release automatically.

## Most Stages Covered plan

GitLab names nine DevSecOps lifecycle stages: **plan, create, verify, package, secure, release, configure, monitor, and govern**. The special prize is awarded to one project from each path that touches the most stages in the most creative way. HABITAT can credibly touch all nine:

| Stage | HABITAT implementation | Proof for the submission |
|---|---|---|
| Plan | Issue-to-acceptance-criteria and risk-planning agent | Issue history and planner-agent output |
| Create | Builder agent creates the branch, implementation, tests, and MR | MR commits and changed files |
| Verify | CI runs unit, integration, contract, concurrency, and end-to-end tests | Pipeline jobs and test results |
| Package | Build a pinned container or release artifact and generate an SBOM | Artifact link and package job |
| Secure | SAST, dependency, secret, and container checks; security agent remediates findings | Scan reports and remediation MR commit |
| Release | Agentic flow deploys the validated artifact to preview/staging or the bounded demo environment | Deployment job and live URL |
| Configure | Environment configuration, policy defaults, migrations, feature flags, and resource limits are applied through reviewed files | Configuration job and deployment manifest |
| Monitor | Smoke tests, health checks, logs, and basic run metrics feed the release summary | Health evidence and monitor-agent comment |
| Govern | Protected branches, MR approvals, MIT license/DCO checks, audit links, and owner-visible outcome summary | Governance job and final issue/MR record |

The narrative should be “one issue becomes a verified, governed Habitat release,” not “we used many unrelated GitLab features.” Stage coverage is valuable only when each stage contributes to the same end-to-end outcome.

## Google Cloud bonus

Google Cloud deployment is optional for both paths. A qualifying deployment can add **up to 0.2 points**, once, after the judges score the project; the maximum final score is 5.2. To qualify, the public GitLab repository must include the Google Cloud deployment code and the submission must provide a public live project URL available to judges.

Use Google Cloud only if it is low-risk for the build. Path B allows deployment anywhere, so the bonus should not displace the core proof of GitLab agent orchestration, Habitat's controls, or a reliable demo. If we retain the current Render direction, document that deployment and skip the 0.2-point bonus unless a small, reproducible Google Cloud deployment can be added without weakening the submission.

## Most Environmentally Impactful option

This is an opt-in special prize. The submission must explain exceptional sustainability practices from model and pipeline optimization through energy-efficient architecture choices and quantify the gain using current public measurement methods and SCI frameworks.

A credible HABITAT entry could measure a baseline against an optimized workflow using:

- diff-aware agent invocation so unchanged lifecycle stages do not rerun;
- bounded model context and output budgets, with summaries passed between agents instead of full logs;
- cached dependencies and artifacts, plus right-sized runners and short-lived preview environments;
- early failure on policy, formatting, and unit checks before expensive integration or deployment jobs;
- measured CI/runtime energy and carbon estimates reported with the methodology, assumptions, and uncertainty.

Do not opt in based only on using fewer tokens or saying that agents are efficient; the rules expect a quantified sustainability case.

## Judging and scoring

There is a two-stage baseline and a possible Google Cloud bonus:

1. **Stage One, pass/fail:** the idea must reasonably fit the theme and reasonably use GitLab Duo Agent Platform.
2. **Stage Two, equally weighted:** technological implementation, design, potential impact, innovation/idea, and presentation.
3. **Stage Three:** a qualifying Google Cloud deployment adds up to 0.2 points.

The five main criteria reward the same things HABITAT already needs for a convincing demo:

| Criterion | What HABITAT must make obvious |
|---|---|
| Technological implementation | GitLab agents and flows genuinely automate a non-trivial post-code lifecycle, with visible pipeline history |
| Design | The issue-to-release experience is coherent and understandable, not a collection of disconnected agent demos |
| Potential impact | Small teams can ship a trust-sensitive agent platform with less operational burden and better evidence |
| Innovation / idea | HABITAT applies agentic automation to the difficult control, budget, security, and governance work after code exists |
| Presentation | A short video clearly shows the automation running end-to-end and explains the owner problem |

## Submission requirements and checklist

The submission must include:

- A project built with GitLab Duo Agent Platform features.
- A text description of what it does, the problem it solves, and how GitLab automates the post-code lifecycle.
- A public GitLab repository containing all source, assets, and run instructions.
- An MIT license file visible near the top of the GitLab project page in the About section.
- Visible CI/CD pipeline history showing the automation running.
- For Path B, the URL of the original MIT-licensed open-source project.
- For Path B, a public deployment URL that remains available until winners are announced on or around November 16, 2026.
- A publicly visible YouTube demonstration video shorter than three minutes, showing the project functioning on the device/platform for which it was built.
- English submission materials, or English translations of the description, video, and testing instructions.

Video and submission safety:

- Do not put provider, GitLab, deployment, payment, or tenant secrets in the repository, logs, screenshots, or video.
- Do not include copyrighted music or third-party trademarks/material unless permission has been obtained; the rules place this responsibility on the entrant.
- Show enough real pipeline and agent evidence that judges can distinguish a working automation from a prerecorded narrative.
- Keep the deployed demo available and free to access for judging/testing through the judging period.

## Entry and implementation checklist

| Order | Action | Why it matters |
|---:|---|---|
| 1 | Join the hackathon on Devpost | Required registration |
| 2 | Register as a GitLab Contributor | GitLab says approval takes about 24 business hours and provisions the hackathon group, subgroup, project, and onboarding issue |
| 3 | Add an MIT `LICENSE` to HABITAT and verify the repository history | Required for the Path B source project and submission repository |
| 4 | Import or mirror HABITAT into the provisioned public GitLab project | Establishes the Bring Your Own baseline |
| 5 | Record a baseline: manual lifecycle, existing tests, deployment state, and the changes made after October 5 | Path B asks what was added or changed during the Submission Period |
| 6 | Implement the issue-to-release agent and flow set | Creates the actual hackathon contribution |
| 7 | Cover the nine stages and make pipeline history visible | Supports Most Stages Covered and technological implementation scoring |
| 8 | Deploy and test the project; decide whether Google Cloud is worth the 0.2 bonus | Path B requires deployment; Google Cloud is optional |
| 9 | Record a sub-three-minute demo and prepare the README/testing instructions | Presentation and judge access are explicit requirements |
| 10 | Submit before **October 27, 2026 at 1:00 pm UTC / 9:00 am Eastern** | The deadline is hard; drafts cannot be changed after the Submission Period closes |

## Official schedule

| Event | Date and time |
|---|---|
| Registration opens | September 29, 2026 at 10:00 am UTC |
| Submission Period opens | October 5, 2026 at 10:00 am UTC |
| Build Session listed on the overview | October 9, 2026 at 10:00 am Eastern |
| Submission deadline | October 27, 2026 at 1:00 pm UTC / 9:00 am Eastern |
| Judging | October 28 at 10:00 am UTC through November 14, 2026 at 5:00 pm UTC |
| Winners announced | On or around November 16, 2026 at 2:00 pm UTC / 10:00 am Eastern |

Source: [official rules, section 1](https://gitlab-transcend.devpost.com/rules) and the [hackathon overview](https://gitlab-transcend.devpost.com/). The live rules control if the schedule or requirements change.

## Open decisions for HABITAT

- Add and review the MIT license before treating Path B as available.
- Confirm the GitLab Contributor onboarding account and provisioned project after approval.
- Choose the smallest real Habitat change that exercises the trust boundary and can be demonstrated in under three minutes.
- Decide whether the release posture is honestly supervised or whether a disposable, reversible environment makes hands-off credible.
- Decide whether to keep the Render deployment plan or add a separate Google Cloud deployment for the 0.2-point bonus.
- Decide whether enough baseline data can be collected to opt into the environmental prize without making unsupported claims.

The core narrative should stay focused: **HABITAT gives agents bounded authority; GitLab agents make the system itself move from intent to a tested, secure, observable, governed release.**
