# CTX delivery readiness and stage evidence

Status: local, unactivated implementation. This adds a deterministic evidence
consistency check, not application build/scan/deployment adapters or nine-stage
operational coverage. No deployments or credential/control changes were made.

## Execution and authority

Workflow validation/tests now run on merge requests and the default branch without
`CTX_WORKFLOW_CHECKS=1`. Other branch runs can still opt in. This does not change
the opt-in application lane or GitLab merge protections.

Within the application lane, `ctx:delivery-readiness` runs only on the default
branch, after collecting verify, acceptance, source-security, package,
artifact-security and configure reports. It uses `when: always` to retain a
diagnostic report when prerequisites fail; missing or failed artifacts cannot pass.
A feature MR is not required to prove it is already merged.

```sh
python scripts/ctx_delivery.py --phase candidate
```

The command requires a clean checkout matching `CI_COMMIT_SHA`, numeric
`CI_PROJECT_ID` and `CI_PIPELINE_ID`, canonical `CI_PROJECT_URL`, and matching
`CI_COMMIT_BRANCH`/`CI_DEFAULT_BRANCH`. It reads `.ctx/reports/<name>.json` and
writes `.ctx/reports/delivery-readiness.json`. Exit 0 means all required receipts
are structurally consistent; exit 2 means blocked. It performs no network writes,
deployment, approval or signing. It rejects duplicate JSON fields and symlink inputs.

`evidence_complete` is NOT an assertion that the jobs really ran, nor a deployment
grant. Every result states `authorizes_deployment: false` and
`remote_verification: required`. The independent reviewer must read actual GitLab
jobs, artifacts, repository state and approvals. Controlled CI jobs must produce
receipts from those observations; a model must never invent them to make a gate pass.

## Four evidence phases

| Phase | Required evidence | What is still not implied |
|---|---|---|
| `candidate` | Six existing CI receipts plus plan, merged change and governance | Deployment, applied configuration or healthy service |
| `staging` | Candidate plus staging deployment/configuration application and monitoring | Production approval or promotion |
| `promotion` | Healthy staging, reviewed production configuration and independent human outcome approval | Production has deployed |
| `production` | Promotion plus matching production deployment and post-deployment monitoring | Authority to perform another deployment |

Every report records the requested phase, candidate SHA/pipeline/project, package
digest, configuration hashes, blockers and all nine lifecycle stages with evidence
links. The Configure stage remains incomplete until a deployment receipt records
actual application. Production must use the same package digest as staging; its
separate configuration hash must match the approved one. Changes invalidate dependent
receipts. Approval must identify the same deployment and predate deployment. Health
observations must identify that deployment and begin after it.

All receipts in an assessment use the **same release pipeline identity**. Initial
planning/design may have occurred earlier; a plan receipt revalidates their committed
references for this candidate, not a claim that the interview ran again. Cross-pipeline
deployment receipts are currently unsupported: implement and independently review
an explicit provenance handoff before using a separate deployment pipeline.

## Receipt schema

Existing six command receipts retain the schema in
[the implementation guide](gitlab-workflow.md#application-command-and-evidence-contract).
Additional receipts have the same envelope:

```json
{
  "step": "plan",
  "status": "passed",
  "project_id": "ACTUAL_PROJECT_ID",
  "source_sha": "ACTUAL_40_HEX_RELEASE_SHA",
  "pipeline_id": "ACTUAL_RELEASE_PIPELINE_ID",
  "evidence": {
    "source_sha": "ACTUAL_40_HEX_RELEASE_SHA",
    "report_url": "https://gitlab.com/GROUP/PROJECT/-/jobs/ACTUAL_JOB_ID/artifacts/file/REPORT.json",
    "source_issue_url": "https://gitlab.com/GROUP/PROJECT/-/issues/ACTUAL_SOURCE_IID",
    "epic_url": "https://gitlab.com/GROUP/PROJECT/-/issues/ACTUAL_EPIC_IID",
    "spec_sha": "ACTUAL_40_HEX_DESIGN_SHA",
    "design_confirmed": true
  }
}
```

The example is schematic, not valid evidence. All reports require a same-project
CI job/artifact `report_url` and matching source SHA. Additional fields:

| Receipt | Required evidence fields |
|---|---|
| `plan` | Source issue and epic URLs, committed `spec_sha`, `design_confirmed: true` |
| `create` | Same-project MR URL, `merged: true`, `merge_sha` equal to release SHA |
| `govern` | `checks` and `control_urls` for license, DCO, branch protection, merge policy and environment protection; staging environment, package digest and staging configuration hash |
| `configure-production` | Production environment, package digest, 64-hex `configuration_revision`, `passed: true`, `protected_environment: true`, same-project `controls_url` |
| `approval-production` | Production environment, digest/configuration, positive deployment ID, distinct positive approver/initiator IDs, `approval_kind: protected_environment`, `decision: approved`, timestamp `approved_at`, same-project environment/deployment `approval_url` |
| `release-staging`, `release-production` | Target environment, digest/configuration, deployment ID/URL, environment URL, `deployed: true`, `configuration_applied: true`, timestamp `deployed_at` |
| `monitor-staging`, `monitor-production` | Matching target/digest/configuration/deployment ID/environment URL, `checks` for health/smoke/logs/metrics all passed, timezone-aware `observed_from` and `observed_until` |

Governance check values must all be `passed`. Stage verdicts cannot be waived with
`not_applicable` in this initial contract. An MR approval or a manual-job click is
not a protected-environment outcome approval. The receipt schema checks that claim;
only GitLab's enforced controls and independent readback can establish its truth.

Synthetic receipt fixtures in `tests/workflow/test_ctx_delivery.py` exercise these
bindings. They are not genuine CI, security, governance or deployment evidence.

## Remaining activation work

1. Merge/review the workflow changes, then publish the existing Duo catalog entries
   separately. A repository merge alone does not update registered flows.
2. Deliver the application foundation: real tests, build recipe, dependency locks,
   source/dependency/secret scanners, package/SBOM producer and artifact scanner.
3. Implement independently reviewed plan/create/govern receipt producers against
   GitLab API state, a real MIT license/DCO policy, and actual protected controls.
   None currently exists; the new candidate gate correctly blocks without them.
4. Confirm the target (the current product design names Render), configuration,
   recovery/migrations, and supported environment/approval controls. Keep credentials
   in isolated deployment jobs, not Duo agent sessions.
5. Add reviewed deployment, monitor and promotion executors. No live deploy job is
   supplied by this change. Protect the target and enforce the outcome gate before
   adding credentials. Verify capability on the actual GitLab tier: protected
   environments are documented for Premium/Ultimate.
6. Exercise one real change end-to-end and retain the evidence, including failures
   and repairs. Receipt validation alone must never be presented as prize coverage.

References: [GitLab job rules](https://docs.gitlab.com/ci/jobs/job_rules/),
[protected environments](https://docs.gitlab.com/ci/environments/protected_environments/),
[deployment safety](https://docs.gitlab.com/ci/environments/deployment_safety/).
