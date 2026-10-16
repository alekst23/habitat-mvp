# Automatic acceptance and persistent execution goals

Status: **Project 1.9.0 and Development 1.11.0 published, enabled and fully read
back on 2026-10-16 UTC.** Source and both maintenance branch syncs are merged.
Final ticket verification/acceptance passed; its pipeline **failed overall** on
unconfigured source-security. Security and live recovery remain open. No E11 agent
continuation, checkpoint edit, budget reset, application MR merge or deployment
is part of this publication record.

## What changes

- One approved objective remains owned across bounded sessions. Planning/design
  decisions remain interactive. Technical diagnosis, checks, supported recovery
  and independent review stay with the supervisor.
- Committed branch/issue mappings select acceptance scope. Candidate context
  carries ticket scope through integration; final epic docs prepare whole-epic
  scope. Browser needs come from the manifest, not a user switch.
- A separate mandatory whole-epic MR gate prevents ticket-only evidence from
  making the epic merge-ready. Wrong ticket/epic MR destinations fail validation.
- Workflow-only maintenance can be classified from a complete verified ancestor
  diff and reviewed path allowlist. It reports not-applicable, never an application
  pass; mixed application changes cannot use that path.
- The ordinary push/MR pipeline provides evidence. A correct new report reopens
  an evidence-blocked verification phase only through `resume-evidence`; the
  verifier and independent reviewer still run. Existing counters/history survive.
- A real human merge can reopen a permission-blocked integration through a
  verified `resume-integration` receipt. The worker reconciles the saved merge
  read-only; it never retries the merge or unlocks dependents from prose alone.
- Workers save coherent increments before their soft deadline. A safe checkpoint,
  abrupt interruption, failed acceptance and an actual access/approval blocker
  are different outcomes. Green tests alone do not complete a ticket.
- Project gives one immediate action at a real boundary. A pending note approval
  is an approval, not a completed write followed by a second manual CI chore.

The branch scope protocol is in [acceptance-evidence.md](acceptance-evidence.md);
the recovery protocol is in [single-shot-development.md](single-shot-development.md).
Neither expands tools, grants merge permission nor turns a chat into a scheduler.
Security/delivery checks remain fail-closed; passing ticket ACs does not authorize
release or excuse unrelated failing mandatory merge controls.

## What we adopted from goals

GitLab's [Duo CLI goal loop](https://about.gitlab.com/blog/gitlab-duo-cli-drives-automation/)
keeps working toward an outcome and independently checks completion, within
configured limits. CTX already has native delegated workers plus a deterministic
journal; this change strengthens that ownership/check/recover loop rather than
replacing it with a generic Developer flow or nested CLI. The goal is verified
completion, not merely a worker's final message. Model judgment does not replace
AC artifacts, actual GitLab job results or independent review.

The local inference is to save smaller durable increments and reconcile them at
the next authorized session. A soft save deadline cannot prevent runtime crashes;
we do not claim a hard worker timeout or unattended cross-session restart.
Project can continue the original objective on `check progress` after ownership
and budget checks. Native pending approvals still require their actual control.

GitLab's [variable precedence](https://docs.gitlab.com/ci/variables/#cicd-variable-precedence)
means YAML defaults cannot reliably displace stale project settings. Therefore
scope is resolved inside the reviewed adapters, and CI job activation uses
committed plans, not those variables. Old values may remain configured but are
ignored as inputs. No additional scopes, personal tokens or project-variable
permissions are required. The optional controller remains disabled.

## Validation and rollout

Local checks:

```sh
python scripts/ctx_workflow.py validate
python -m unittest discover -s tests/workflow -v
```

Fixtures cover stale project variables, MR source refs, ambiguous identities,
ticket-to-epic context, whole-epic scope, required/browser-not-applicable behavior,
spent transient retries, preserved repair/action history and fresh review after
recovery. These are protocol tests, not an E11 application pass or live Duo proof.

Initial local validation on 2026-10-16: all 232 workflow tests passed, repository contract
validation passed, structural design validation passed (the main-branch E11 plan
remains planning-only, not implementation-ready), and `git diff --check` passed.
The wrong-ticket regression was run against the original `origin/main` acceptance
adapter: it returned success for an E11-1 report on an E11-2 branch; the corrected
adapter rejects it. Independent local CI and journal/handoff reviews passed after
fixing the epic pre-merge gate, maintenance path and human-merge resume gap.
These reviews are not native GitLab approval. The subsequent CI, sync and catalog
readbacks below supersede the initial local-only status, not the pending live
recovery or required browser-execution evidence.

## Publication and synchronization evidence

Verified release readbacks on 2026-10-16 UTC:

- **Project 1.9.0:** enabled/private, exact unchanged 24 tools, unchanged description
  and no external MCP. Complete saved prompt: 39,817 bytes, equal to the 39,818-byte
  source after removing its final newline. Source SHA-256:
  `303810d6b9cd60b84d1680ba6398d315720b1b11e8c04bd083cec2fcccb57702`;
  saved SHA-256:
  `a8b44db7e05514b7f2c31d8bde7bceeca26c57c9f81f6a430660f7c50a1120ee`.
- **Development 1.11.0:** enabled/private, same service account and active
  Mention/Assign/Assign reviewer triggers, unchanged tools and 64-delegation cap.
  Complete saved YAML: 40,932 bytes, equal to the 40,933-byte source after removing
  its final newline. Source SHA-256:
  `edd61f87b3de0732683b7a47db4e16d77455d25a3d96449a252c9523145f4899`;
  saved SHA-256:
  `54e4a3995002ce8f4659cf1b0e7ee7e98bbfe50f5c46ff6b8fc9ff2a8026e124`.

Both payloads come from reviewed source
`4f56e11fff5decb6bd43a16904f84f5210fad7f4`. The Project binding records release-time
Development version 1.11.0 and date 2026-10-16. Numeric consumer `12316920` and
catalog item `1016234` are retained unchanged from the reviewed binding; the
consumer was **not newly queried through native discovery** for this release.
UI enablement/service identity readback is not fresh API eligibility, ownership
clearance or proof that a native tool exposes runtime version. Preflight remains
required; preserve `not_exposed` where appropriate.

| Maintenance change | Reviewed source | Verified merge commit | Passing CI |
| --- | --- | --- | --- |
| [Source !60](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/60) into main | `4f56e11fff5decb6bd43a16904f84f5210fad7f4` | `f4c7f09f11a680ce72b88c029a5b3ae085f566f3` | [2956257602](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2956257602) |
| [Epic sync !61](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/61) into `ctx/epic-i11` | `f96c20f2de5f4f1517ed1167c609ba10c84e50d7` | `318d2883f8a5ebc301767ea26fd9644b84652c95` | [2956258905](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2956258905) |
| [Ticket sync !62](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/62) into `ctx/ticket-i13` | `3d10d11dd45a9ff6a6cc0f195816ef6840bb923e` | `ee86c6b2d52341b7a9bc1e3bd2a9509d9f7ac857` | [2956261588](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2956261588) |

Two independent local source reviewers passed; their results were relayed in
note `4031025070`. Native Duo source review failed with HTTP 502 and then a review
lock. Epic sync's independent local review is note `4031026495`; native Duo review
failed HTTP 503. Ticket sync's independent local review is note `4031035383`, with
238 local tests passing. These are local independent reviews, **not native Duo
approval**; passing CI is recorded separately from review provenance.

The final ticket marker candidate
`1e86671774206eb0cb7eb4c97867fc91a8c6a401` passed independent review of the complete
32-file maintenance diff from the old candidate, plus 238 local tests and contract
validation. E11 acceptance-manifest SHA-256 is unchanged:
`7950f2341e00c03f4e59beb2b82c79c885bbfd3b1d38025e26c1292994975dba`.
Its ordinary [pipeline 2956291204](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2956291204)
finished at this exact SHA with the following read-back results, not the earlier
sync-MR pipeline's evidence:

| Check | Result |
| --- | --- |
| Workflow validate/tests/design | Passed. |
| [ctx:verify 17241593113](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/jobs/17241593113) | Passed: 47 tests, one warning; correct E11-2 candidate context. |
| [ctx:acceptance 17241593114](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/jobs/17241593114) | Passed: `passed=true`, `criteria_total=1`, `scope=E11-2`, exact candidate SHA and manifest hash above, `browser_required=false`, `mode=application`, branch `ctx/ticket-i13`. `.ctx/reports` and `.ctx/acceptance.json` artifacts uploaded with HTTP 201. |
| [ctx:browser 17241593112](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/jobs/17241593112) | Job succeeded as expected N/A: "Browser not applicable to this checked context; no browser pass claimed." No real browser execution is claimed for this non-UI scope. |
| [ctx:source-security 17241593115](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/jobs/17241593115) | **Failed**, exit 2: `source-security command is not configured; application foundation required`. |

The overall pipeline is **failed**, not green. Source-security remains a separate
security/merge gate; these acceptance results do not waive it, change its adapter
or grant merge/deployment authority. Independent local maintenance review is
[!59 note 4031054561](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/59#note_4031054561),
not native or application-review approval. No application-code change or checkpoint/
budget reset is claimed. Live maintenance adoption, coordinator verification of the
full evidence bundle, independent ticket review and integration recovery remain
pending. Passing the CI acceptance job alone does not advance the blocked journal
or complete E11-2.

## Remaining rollout validation

1. Retain the failed source-security result as an open gate. Its adapter requires
   separately scoped foundation work and independent review; do not weaken or
   bypass it in this publication update. The recorded ordinary candidate pipeline
   supplies E11-2 verification/acceptance evidence without manual scope overrides,
   not an all-checks-passing or merge-ready verdict.
2. A changed maintenance SHA invalidates old evidence. Before resuming E11, the
   coordinator must verify the scoped maintenance diff/review/authorization,
   new candidate identity and fresh CI, then use the supported maintenance
   adoption in `resume-evidence`. No code/AC drift may be hidden in that receipt.
3. With the exact candidate CI results read back, the user's ordinary authorized
   `check progress` resumes ownership checks and supported recovery. Observe
   verification -> independent review -> the actual permitted integration path.
   If merge capability is denied, Project gives one exact human merge action only
   after the required gates pass; afterward it verifies integration before
   advancing dependents. No claim of live success until this is observed.

New sessions, retries or an empty commit are not ways to obtain new budgets.
If authority or candidate reconciliation cannot be established, retain the full
checkpoint and identify the exact missing approval/access, not a variable tutorial.
