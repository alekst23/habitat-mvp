# Exact native checkpoint publication

Status: **Project v1.6.0 and Development v1.10.0 published and enabled**, with full
saved-definition readback on 2026-10-15 UTC. Source and E11 helper synchronization
are merged. Live checkpoint/recovery acceptance remains pending; publication did
not start or authorize an application run.

## Publication evidence

- [Source !49](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/49)
  at `9522bf6c39e6564047a5ea9d775f69de90828f41` merged main at
  `75442835aaecff7fa0f9e0d5b96cd2f7620b7996`. Independent follow-up review
  [4021263981](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/49#note_4021263981)
  confirmed the definite-rejection retry repair and no remaining findings.
- [E11 helper sync !50](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/50)
  at `5fc20b08e101f6647c6214702193c49ead3cf4ef` merged `ctx/epic-i11` at
  `71016e8be0c87217ff89f834a7156a017c5a8de7` after independent review
  [4021234416](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/50#note_4021234416).
  All 17 changed paths are workflow files. E11 design/plan and application
  verification/acceptance adapters remain byte-identical to `7ad45df2`.
- Workflow validation, design validation and workflow tests passed in pipelines
  [2951370940](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2951370940)
  and [2951372315](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2951372315).
  **Overall pipelines failed:** main has no configured application verify adapter;
  E11 has no `backend/tests/` yet. The user explicitly approved these workflow-only
  merges despite those failures. No CI settings, job rules or protections changed;
  these are not application acceptance passes.
- [CTX Project v1.6.0](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/automate/agents/1016538):
  all 30,633 saved prompt bytes equal reviewed source with the final newline
  removed; SHA-256 `cc4dcc0bbea23c0c717546710849ea6a58dfebc7dc3509fc50a574e0b033a7b7`.
  Enabled/private, unchanged description, exact 24 tools and no MCP read back.
- [CTX Development v1.10.0](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/automate/flows/1016234):
  all 40,852 saved YAML bytes equal reviewed source with the final newline
  removed; SHA-256 `dade03331949cede1e5089d75766be7a38b3adc4cdaf7485c65a4371b461791d`.
  Enabled/private, unchanged description/tools, 64 delegations, same service account
  and active Mention/Assign/Assign reviewer triggers read back.

No application MR was merged, source checkpoint rewritten or note deleted. No
application session was started. To resume the previously approved objective, open
a **new CTX Project chat** and send **`Continue E11 using issue #11.`** Project must
reconcile current sessions/state first and use the existing authority, not reset
budgets or duplicate active work. The live acceptance checks below remain required.

## Failure and repair boundary

### Composite-identity repair (candidate; live verification pending)

Sessions **9576995** and **9577108** stopped before dispatch because the old helper
equated `/api/v4/user.id` with the checkpoint author. The first
[stop report](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/issues/11#note_4025119435)
reports `administrator106` / **43066631**; the second
[report](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/issues/11#note_4025138079)
confirms the same rejection but does not expose the resolved ID. Neither report
alone verifies the OAuth token owner. Changing the trigger path is not a remedy.

GitLab's [composite identity](https://docs.gitlab.com/user/duo_agent_platform/composite_identity/)
has a service-account OAuth owner and a human scoped user. Its
[API authentication resolver](https://gitlab.com/gitlab-org/gitlab/-/blob/master/lib/gitlab/auth/auth_finders.rb)
returns the scoped user for composite authentication; its
[scope parser](https://gitlab.com/gitlab-org/gitlab/-/blob/master/lib/authn/scoped_user_extractor.rb)
uses exactly one `user:<id>` scope. A human `/user` result does not mean a personal
token was injected. The new helper checks the actual OAuth owner through the
documented [token information endpoint](https://docs.gitlab.com/api/oauth2/#retrieve-the-token-information),
then binds `/user` to that verified composite identity. It still trusts only
**43132375** as the checkpoint author, not arbitrary human-authored notes.

The read-only diagnostic is `python scripts/ctx_checkpoint.py identity`. It returns
only project, OAuth-owner, scoped-user, effective-user and checkpoint-author IDs
plus a verification result. It never returns token values, raw introspection/user
responses, application metadata or headers. Run it only in a separately authorized
maintenance diagnostic using the existing injected credential; do not start E11 to
test this repair. An introspection denial or identity mismatch fails closed without
falling back to `/user` alone, a personal token, new scopes or a changed writer list.

This is a helper/guide-only change: the existing v1.10.0 catalog prompt already
loads this guide and helper, so no catalog version/tool/trigger change is required.
Independent review and helper synchronization must precede E11 use. Retain the
seven exclusions, checkpoint **4019881978**, all notes, budgets and app MRs !45/!48.

E11's [session 9530877 stop report](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/issues/11#note_4020469403)
identifies repeated transcription of an approximately 54 KB owner payload. Copies
invented resource entries or omitted history; exact comparison and continuation
validation correctly refused dispatch. Fix the transfer, not the validation gate.
Other historical `failed (dropped)` sessions need their own logs; this repair does
not claim to explain or cure every runtime crash.

`scripts/ctx_checkpoint.py` transfers generated files directly between the existing
flow runtime and source-issue notes. It reuses `ctx_owner.py` validation and framing.
It never dispatches, changes branches/ACs, clears claims, grants authority, resets
budgets, alters review gates, or edits/deletes notes. The controller is unaffected.

The official [custom-flow authentication contract](https://docs.gitlab.com/user/duo_agent_platform/flows/custom/#authenticate-to-the-gitlab-api)
provides an injected OAuth credential as `GITLAB_TOKEN` / `GITLAB_OAUTH_TOKEN`;
scripts must send `Authorization: Bearer`, not `PRIVATE-TOKEN`. Only this reviewed
helper reads that credential in memory. It checks the CI project/origin, requires
`/oauth/token/info.resource_owner_id` to equal **43132375**, a positive expiry,
`ai_workflows`, exactly one `user:<id>` scope and optional `mcp` only. It verifies
`/user.id` is that scoped user (or the same service account for compatible older
API behavior). A different owner, absent/ambiguous binding or broader scope fails
closed. Note selection and exact readback still require author **43132375**. It pins
GitLab.com and Showcase **87329027**, refuses redirects/proxies, and exposes only
identity reads plus issue-note list/get/create endpoints. No token flag, arbitrary
URL, generic API verb, personal/controller credential, CLI credential store or new
secret is accepted. Credentials never enter model/tool output, command arguments,
payloads or receipts. Do not inspect the environment or use shell interpolation to
extract tokens. If the runtime credential/identity is unavailable, stop with that
access boundary; do not fall back to a human token or rewrite JSON by hand.

## Read, assemble, publish

The supervisor still verifies the human objective, later pause/scope/decision notes,
actual session status, current heads and exclusive ownership. The helper verifies
transport and consistency, not those remote decisions, reviewer independence or an
atomic epic lease. Run it only from the reviewed coordinator/default source, never
a worker-modified implementation checkout. Do not self-edit it to bypass a gate.

1. **Read directly to files.** The helper paginates all source notes, retains their
   server IDs/authors and original bodies, applies only the reviewed exclusions,
   then selects and validates the compatible full checkpoint. It writes `notes.json`,
   `handoff.json`, `closure.json` and `journal.json` into a NEW scratch directory.
   The output is a small receipt, not full JSON for the model to copy.

   ```sh
   python scripts/ctx_checkpoint.py read --source-issue 11 --epic E11 --output-dir .ctx/checkpoint/e11-read-01
   ```

   Use a fresh directory per actual read, not an overwrite of locally claimed work.
   The full `notes.json` retains excluded comments and later human decisions for
   reconciliation. Read relevant prose/evidence without asking the model to recreate
   whole note arrays. Explicit verified legacy migration retains `--legacy-note-id`.

2. **Assemble from loaded files.** Copy the downloaded journal as file data into
   its normal `.ctx/development/` path, then use the existing claim/record/repair
   helpers. Reconcile any active claim first. Use `assemble` to splice their actual
   generated journal/closure into a deep copy of the complete downloaded handoff:

   ```sh
   python scripts/ctx_checkpoint.py assemble .ctx/checkpoint/e11-read-01/handoff.json --journal-file .ctx/development/execute-e11-1.json --updates-file .ctx/checkpoint/e11-update-01.json --output .ctx/checkpoint/e11-next-01.json
   ```

   `--closure-file` accepts a complete validated closure object when it changes.
   The small updates file permits only `session`, `decisions`, `resources_append`
   and `closure_returns_append`. Supply observed identities and verified new events;
   do not reconstruct historical arrays. Absent fields are preserved. Session
   reservations and cumulative budgets still follow the existing admission rules.
   Validation rejects changed objectives, lost history and regressed counters.

3. **Publish the generated file once.** Write only the short human summary yourself,
   at most 120 words, without mentions or GitLab quick actions. Do not retype full JSON into a note tool, file tool, heredoc,
   prompt or command argument. The publisher renders, validates against the latest
   complete remote parent, posts the file content, GETs the saved note and compares
   **exact full body plus complete parsed payload**. It rechecks the current selected
   checkpoint before returning `verified: true` with note URL and body SHA-256.
   Pagination uses the documented `created_at` sort field in the
   [GitLab Notes API](https://docs.gitlab.com/api/notes/#list-all-issue-notes);
   checkpoint chronology is validated locally by server note ID.

   ```sh
   python scripts/ctx_checkpoint.py publish .ctx/checkpoint/e11-next-01.json --summary-file .ctx/checkpoint/e11-summary-01.md --previous-note-id 4019881978 --receipt-file .ctx/checkpoint/e11-publication-01.json
   ```

   The parent in this example was the reported valid note at investigation time;
   use the ACTUAL read receipt on every run. Never hard-code it as permanently current.
   `--initial` is only for the explicitly authorized first full owner checkpoint
   after legacy/history reconciliation, never to discard an existing run. It is
   rejected when a full checkpoint already exists. Missing JSON alone does not
   authorize initialization. Application credentials must never appear in payloads.

4. **Dispatch only after verified persistence.** Keep the original run, manifest,
   full history, answers, reservations and budgets. Use the receipt as transport
   evidence, not as authorization or a successful worker/review result. Continue
   normal independent verification and the admission check. Repeat before/after
   each delegation without ending a healthy session.

## Unknown writes and invalid notes

The publisher fsyncs a local intent before one POST. Repeating the command with
the **same file, summary and receipt path** performs read-only reconciliation of
that attempt. An exact existing current note is adopted after GET/readback; a
missing, altered, duplicate or superseded result blocks. A timeout does not cause
another POST. Do not choose a new receipt path, summary, manual note tool or new
session to retry an uncertain publication. Retain the attempt, available note ID
and logs at a real stop. If the runtime dies and loses local files, reconcile the
actual source notes and previous session evidence before any new mutation. The
receipt is not a distributed lock or an exactly-once guarantee across machines.

A definite POST rejection (HTTP 4xx except 408/429) is different: the helper records
`rejected`, the status and attempt history in the same receipt. After resolving the
cause within existing authority, re-enter with the same files and receipt. It repeats
authentication, note selection and parent checks, then permits at most one additional
POST (two attempts total). An exclusive retained `.attempt-2` reservation prevents
two local retry callers posting together. Rejections remain in the final receipt;
never delete a receipt/reservation, reset its counters, switch credentials or trim
state to obtain a retry. Timeouts, 408/429, 5xx, malformed responses and interrupted
reservations remain uncertain and cannot take this path. Permanent rejection or an
exhausted transport allowance is a precise stop, not permission to widen access.

`.gitlab/ctx/checkpoint-exclusions.json` contains only these known-invalid notes on
Showcase **#11 / E11 / execute-e11-1**, written by **43132375**:

- 4019842621, 4019862442, 4019930708, 4020048348
- 4020406044, 4020434941, 4020464828

The selector reports exclusions and their evidence link, but never deletes notes
or removes them from the fetched evidence. It still checks all remaining compatible
history. A wrong writer/source/epic/run, missing original valid run or any unknown
malformed/new checkpoint fails closed. There is no arbitrary `--ignore` option.
Adding another exception requires a reviewed workflow change, not a note-body claim.

For E11, the stop report names valid checkpoint **4019881978** and verification
report **4019905198**. After re-reading current truth, reconcile the existing verify
claim and adopt the verified result using the normal journal transition before
claiming review. Do not count invented review claims in excluded notes as dispatched
workers, but reconcile their actual session reservations independently. Preserve
consumed design repairs, all action/delegation history and the actual per-session
counter; exclusion never means a budget refund. No automatic E11 execution is part
of this workflow repair.

## Rollout and acceptance

Run the workflow validator and tests, obtain independent review, and merge the
workflow change separately from application MRs. Compare trusted helpers/policy
with the actual epic runner checkout; synchronize only reviewed workflow paths
if required, preserving app changes and design/manifest content. In particular,
deploy `scripts/ctx_checkpoint.py`, `scripts/ctx_owner.py`, `scripts/ctx_workflow.py`
and `.gitlab/ctx/checkpoint-exclusions.json` together; the new owner selector imports
the shared policy validator. Keep their existing dependencies compatible and include
the updated guides/skills. Publish/read back
the Project prompt and Development YAML to their existing catalog entries, with
the same tools, visibility, service account, triggers and delegation limits.

Then use an explicitly authorized live continuation/test to demonstrate one real
file-based publication plus exact GET/readback and no duplicate POST on re-entry.
Verify E11 recovery selects current valid state with exactly the seven exclusions,
and the next eligible worker is dispatched only after verified persistence. Record
session, note and source SHA evidence. Fake-API/unit tests and catalog readback are
not live acceptance. Do not restart an unchanged failing version or call a local
candidate published.

Local verification on 2026-10-15: workflow contract validator passed; all 202 workflow
tests passed, including 12 checkpoint tests with a file-based CLI round trip, >54 KB
payloads, altered/truncated readback, uncertain POST reconciliation, stale parents,
credential/endpoint restrictions, pagination, the seven exact exclusions and a
bounded definite-rejection retry (with a behavioral red baseline before the fix).
No live publication or application continuation was performed by these tests.
