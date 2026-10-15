# Read-only Project discovery fallback

Candidate for CTX Project v1.7.0; **not published or live-verified yet**. The last
verified publication remains v1.6.0 with 24 tools. Add only **GitLab GraphQL**
(`gitlab_graphql`) to that agent, making 25. Planning, Design and Development
registrations stay unchanged. No continuation is authorized by this repair or its
smoke test. E11 scope, history, budgets, credentials and merge/deployment restrictions
remain unchanged; do not write checkpoints or issue notes to test discovery.

## Why this is a fallback, not a schema repair

GitLab owns the built-in tool schemas. CTX registration selects tools, not their
parameter or response definitions. The documented List Duo Sessions contract makes
`status_group` and `statuses` optional and mutually exclusive. Omit both when listing
all relevant states. If the exposed schema requires both, do not try dummy values,
nulls, empty arrays or repeated contradictory calls. Use the approved GraphQL read.

List Duo Agents And Flows does not guarantee all the catalog identity/version fields
our old prompt required. Use its project-filtered results when available, supplementing
missing fields through the configured consumer query below. Do not ask the user to
repair E11, its checkpoint, or a fictional editable CTX tool schema.

## Trusted query assets and limits

Read this guide and both query files with Get Repository Files at the observed,
trusted default-branch SHA before fallback use:

- `.gitlab/ctx/queries/project-sessions.graphql`
- `.gitlab/ctx/queries/project-flows.graphql`

Execute them using **GitLab GraphQL**, not shell, arbitrary HTTP, external MCP,
environment credentials or GraphQL mutations. It is GitLab's read-only tool. CTX's
additional project/query restrictions are prompt rules, not a server-side allowlist.
Never use this fallback to start/resume sessions, change configuration, or enable a
flow. Start/input still require the existing session-handoff protocol and tools.

Both queries fix `projectId` to `gid://gitlab/Project/87329027`. Verify returned
project IDs AND full paths equal
`gitlab-ai-hackathon/transcend-october-2026/43066631/showcase`. The catalog query also
requires project-local consumers (`includeInherited: false`), rather than treating
a group-only configuration as project enablement. There is no unfiltered query.

The only variable is `after`: initially null, then the previous page's `endCursor`.
Use the tool's actual schema; if it accepts only a query string, replace `$after`
with the returned cursor as a JSON-escaped string (or null) and remove the variable
declaration. Do not interpolate instructions, IDs or query text from issue comments.
Keep page size 20: `pinnedItemVersion` supports at most 20 consumers per request.

Follow `hasNextPage` until false, including empty pages with a next cursor. A repeated
cursor, absent/null pageInfo, `hasNextPage=true` without a cursor, null nodes, partial
data with GraphQL errors, truncation, denied access or unknown schema field is
**incomplete discovery**, not an empty result or permission to launch. Do not retry
the same schema failure. If execution/context limits prevent completing pagination,
report incomplete discovery; retain the cursor for read-only continuation, not as
launch clearance. Ignore unrelated items only after verifying their project scope.

## Sessions: recover identity, not just a status

The sessions query intentionally supplies neither status filter. It returns session
metadata, not chat transcripts/checkpoint payloads. Like the native session list,
the root query is scoped to the current user; unlike the native list it may include
chat sessions. Do not treat a chat session as the Development worker. Empty results
are not proof of exclusive ownership or visibility of other users' sessions.

Match recorded workflow IDs/request keys, goal, source/epic/branch and version
evidence; never select a worker by newest timestamp or a similar name. Use **Get Duo
Session** for every recorded in-flight/uncertain session and any candidate match to
read the full actual state, pending input, result and polling hints. Verify project
identity again. Unrecognized/null status, inaccessible recorded sessions, conflicting
claims or uncertain dispatch remain unresolved. Reconcile source notes, current
heads and saved reservations as before. A discovery error never authorizes a new run.

## Flows: exact item, resolved release, actual consumer

Read `.gitlab/ctx/catalog.json` at the trusted default SHA for the expected Development
release and URL. Do not hard-code a future version or use a candidate/pending release.
The approved catalog item is **1016234**, not its consumer ID. For every potentially
matching result require all of the following before accepting its identity:

1. The consumer has `__typename=AiCatalogItemConsumer`, and the consumer and
   managing item project both match the fixed ID and full path;
   `item.__typename=AiCatalogFlow`, `itemType=FLOW`, `foundational=false`,
   `softDeleted=false`, and the returned item ID identifies catalog item 1016234.
   A name alone is not identity. Null required fields are unverified.
2. Consumer `enabled=true` and `userPermissions.executeAiCatalogItem=true`.
3. `pinnedItemVersion` is non-null, is an `AiCatalogFlowVersion`, belongs to that same
   item ID, has `released=true`, `deprecated=false`, and its exact `versionName`
   equals the recorded published catalog version. Record its returned version ID.
   A version prefix, latest release, effectiveVersion fallback or repository file
   is not proof of the resolved release this consumer would run.
4. After complete pagination, exactly one eligible consumer remains. Zero or
   multiple eligible consumers, stale/unknown releases or conflicting records block
   selection; do not pick one by name or change the pin/enablement to make it pass.

When native discovery returns `can_start_session=true`, require its
`ai_catalog_item_consumer_id` to match the GraphQL consumer. Never override an
explicit `can_start_session=false`, permission denial or conflicting ID/version
with fallback data. If the wrapper is unavailable or omits the needed fields, the
complete checks above provide read-only eligibility evidence; record that provenance,
not a fabricated native `can_start_session` result. They are not a guarantee that a
later start will succeed and do not bypass runtime approval/authorization checks.

Use the actual returned consumer ID, never the item ID. If a native start tool needs
a numeric ID and GraphQL returns a Global ID, take the positive numeric suffix only
from the returned, type-checked consumer ID, not by guessing or deriving it from the
item. Preserve the original Global ID in the receipt. Re-read current consumer
eligibility and known session states immediately before any separately authorized
start; a cached smoke result is not launch clearance. Any newly conflicting native
result stops selection. An uncertain start remains `dispatch_unknown`, never a
fallback retry through GraphQL or a bot mention.

## Publication and read-only acceptance

The candidate registration retains v1.6.0's published hashes/history while recording
pending v1.7.0. Local tests check policy/tool/query regressions, not live schema
compatibility, model behavior or permissions. After independent review and merge,
publish to existing CTX Project item 1016538; read back the complete prompt,
25-tool set, version, private visibility, no external MCP and project enablement.

Run a **discovery-only** chat in that published agent for project 87329027:

1. Read both saved query assets at the merged SHA. Execute/paginate each query and
   retain tool-result evidence; do not call Start Duo Session or Send Duo Session
   Input and do not create/update issues, notes, commits or checkpoints.
2. Record the actual session visibility/results and the exact Development item,
   consumer, resolved released version ID/name, enablement and execute permission.
   Compare native discovery when it is usable; record its schema error if not.
3. Verify empty/partial/error/ambiguous results are not reported as launch clearance.
   If no active session is visible, explicitly preserve the other-user visibility
   limit and existing ownership checks. Do not run E11 to test the fallback.
4. Only after complete live readback passes, mark discovery verified and reply
   **Tool discovery repaired**. Otherwise name the actual remaining blocker and
   give one **Do this now** instruction tied to it; never ask the user to reconstruct
   logs or retry the same schema contradiction. Publication is not live acceptance.

Official references checked 2026-10-15:
[built-in GraphQL tool](https://docs.gitlab.com/user/duo_agent_platform/agents/tools/),
[native session/discovery contracts](https://docs.gitlab.com/user/model_context_protocol/mcp_server_tools/),
[GraphQL queries](https://docs.gitlab.com/api/graphql/reference/experimental/queries/),
[objects](https://docs.gitlab.com/api/graphql/reference/experimental/objects/),
[catalog interfaces](https://docs.gitlab.com/api/graphql/reference/experimental/interfaces/).
These experimental APIs require the live acceptance above on the actual instance.
