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

Use these pipeline variables (example identities, not project defaults):

```text
CTX_APPLICATION_CHECKS=1
CTX_AC_MANIFEST=docs/plan/E2/acceptance.json
CTX_AC_SCOPE=E2-1
CTX_BROWSER_CHECKS=1
```

For whole-epic review, set scope to `E2` and prove every criterion. Set browser checks
only when that scope needs them; missing required browser evidence always blocks.
Use a reviewed branch/ticket-to-scope mapping when making CI mandatory. The verifier
cannot know whether a human or agent selected the wrong ticket: the reviewer must
compare scope with the MR and independently check the manifest against the spec.

## Verify adapter output

Status: `commands.yml` runs the reviewed `scripts/ctx_verify_backend.py` (pytest over
`backend/tests` with `PYTHONPATH=backend`). It writes `CTX_OUTPUT` only when the JUnit
XML counts at least one test and none failed, errored or were skipped, the checkout
is clean at `CTX_SOURCE_SHA` and `CI_JOB_URL` is an HTTPS URL; otherwise it exits 2
and leaves no evidence. `ctx:verify` installs `backend/requirements.txt` when it
exists (E11-1 supplies it). The lane stays opt-in: a maintainer sets
`CTX_APPLICATION_CHECKS=1` (and `CTX_BROWSER_CHECKS=1` for browser scope) with the
manifest variables below. Neither job has run on GitLab yet.

### Acceptance report writer and test-to-AC mapping

The same adapter run now also writes `.ctx/acceptance.json` (already a `.ctx-check`
artifact) for the scope in `CTX_AC_SCOPE`, using the committed manifest named by
`CTX_AC_MANIFEST` and `CI_PROJECT_ID`, `CI_PIPELINE_ID`, `CTX_SOURCE_SHA` and the real
`CI_JOB_URL`. It is written only after the passing pytest run, in the clean candidate.

Tests declare what they prove with the reviewed marker in `scripts/ctx_pytest_ac.py`
(loaded by the adapter; no `conftest.py` or `pytest.ini` is needed):

```python
@pytest.mark.ac("E11-1.AC1", "E11-1.AC2", code="backend/aicl/budget.py:reserve")
def test_reservation_blocks_over_budget(): ...
```

- One test may name several ACs; several tests may name one AC. `code` is required,
  has no whitespace, and must be a tracked repository file with an optional `:symbol`.
  A missing or malformed marker aborts collection and the verify job fails.
- The mapping is read back from the executed run's JUnit XML (marker values are copied
  into test properties). Test IDs are the executed, passing cases (`file::Class::test[param]`),
  never hand-written. The row `code` is the sorted union of the `code` values.
- An AC with a `test` method needs at least one passing mapped test, or the writer fails.
  A UI AC with `browser` stays `pending-browser`; browser-only ACs get no test evidence,
  only the code reference, and the independent `ctx:browser` report must supply the rest.
  Methods other than `test` and `browser` (inspection) cannot be produced here and fail
  closed: use a scope without such ACs, or a separate reviewed inspection writer.
- Fail closed (exit 2, `CTX_OUTPUT` and `.ctx/acceptance.json` removed): missing
  `CTX_AC_SCOPE`/`CTX_AC_MANIFEST`/`CI_PROJECT_ID`/`CI_PIPELINE_ID`, an untracked or
  invalid manifest or out-of-manifest scope, a marker naming an AC not in the manifest,
  any failing, erroring or skipped test, an in-scope AC without a passing mapped test,
  dirty checkout or HEAD different from `CTX_SOURCE_SHA`. Tests for ACs in other
  tickets may still be mapped; only the requested scope is reported.
- The adapter exposes `scripts/` on `PYTHONPATH` for the marker plugin, so backend tests
  could import those helpers; do not depend on that.

The reviewed `verify` adapter runs the minimal applicable tests and writes ordinary step
evidence to `CTX_OUTPUT` (see [workflow guide](gitlab-workflow.md)). It ALSO writes
`.ctx/acceptance.json` for the selected scope, including browser-only criteria
(schema below; the example identities are illustrative):

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
