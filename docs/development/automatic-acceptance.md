# Automatic acceptance and persistent execution goals

Status: local candidate, 2026-10-16. Project 1.9.0 and Development 1.11.0 are
proposed releases, not live publication claims. No E11 continuation, checkpoint
edit, budget reset, application merge or deployment is part of this maintenance.

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

Local validation on 2026-10-16: all 232 workflow tests passed, repository contract
validation passed, structural design validation passed (the main-branch E11 plan
remains planning-only, not implementation-ready), and `git diff --check` passed.
The wrong-ticket regression was run against the original `origin/main` acceptance
adapter: it returned success for an E11-1 report on an E11-2 branch; the corrected
adapter rejects it. Independent local CI and journal/handoff reviews passed after
fixing the epic pre-merge gate, maintenance path and human-merge resume gap.
These reviews are not native GitLab approval. Live CI/browser-container execution,
catalog readback, branch synchronization and E11 continuation remain unperformed.

Release steps, owned by the workflow maintainer:

1. Obtain independent maintenance review and merge the workflow source under
   its existing controls. Do not merge application MRs as part of this release.
2. Reconcile active writers before synchronizing the reviewed helpers/CI/docs to
   the relevant epic AND ticket branches. A default-branch change alone does not
   update an existing ticket's pipeline. Preserve product code, plan/AC bytes,
   commands/adapters, original journal and all notes. Preserve the existing E11
   backend dependency installation when reconciling CI files.
3. Publish the revised Project/Development entries, verify full saved prompts,
   unchanged tools/visibility/identities and the actual enabled consumer/version.
   Update publication records only from readback; do not fabricate activation.
4. Validate CI on the synchronized candidate with old scope variables deliberately
   left in place. For `ctx/ticket-i13`, scope must be E11-2 and the manifest hash
   must match committed E11 acceptance bytes. No manual pipeline overrides.
   Use ordinary maintenance commit CI, not an E11 agent start, for this check.
5. A changed maintenance SHA invalidates old evidence. Before resuming E11, the
   coordinator must verify the scoped maintenance diff/review/authorization,
   new candidate identity and fresh CI, then use the supported maintenance
   adoption in `resume-evidence`. No code/AC drift may be hidden in that receipt.
6. After publication and branch-sync readback, the user's ordinary authorized
   `check progress` resumes ownership checks and supported recovery. Observe
   verification -> independent review -> the actual permitted integration path.
   If merge capability is denied, Project gives one exact human merge action only
   after the required gates pass; afterward it verifies integration before
   advancing dependents. No claim of live success until this is observed.

New sessions, retries or an empty commit are not ways to obtain new budgets.
If authority or candidate reconciliation cannot be established, retain the full
checkpoint and identify the exact missing approval/access, not a variable tutorial.
