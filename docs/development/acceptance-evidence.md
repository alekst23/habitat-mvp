# Acceptance-criteria evidence

Tests should be few; coverage claims must still be explicit. One executed test may
prove several criteria. The reviewer decides whether its assertions actually prove
them; the acceptance job checks completeness and identity, not semantic correctness.

## Committed requirements

Planning creates `docs/plan/E2/acceptance.json` from
`.gitlab/ctx/templates/acceptance.json`, replacing all example statements. Example:

```json
{
  "version": 1,
  "epic": "E2",
  "criteria": [
    {"id": "E2-1.AC1", "statement": "An over-budget request cannot dispatch.", "ui": false, "methods": ["test"]},
    {"id": "E2-1.AC2", "statement": "The user sees why the request was blocked.", "ui": true, "methods": ["browser"]}
  ]
}
```

IDs are stable and unique. Required methods are `test`, `browser`, or `inspection`;
UI criteria must include `browser`. Use inspection for justified documentation or
low-risk changes, not as a way around missing runtime checks. That criterion also
needs `inspection_reason` explaining why executable coverage adds no value.
Do not remove or weaken criteria to pass a failed check; intent changes need review.

## Automatic candidate scope (local revision; publish and sync before use)

Ordinary MR/push pipelines activate application checks when a committed
`docs/plan/E*/state.json` exists. No manual application/browser switches, manifest
path or scope variables are needed. `scripts/ctx_ci_context.py resolve` uses the
MR **source** branch (or branch pipeline ref), committed version-2 issue/branch
mappings and `docs/plan/<epic>/acceptance.json`. Unknown/ambiguous branches,
wrong projects, uncommitted inputs and wrong-SHA candidates fail closed.
Old `CTX_APPLICATION_CHECKS`/`CTX_BROWSER_CHECKS` values no longer gate jobs.
Old `CTX_AC_SCOPE`/`CTX_AC_MANIFEST` values cannot choose scope: the adapter runner
overwrites them with derived values only as internal compatibility outputs to
existing reviewed adapters. Acceptance and the browser reporter resolve independently.

Before saving a ticket candidate, its implementation worker runs:

```sh
python scripts/ctx_ci_context.py prepare
```

This writes `.gitlab/ctx/verification-context.json` from that branch's plan, without
a user-selected ticket argument. Commit it with the candidate, before tests and
review. This narrowly authorized candidate-data file is not permission to modify
CI policy. Its scope travels through the ticket merge so CI can verify that ticket
again at the resulting epic SHA. A stale context from another ticket is rejected,
not silently reused. A legacy ticket without the file still resolves from its
branch; adding the file later changes SHA and invalidates old evidence/review.

After all tickets integrate, the epic docs worker runs `prepare --whole-epic`
on the epic branch and commits the result BEFORE full-epic verification/review.
The mandatory `ctx:epic-scope` MR gate rejects partial scope before default merge.
Ticket-scoped jobs still run on the draft epic MR for post-integration evidence;
their green status does not make that epic MR merge-ready. Ticket MRs must target
their own epic, and epic MRs must target default; cross-epic/direct-ticket-to-default
MRs fail identity validation. Default-branch verification requires whole-epic context. An epic
without a context defaults to whole-epic scope; it never guesses the last ticket.
The journal still requires ticket-scoped post-integration evidence and whole-epic
evidence for final review. Never silently narrow an epic completion claim.
Do not rewrite a reviewed candidate's context after review. Parallel writers must
reconcile context conflicts under the existing merge/re-review rules.

Browser applicability comes from the selected criteria. A non-UI scope produces
only an explicit not-applicable diagnostic, not a synthetic browser pass. A UI
scope runs the pinned browser harness and fails when prerequisites/evidence are
missing. Workflow-only branches without a plan remain structural-only, not app
verification. An unmapped branch can produce a structural-only maintenance result
only when its complete ancestor diff proves exclusively reviewed workflow paths
(`MAINTENANCE_FILES`/`MAINTENANCE_PREFIXES` in the resolver). Its MR target must be
a known ticket/epic/default branch. CI retains full history to verify the diff base.
Application, plan, AC, command-adapter, credential or checkpoint-policy changes
cannot use this exemption. Mixed diffs and missing/unknown bases fail closed.
Planned ticket/epic refs always run application checks, even for maintenance-only
diffs. Maintenance jobs return explicit `not_applicable`, never passing AC evidence;
merge still needs independent maintenance review and existing controls.

The reviewer still compares the mapping and manifest against the intended task,
actual jobs, assertions and current SHA. Scope consistency is not semantic proof.

## Verify adapter output

The application foundation supplies the real `verify` command in `commands.yml`.
It runs the minimal applicable tests and writes ordinary step evidence to
`CTX_OUTPUT` (see [workflow guide](gitlab-workflow.md)). It ALSO writes
`.ctx/acceptance.json` for the selected scope, including browser-only criteria:

```json
{
  "version": 1,
  "project_id": "87271414",
  "source_sha": "<CTX_SOURCE_SHA>",
  "pipeline_id": "<CI_PIPELINE_ID>",
  "scope": "E2-1",
  "manifest_sha256": "<SHA-256 of the committed manifest bytes>",
  "criteria": [
    {
      "id": "E2-1.AC1", "status": "passed", "code": "src/budget.ts:reserve",
      "evidence": {"test": {"status": "passed", "test_ids": ["budget rejects dispatch"], "url": "https://gitlab.com/group/project/-/jobs/123"}}
    },
    {"id": "E2-1.AC2", "status": "pending-browser", "code": "src/BudgetNotice.tsx", "evidence": {}}
  ]
}
```

These are examples, not fabricated execution results. Identity values are strings;
SHA and hash values must be populated from the actual candidate and manifest.
Every criterion needs a code/document reference. An `inspection` evidence entry
uses `status`, HTTPS `url`, and `reason` describing the observed result instead of
`test_ids`. Reusing a test ID across criteria is supported and encouraged where valid.

`ctx:browser` independently produces `.ctx/browser/acceptance.json` from executed
Playwright tests annotated with AC IDs. It has the same identity/hash fields and
only the browser criteria, each with `evidence.browser.status`, `test_ids` and URL.
The acceptance adapter merges that evidence into the verify report in memory;
a builder's self-reported browser pass cannot substitute for the browser job.

## Gates and limitations

`ctx:acceptance` downloads verify/browser artifacts and runs
`scripts/ctx_acceptance.py` through the normal clean-checkout evidence adapter.
It checks exact scope coverage (no missing, extra or duplicate IDs), each required
method, actual test-ID references, nonempty inspection results, HTTPS links and
matching project/SHA/pipeline/scope/manifest hash. Skipped, failed, flaky or
missing browser runs cannot establish acceptance. Changed commits invalidate evidence.
The resulting `.ctx/reports/acceptance.json` gates downstream delivery jobs.

Ticket review checks each AC against the actual assertions, observed output and
GitLab job status, then records passed/failed/blocked with links. A genuinely
not-applicable requirement needs an explicit reviewed scope decision, not a silently
skipped row. Epic review repeats this across the integrated feature and wiring.
Docs must be complete before final epic review; later commits require new evidence.

This is not cryptographic attestation or a GitLab approval. Reviewed adapters can
still be wrong, and links/hashes do not prove the content behind them. Protect CI
definitions and manifest changes, verify actual job results, require independent
review, and make application checks mandatory before implementation merges.
Workflow-only green pipelines are not application or acceptance evidence.

### Recover an existing evidence stop

A new green pipeline is not itself a journal transition. The coordinator owns
the supported `resume-evidence` protocol in [single-shot development](single-shot-development.md),
then fresh verification and independent review. Keep the original objective,
candidate/history and every consumed action/retry/repair. A new helper-sync SHA
needs explicit reviewed maintenance adoption, never an in-place checkpoint edit.
No user pipeline-variable override, personal token, policy bypass or budget reset.
