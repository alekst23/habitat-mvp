# Native Project discovery

Published CTX Project v1.7.0 on 2026-10-15 UTC. Keep the existing **24 tools**, private visibility
and no external MCP. No continuation is authorized by this repair or its smoke test.
E11 scope, history, budgets, credentials and merge/deployment restrictions remain
unchanged. Do not write checkpoints or issue notes to test discovery.

## Publication receipt and fresh-chat acceptance

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
forward an old schema error without inspecting the current schema. Omit BOTH
status filters by default. If the contradiction reappears, do not invent nulls,
empty arrays or dummy values or repeatedly call an invalid combination.

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

Only after that acceptance passes say **Tool discovery repaired**. If it fails,
name the remaining concrete boundary and provide one **Do this now** instruction;
do not report publication or unit tests as live integration proof.

Official native contracts:
[GitLab MCP tools](https://docs.gitlab.com/user/model_context_protocol/mcp_server_tools/).
The live diagnostic above is the instance-specific evidence; the documentation is
not a guarantee that every deployment exposes the same fields.
