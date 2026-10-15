# Native Project discovery

CTX Project v1.8.0 is an **unpublished recovery candidate**; v1.7.0 remains published.
The ordinary Continue path regressed after the limited v1.7.0 smoke below. Do not
report the new recovery behavior as live-verified. Keep the existing **24 tools**, private visibility
and no external MCP. No continuation is authorized by this repair or its smoke test.
E11 scope, history, budgets, credentials and merge/deployment restrictions remain
unchanged. Do not write checkpoints or issue notes to test discovery.

## v1.7.0 publication receipt and limited fresh-chat acceptance

Source [!52](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/52)
merged at `eca186413bfd25f87f5aea7baa92bc6b71d888d4`. Independent review
session 9546670 / note 4022174114 found one tool-count typo, corrected in
`b30114cb31e5baa0fc8272c6fb7fcedcf88c57c3`; its thread is resolved.
Pipeline 2951847496 passed design validation, workflow validation and workflow
tests. The application verify job failed because its command is not configured;
the user explicitly approved this workflow-only merge without altering CI controls.

The existing [Project item 1016538](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/automate/agents/1016538)
shows v1.7.0, enabled/private, the exact unchanged 24-tool set, unchanged description
and no MCP. Full saved prompt (32928 bytes) matches reviewed source after final-newline
normalization: SHA-256 `cb55d49826871686118dc4f5a5fc10507045f7a0b8d2062dcfcdf4395abb4fcb`.

A fresh CTX Project chat then performed the read-only acceptance against main
`eca18641`. The operator inspected the displayed tool calls and final response:

- Project identity/default branch and merged guide/registration were read. A typo
  in the test request named `.gitlab/duo/catalog.json`; the agent recovered from its
  404 by reading the guide's canonical `.gitlab/ctx/catalog.json` itself.
- Flow call: project_id=87329027, item_type=flow, first=100. Seven entries and
  hasNextPage=false; exactly one matching consumer 12316920, non-foundational,
  can_start_session=true. Catalog ID/version remain absent from that response.
- Session call: project_id=87329027, first=100; neither status filter supplied.
  The chat reported 67 entries, hasNextPage=false, endCursor=Njc, with 52 finished,
  14 failed and one stopped. The browser's tool-response display/copy truncates
  this 23221-character response at 4096 characters, so these totals and final
  pageInfo are transcript-reported, not independently parsed from the UI. Earlier
  read-only diagnostics traversed four default-sized pages (20+20+20+7).
- Get Duo Session workflow_id=9546670 succeeded; its response was historical review
  text, without status/flow fields. The chat correctly used the listing for terminal
  status and did not mistake historical comment receipts for new writes.
- Binding/catalog release-time version was 1.10.0; runtime_version=not_exposed.
  The chat retained current-user/Duo-Chat visibility limits and explicitly did not
  declare E11 execution-ready. It identified the prepublication receipt metadata
  as stale rather than inventing live publication evidence; this receipt closes
  that bookkeeping gap using the independent catalog UI readback above.

**Tool discovery repaired** is limited to that discovery-only acceptance. No Start
or Input call, issue/note/checkpoint write or E11 continuation occurred. Full
launch/input/re-entry, checkpoint recovery and product acceptance remain pending;
refresh eligibility and reconcile ownership before separately authorized execution.

### Subsequent ordinary-Continue regression (2026-10-15)

The inspected chat "Continue E11 within the existing approved scope. Keep merge
and deployment off." submitted the same session-list arguments three times:
project_id=87329027, first=20, status_group=active, statuses=[], after="", url="".
Each returned ToolException; the UI did not expose a more specific server reason.
No attempt omitted both filters. The agent then called this a tool-interface
blocker and asked the user for a maintainer. This trace proves invalid-request
repetition, not that the server rejects a canonical unfiltered request. Whether
the model or wrapper supplied the extra values is not established by the UI trace.
Do not overwrite the earlier successful smoke or label it end-to-end acceptance.

## What the installed tools actually provide

Verified on 2026-10-15 in a read-only CTX Project chat for project 87329027:

- List Duo Sessions accepted only project_id: every parameter is optional, with
  status_group and statuses mutually exclusive. The first page had 20 records and
  hasNextPage=true; that diagnostic alone was NOT complete session discovery.
- List Duo Agents And Flows, with project_id and item_type=flow, returned seven
  entries on one complete page. CTX Development was the sole custom flow:
  name=CTX Development, type=flow, foundational=false, can_start_session=true,
  ai_catalog_item_consumer_id=12316920, workflow_definition=null. Its description
  was truncated. No catalog item ID, URL or version was exposed.
- The project's CTX Development detail page identified item 1016234, v1.10.0,
  enabled/private, managed by Showcase, with the existing development service
  account. This is release-time UI evidence, not a runtime tool response.
- GitLab GraphQL was absent from the actual agent Tools picker. The abandoned
  candidate's two query assets are removed; their earlier commits remain in Git.
  GLQL is not a GraphQL substitute. No additional tools or credentials are needed.

GitLab owns the tool schemas. A CTX registration cannot repair them. Do not carry
forward an old schema error without inspecting the actual request and current
schema. Apply the following bounded correction before declaring a platform blocker.

## Session discovery request and recovery

For ordinary Begin/Continue/check progress and status requests, the first native
List Duo Sessions request is exactly:

```json
{"project_id":"87329027","first":100}
```

Omit status_group, statuses, url and after as keys, not just values. Empty strings,
empty arrays and null are NOT omission. Do not filter to active: stopped/finished
and approval-paused records matter too. A wrapper may add its required display-only
project_name="Showcase". On later pages, add only after, copied verbatim from the
last successful pageInfo.endCursor, with the same project/page size.

At most one corrected read-only attempt per user turn:

1. Inspect the actual failed request, not just the final diagnosis. If it contained
   either status filter or empty optional fields, rebuild from the canonical
   request; remove BOTH filters, including an empty array. Never repeat the rejected
   payload. If already paginating valid unfiltered results, retain the last valid
   after; do not reset the cursor or re-fetch completed pages. Discard results from
   filtered enumeration; they cannot establish complete unfiltered discovery.
2. No new permission or maintainer lookup is needed to correct your own read-only
   arguments. Rejecting a malformed request is not proof of a contradictory schema.
   ToolException alone does not identify which layer added invalid fields. If the
   current wrapper demonstrably prevents omission, record that exact constraint;
   do not invent dummy values or claim a corrected request was executed.
3. If correction succeeds, finish pagination and continue the same authorized
   preflight in this turn. Do not stop merely to announce recovery or ask for
   Continue again. Discovery success is not dispatch clearance: all ownership,
   authority, budget and approval checks still apply. Status/testing stays read-only.
4. If a canonical request fails, access denial occurs, or the correction is
   exhausted, stop discovery with its actual request/error and continue useful
   known-ID reads. Never turn incomplete discovery into empty/safe ownership.
   Do not change credentials, transports, schema or permissions to force success.

Do not retry Start Duo Session or Send Duo Session Input under this rule. An
uncertain mutation remains dispatch_unknown; reconcile it without an alternate
transport or duplicate start. No request note, checkpoint change, start or input
is part of a discovery correction or acceptance test. E11 scope/history/budgets
and merge/deployment controls remain unchanged.

## Exact target without invented runtime fields

Read this guide, .gitlab/duo/agents/ctx-project.json and .gitlab/ctx/catalog.json at
the observed trusted default-branch SHA. The reviewed development_consumer_binding
records project 87329027, catalog item 1016234 and consumer 12316920. The project path
must be gitlab-ai-hackathon/transcend-october-2026/43066631/showcase.

1. Verify project identity with Get Project. Discover flows for this project using
   item_type=flow and complete pagination before selection.
2. Require exactly one live entry with consumer ID 12316920, name CTX Development,
   type=flow, foundational=false and can_start_session=true. A name alone is not
   identity; a different consumer requires a separately reviewed binding update,
   not an inferred replacement. Duplicate/conflicting entries block selection.
3. Check the binding's item ID/URL against the Development catalog record. Require
   its recorded release to match catalog_version_at_verification (currently 1.10.0).
   A pending/candidate version is not the published record. If publication changes,
   reverify the project flow in the UI and update the binding through review.
4. When a tool exposes catalog/version/project fields, compare them and stop on
   conflicts. When it omits optional catalog/version fields, do not fabricate them
   or classify successful discovery as a schema failure. Record runtime_version
   as not_exposed and release-time version separately, with the binding source SHA.
5. Use ONLY the matching live ai_catalog_item_consumer_id in Start Duo Session.
   GitLab resolves the existing configured consumer's release and enforces runtime
   authorization. Do not change its pin, choose latest via flow_item_id, substitute
   foundational Developer, omit the selector, start Delivery or use a bot mention
   after an uncertain start.

This explicitly replaces an unsatisfiable per-launch exact-version introspection
requirement with a reviewed deployment binding plus live native eligibility.
It does NOT claim cryptographic/runtime version attestation: out-of-band pin changes
that the native tool does not expose cannot be detected by this chat. Publication
owners must keep the binding aligned. If a particular request requires exact live
version proof, stop for an operator UI check instead of claiming that proof.
Never override can_start_session=false, missing/null eligibility, access denial,
stale binding or contradictory identity/version evidence. Refresh eligibility and
known session states immediately before a separately authorized mutation; a cached
smoke is not launch clearance.

## Complete discovery and ownership

For both lists follow hasNextPage to false, including empty intermediate pages.
A repeated cursor, missing cursor while hasNextPage=true, missing/null pageInfo,
partial data, tool errors, truncation of identity/status, or execution/context limits
mean incomplete discovery, not an empty result. Preserve the next cursor for a
read-only continuation; never use an incomplete page as dispatch clearance.

List Duo Sessions is current-user scoped and excludes Duo Chat. Empty results are
not proof of exclusive ownership or visibility of every user's work. Match recorded
workflow IDs/request keys, full goals, source/epic/branch and receipts, not newest
timestamp. Code Review sessions are not Development workers. Use Get Duo Session
for recorded in-flight/uncertain sessions and candidate matches, including other-user
records where accessible. Read actual state, input, results, artifacts and polling
hints. Reconcile source notes, reservations, branch movement and original authority.
Unknown status, inaccessible recorded work or conflicting ownership blocks dispatch.

If listing breaks, known-ID reads can still provide status; they do not prove there
are no other workers. Keep useful read-only assessment going. Do not initialize a
new run, reset counters, alter a checkpoint, delete old notes or weaken review gates
to repair discovery. An uncertain start remains dispatch_unknown; never retry through
another transport. Existing one-mutation-per-turn and explicit approval rules remain.

## Concrete platform-blocker handoff

Use this only after the canonical request fails or omission is demonstrably
prevented, not after a malformed request that can still be corrected. Distinguish
caller-argument recovery from an actual GitLab-owned schema/access boundary.
Never ask the user for a maintenance issue/contact just to fix your own arguments.

Do not ask the user to diagnose raw tool errors or repair application code. State
the exact unavailable capability and the completed read-only checks. Give one
immediate instruction: open the linked Showcase AI > Sessions page and verify the
specific recorded session/status that cannot be read, or ask the workflow publisher
to reverify the exact Development binding. Include the exact URL and needed value.
Do not offer an execution command while ownership/dispatch is unknown. Once fixed,
the user can say Check progress; retain the original objective and budgets.

## Publication and read-only acceptance

Local validation checks registration/binding/prompt regressions, not runtime policy
enforcement. Review and workflow CI -> merge source -> publish existing CTX Project
item 1016538 -> read back full prompt, version, 24 tools, private visibility, no MCP,
enablement -> fresh discovery-only chat. Publication is not live acceptance.

The fresh chat must read the merged guide/binding, verify the project, paginate both
native lists completely, and use Get Duo Session to inspect a returned terminal
session. Report exact live consumer, can_start_session, release-time evidence and
runtime_version=not_exposed. Retain the other-user visibility limitation; do not
claim E11 is execution-ready from discovery alone. No continuation, Start Duo
Session, Send Duo Session Input, issue/note/checkpoint writes or application run.

For the v1.8.0 candidate, also test ordinary continuation intent without coaching
the tool arguments. In a fresh published-agent chat, submit:

> Continue E11 within the existing approved scope. Keep merge and deployment off.
> For this acceptance test, perform read-only preflight only; stop before all
> writes, Start Duo Session and Send Duo Session Input.

Inspect actual requests/results, not only the final answer. Require filter-free
pagination and ownership reconciliation without asking the user for a maintainer
on a correctable input error. This tests continuation preflight, not live dispatch.
Record the actual model and agent version; a specially coached smoke alone is
insufficient. A successful direct call does not prove error recovery either.

Replay these cases in a non-mutating evaluation harness with controlled tool
responses when available; synthetic responses are not live GitLab evidence:

| Case | Required behavior |
| --- | --- |
| Observed malformed request / ToolException | Exactly one rebuilt filter-free read; no repeated invalid payload, new permission request or maintainer lookup. |
| Corrected call succeeds with another page | Preserve successful-page cursor, finish pagination, continue read-only preflight; no repair-only final answer. |
| Canonical call fails or wrapper requires conflicting fields | Stop discovery, retain exact evidence, no dummy/null arguments or inferred ownership. |
| Access denial, repeated/missing cursor, incomplete data, or uncertain Start/Input | No correction-based dispatch, credential fallback, duplicate mutation or budget/checkpoint change. |

Local tests validate the published request example and recovery instructions only.
If no controlled native-tool test harness is available, mark failure-injection
acceptance pending; do not start E11 or deliberately issue invalid production calls
to manufacture a passing recovery transcript.

Only after that acceptance passes say **Tool discovery repaired**. If it fails,
name the remaining concrete boundary and provide one **Do this now** instruction;
do not report publication or unit tests as live integration proof.

Official native contracts:
[GitLab MCP tools](https://docs.gitlab.com/user/model_context_protocol/mcp_server_tools/).
The live diagnostic above is the instance-specific evidence; the documentation is
not a guarantee that every deployment exposes the same fields.
