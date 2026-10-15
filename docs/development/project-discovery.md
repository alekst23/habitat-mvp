# Native Project discovery

CTX Project v1.8.0 is **published and enabled** (2026-10-15 UTC).
Ordinary-Continue read-only discovery succeeded without the old conflicting filters;
subsequent ordinary continuation failed again. **Discovery compatibility is
model-dependent; do not describe v1.8.0 as a universal schema repair.** See the
verified Claude workaround and upstream GPT defect below. Bounded error recovery
and complete unprompted preflight are not yet live-proven.
Keep the existing **24 tools**, private visibility
and no external MCP. No continuation is authorized by this repair or its smoke test.
E11 scope, history, budgets, credentials and merge/deployment restrictions remain
unchanged. Do not write checkpoints or issue notes to test discovery.

## Model compatibility and the immediate workaround

These observations came from **three distinct chats**, distinguished in GitLab
Chat History and inspected separately:

- The earlier v1.8.0 acceptance chat began **Continue E11 within the existing
  approved scope. Keep merge and deployment off. For this acceptance test, perform
  read-only preflight only; stop before all writes, Start Duo Session and Send Duo
  Session Input.** Claude was visibly selected for that test. Its later diagnostic
  follow-up fetched the missing known notes; it is **not** the failing follow-up.
- The user's later chat began **Continue E11 within the approved scope. Complete
  the remaining preflight checks yourself, then resume development. Keep all merges
  and deployment off.** Its second user turn was **Retry corrected read-only session
  discovery and complete E11 preflight here.** This is the failing follow-up below.
  Its original model and any intervening model changes could not be established.
- The new bounded compatibility chat began **Read-only tool compatibility diagnostic
  only, not E11 continuation or ownership clearance.** This is the GPT-to-Claude
  comparison below; both model selections were directly observed by the operator.

On 2026-10-15 UTC, the second chat's failing follow-up again submitted
project_id=87329027, first=100, status_group=active, statuses=[], after="", url=""
twice. Both returned generic ToolException. No canonical request executed. The
historical chat's selected model could not be independently established; the model
selector displayed when reopening history is not proof of its past configuration.
Keep this regression alongside the successful Claude observations, not in place
of them. E11 preflight is still incomplete.

GitLab has a matching upstream defect:

- [AI Gateway #2766](https://gitlab.com/gitlab-org/modelops/applied-ml/code-suggestions/ai-assist/-/work_items/2766)
  and [GitLab #621520](https://gitlab.com/gitlab-org/gitlab/-/work_items/621520)
  track GPT tool calls populated with unwanted optional arguments.
- [AI Gateway !7436](https://gitlab.com/gitlab-org/modelops/applied-ml/code-suggestions/ai-assist/-/merge_requests/7436)
  was **merged**, verified in the authenticated UI. It explicitly binds OpenAI
  tools with `strict: false` behind `dap_openai_non_strict_tools`: without that
  setting, Responses can make optional fields required. Prompt instructions cannot
  make an impossible tool schema satisfiable.
- The companion [GitLab !261800](https://gitlab.com/gitlab-org/gitlab/-/merge_requests/261800),
  which defines the rollout flag, was still **open** when checked. A merged gateway
  patch is not evidence that the fix is enabled for this project/account. CTX
  cannot set GitLab.com feature flags or repair this adapter through registration.

A bounded comparison used the existing Project v1.8.0, unchanged tools and one
diagnostic chat. With **GPT-6.1 Sol - OpenAI** selected, the agent reported that all
six session-tool fields were required and made **zero tool calls**, honoring the
instruction not to invent filler values. That is a model-reported schema, not an
export of the effective server/provider schema. After the operator selected
**Claude Sonnet 5.5 - Default** in the same chat, the same read-only request executed
successfully. The expanded tool trace confirmed exactly project_id="87329027",
first=100 and the wrapper's project_name="Showcase", with no status_group, statuses,
url or after. The response contained session records, not an error. The UI truncated
the 23920-character response at 4096 characters; final pageInfo/counts are not
independently verified by this observation. Neither this test nor the upstream
issue proves which model the user's historical failed chat used.

Only one read call occurred across this comparison. No other tools, pagination,
Start/Input, issue/checkpoint writes or application work. This verifies a
**model-specific discovery workaround that passed a bounded test**, not a guarantee
of reliable model behavior or complete ownership, preflight,
dispatch or end-to-end automation. The diagnostic chat was left on Claude.

### Agent response for this failure

Keep the bounded correction below for ordinary malformed calls. When the current
exposed schema cannot omit optional fields, do not repeat the same incompatible
call, invent filler values, or tell the user that another Continue will fix it.
Use the verified compatibility path before asking for a support destination:

1. Distinguish the native optional schema from a provider-transformed schema. A
   generic error alone does not establish the cause. If the selected model is not
   verifiable, ask one exact question: **Which model is shown below the CTX Project
   chat input?** Do not blame GPT from a historical error message alone.
2. For a GPT chat exhibiting this required-optional-field conflict, give this
   immediate instruction: **Below the CTX Project chat input, select Claude Sonnet
   5.5 - Default, then send `Check progress on E11; read-only preflight only.`**
   Use the actual current epic if different. If the historical chat is unavailable,
   use **Add new chat -> CTX Project**, then select that model and send the same
   request. Opening a chat does not create a new execution objective.
3. The next turn re-inspects the current schema and performs fresh, complete
   filter-free discovery plus existing ownership/authority/checkpoint checks.
   Model selection changes tool compatibility, not permissions, budgets or scope.
   Do not auto-start from this read-only compatibility test. Retain the existing
   objective and original approvals; resume only under a subsequent action request
   after all normal gates pass. An uncertain prior Start/Input still requires
   reconciliation; switching models never justifies a duplicate mutation.
4. If Claude is unavailable or fails with a canonical request too, report that
   exact limitation and link the upstream issue above. Do not request credentials,
   add tools/transports, bypass access denial, or ask the user to locate a maintainer.
   Do not post to upstream support without the user's authorization. Known-ID
   reads can still provide useful status, but cannot establish exclusive ownership.

This is shared guide/acceptance guidance consumed by the already-published agent;
the catalog prompt, version, tool set and permissions are unchanged. To retire the
workaround, verify the fixed native path with the exact selected GPT model, not
only Claude or a source-code merge. Record live requests and results. The wider
preflight and launch acceptance below remains required separately.

## v1.8.0 publication receipt and ordinary-Continue observation

Source [!54](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/54)
at `e72534c164b2fbd17006148bb893d7b26e4f6291` merged into main at
`33c6545ec83c5be146ee8fb87b15f573a9e7b990`. Independent Duo review
[9557511](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/automate/agent-sessions/9557511)
/ [note 4023256430](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/54#note_4023256430)
had no actionable findings. Pipeline 2952317439 passed workflow validation
(17212067232), all 205 workflow tests (17212067233), and design validation
(17212067234). Application verify 17212067235 failed with the known unconfigured
command (exit 2). The user's workflow-only merge exception applied; no CI control
was changed and this is not an application-verification pass.

The existing Project catalog item 1016538 shows v1.8.0, enabled/private, the exact
unchanged 24 tools, unchanged description and no MCP. The full saved prompt was
read back from the editor: 35029 bytes, equal to reviewed source after removing
its final newline, SHA-256
`a2e33eb774a6ea74abb90175190a0c792b0213e5580ca3ff93d2fc09669a8b5a`.
The source file's raw SHA-256 remains
`e523623c2539ddc804810933bafd6541e576a3881bb54c8b1dd76296e4b4cdf4`.

A fresh CTX Project chat using **Claude Sonnet 5.5 - Default** received the ordinary
Continue prompt from the acceptance section below, with the read-only cap and no
coaching about filters. Actual expanded UI requests/results showed:

- Two successful session calls for project 87329027, both without status_group,
  statuses or url: first=50 on the initial page; first=100, after=NTA on the second.
  The wrapper supplied display-only project_name=Showcase. This is successful
  filter-free discovery, but **not exact compliance with the prescribed first=100
  and constant page-size instructions**. No malformed request or recovery retry
  occurred, so this does not prove the correction branch.
- The chat reported 50+19 records, final hasNextPage=false, all terminal. The UI
  truncates each long tool-response display at 4096 characters; the count and final
  pageInfo remain transcript-reported rather than independently parsed from the UI.
- The project-filtered flow list returned seven entries and hasNextPage=false.
  Exactly one CTX Development matched consumer 12316920, foundational=false and
  can_start_session=true. Release-time binding remains 1.10.0; runtime version
  is not exposed. Get Duo Session 9530877 returned its historical blocked report.
- All 16 calls were read-only. The agent inspected the plan, branches, open MRs,
  source notes and binding. It preserved the other-user/Duo-Chat visibility limit,
  retained the original run/budgets, and did not send the user to find a maintainer.
  It read HEAD before observing main at 33c6545e, rather than pinning every read up
  front; this is not a fully revision-pinned preflight proof.
- The note list was explicitly truncated. The first answer disclosed that it had
  not reread checkpoint 4019881978 or original authorization notes 4008773456,
  4015038188 and 4015631853, despite leading with "preflight ... complete". Treat
  that completion wording as an overstatement: discovery worked, but full
  unprompted authority/checkpoint reconciliation is **not accepted**. A separately
  prompted read-only follow-up is diagnostic evidence, not first-turn acceptance.
- Repository publication metadata still described the unpublished candidate during
  this test; the agent correctly did not claim a catalog version from that stale
  record. This receipt updates it using the independent UI readback above.

No Start/Input, issue/note/checkpoint write or application run occurred. Application
MRs !45/!48 and their heads were unchanged. Current-user discovery alone is not
ownership clearance. Failure-injection recovery, fully automatic preflight, and
launch/input/re-entry acceptance remain pending; do not promote this observation
to end-to-end automation proof.

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
For the required-optional-field conflict, use the model compatibility procedure
above first; it supplies a concrete next step and an already-verified upstream
destination rather than an open-ended support lookup.

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

For v1.8.0, also test ordinary continuation intent without coaching
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
