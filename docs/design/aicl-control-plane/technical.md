# AICL control plane technical design

Scope: E11-1 (domain and control foundation) and the canonical creation service and first-party web-app tools owned by E11-2. Connection, network and dispatch contracts are in [connection-network-policy/technical.md](../connection-network-policy/technical.md); UI, sign-in and chat contracts are in [aicl-experience/technical.md](../aicl-experience/technical.md). Stack, layout, the consolidated configuration table and test layers are in [architecture.md](../architecture.md). Proposed source locations are under `backend/aicl/` and are labeled proposed until the code exists.

## Contracts

### Conventions

- Language Python 3.12; contracts are frozen dataclasses or pydantic v2 models with `extra="forbid"`; ports are `typing.Protocol` classes with a minimal fake each (stubs are prepared by the Development design worker, not by Design).
- Identifiers are lowercase UUID4 strings. Timestamps are timezone-aware UTC, serialized as ISO 8601 with `Z`. Time comes from a `Clock` port (`now() -> datetime`) so tests can control it.
- Money is an integer count of micro-USD (1 USD = 1,000,000). Floats and decimals never cross a contract boundary. Rounding of a computed cost is always up (ceiling).
- Every mutation takes the authenticated `AuthContext` as its first argument. No contract accepts a tenant or owner identifier from a client payload.

### Error taxonomy (shared by every operation and HTTP route)

Errors are a structured object `{error, message, ...}`; `message` is safe to show and never contains secrets, tokens or another tenant's data.

| error | HTTP | Extra fields | Meaning |
|---|---|---|---|
| `unauthenticated` | 401 | none | No valid session or `AuthContext` expired |
| `not_found` | 404 | none | The object does not exist OR belongs to another tenant (indistinguishable) |
| `validation_failed` | 422 | `field_errors: [{field, code}]` | Malformed or out-of-bounds input, unknown template, capability or argument |
| `conflict` | 409 | `current_version` or `existing_result_id` | Stale `expected_version`, or the same idempotency key with a different payload |
| `invalid_transition` | 409 | `from`, `action` | Lifecycle action not in the transition table |
| `invalid_state` | 409 | `lifecycle` | Mutation not allowed in the current state (for example any mutation of an `archived` instance) |
| `denied` | 403 | `reason` | Dispatch gate or confirmation denial; `reason` is one of the gate reasons below |
| `unavailable` | 503 | none | A required dependency (database, lock, price table, secret store) could not be used; the request fails closed |

### AuthContext (owner E11-1)

`AuthContext {owner_id, tenant_id, session_id, expires_at}` is a frozen dataclass created only by an `AuthProvider` (Protocol: `resolve(request_headers_and_cookies) -> AuthContext | None`). E11-1 owns the dataclass, the Protocol and a `FixedAuthProvider` test double (returns configured contexts for fixture cookies); E11-3 owns the real `SessionAuthProvider` (see the experience document). Rules:

- MVP tenant rule: one tenant per owner and `tenant_id == owner_id` (both are the owner's UUID). The two fields stay separate in every model so teams can be added later without changing contracts. "Same owner" (connection sharing) means equal `owner_id`.
- An expired or missing context is `unauthenticated`. Services never read `tenant_id`, `owner_id` or `session_id` from request bodies, query strings, headers other than the session cookie, or tool arguments; such fields are rejected as `validation_failed` (`unknown_argument`) by schemas with `extra="forbid"`, and ignored on form posts.
- Every repository query is filtered by `auth.tenant_id`. A row of another tenant yields `not_found`, never `denied` or `forbidden`, and the audit log records an `access.denied` event with only the object kind.
- Browser-originated mutations additionally require a CSRF token bound to the session (see the experience document).

### Instance model (owner E11-1)

`AgentInstance {id, tenant_id, owner_id, template_id, name, instructions, lifecycle, gated_reason, version, limits, network_domains, created_at, updated_at}`:

- `lifecycle`: `draft | active | paused | archived`. `gated_reason`: `null` or one of `budget_exhausted`, `budget_unavailable`, `capability_disabled`, `connection_revoked`, `connection_reauthorization_required`, `network_denied`. `version` starts at 1 and increments by one on every committed change of the instance, its grants, limits, domains or attachments.
- `limits`: `{inference_daily_micro_usd, inference_monthly_micro_usd, compute_daily_micro_usd, compute_monthly_micro_usd}`, all integers in `[0, 1_000_000_000_000]`, default 0 (D11-5). Within a category monthly must be greater than or equal to daily.
- `network_domains`: tuple of owner-added exact hosts (sorted, at most 20), read through `NetworkPolicy` (E11-2).
- `CapabilityGrant {instance_id, capability, enabled}` for the catalog capabilities `inference`, `gmail.read`, `gmail.send`, `reddit.read`, `reddit.post`, `network.fetch`; all rows exist and default to `enabled=false`.
- Derived `status` for display and read models: the lifecycle when it is not `active`; `gated` when active and (`gated_reason` is set or an unreconciled hold exists, shown as `reconciliation_pending`); otherwise `active`. `gated_reason` is never set on a draft, paused or archived instance by a denial (the denial is `instance_not_active`); an existing reason is retained across pause and resume and shown only while `lifecycle=active`.

### Template catalog (owner E11-2, data in E11-1 constants)

The MVP catalog has one template: `default` (version 1), capabilities as above. Configuration constraints enforced by the canonical creation service: `name` is 1 to 80 characters after trimming and NFC normalization; `instructions` is 0 to 4,000 characters; control characters other than newline and tab are rejected; `enabled_capabilities` is a set of catalog capability ids (unknown id is `validation_failed`). Unknown `template_id` is `validation_failed`.

### CreateInstanceRequest and CreateInstanceResult (owner E11-2)

`CreateInstanceRequest {idempotency_key, template_id, name, instructions, enabled_capabilities}` with `idempotency_key` 16 to 64 characters of `[A-Za-z0-9_-]`. There is no tenant, owner, credential or confirmation field. `CreateInstanceResult {instance: InstanceView, created: bool, audit_event_id: int}` where `created=false` on an idempotent replay.

`create_instance(auth, request) -> CreateInstanceResult` is the one canonical creation function used by the wizard (E11-3), the web-app tool `create_instance` (E11-2, used by chat in E11-4) and any other first-party surface. In one database transaction it validates, then inserts the draft instance (version 1, all limits 0), one grant row per catalog capability (enabled per the request), and the `instance.created` audit event. Idempotency is scoped to `(tenant_id, idempotency_key)`: a replay with an identical request digest returns the stored result with `created=false`; a different digest is `conflict` with `existing_result_id`. Chat derives its key as `chat:<chat_session_id>:<turn>` and the wizard derives it from a per-form hidden value, so a double submit creates one instance. Creation never activates, never attaches connections and never grants authority beyond the explicit capability flags.

### Instance mutation operations (owner E11-2, `InstanceOperations`)

All operations: `(auth, instance_id, expected_version, ...) -> MutationResult {instance: InstanceView, changed: bool, audit_event_id: int | null}`; owned by the creation/operations service in E11-2 and invoked by UI form handlers (E11-3 for the wizard follow-up, E11-5 for management pages). A stale `expected_version` is `conflict` with `current_version` and no effect. A request that would not change state (same capability value, domain already present or absent) and carries the current version returns `changed=false`, no version bump and no audit event. Each committed change bumps `version` and appends one audit event in the same transaction. Mutating an `archived` instance is `invalid_state`.

| Operation | Extra request fields | Effect and rules |
|---|---|---|
| `set_lifecycle` | `action: activate \| pause \| resume \| archive` | Applies the transition table below; anything else is `invalid_transition` |
| `set_capability` | `capability`, `enabled` | Updates the grant. Enabling re-evaluates `gated_reason=capability_disabled` and clears it if that was the reason |
| `set_limits` | `limits` (the four fields) | Replaces the limits after validation. Lowering below current spend is allowed and takes effect at the next dispatch. Re-evaluates budget gate reasons per the gating rule |
| `add_network_domain` / `remove_network_domain` | `host` | Owner `network.fetch` domain edit; add validates with the SSRF host rules (connection document). Re-evaluates `network_denied` |
| `resolve_gate` | none | Owner acknowledgement, see gating rule |
| `attach_connection` / `detach_connection` | `capability`, `connection_id` | Defined in the connection document; same version and audit rules |

Lifecycle transition table (an unlisted pair is `invalid_transition`; `archived` is terminal):

| From | `activate` | `pause` | `resume` | `archive` |
|---|---|---|---|---|
| `draft` | `active` | no | no | `archived` |
| `active` | no | `paused` | no | `archived` |
| `paused` | no | no | `active` | `archived` |
| `archived` | no | no | no | no |

Activation has no preconditions other than ownership and `draft` state: a zero-budget active instance is valid and is gated at its first work request. `paused` is only ever set by the owner; the gate never pauses an instance.

Gating rule, following D11-8 literally: only the owner clears a gate. A daily or monthly window rollover never clears `gated_reason`. The owner clears it by (a) the committed mutation that fixes the control (a positive limit via `set_limits`, `set_capability` enabling, a new attachment, a domain addition), which re-evaluates the persisted reason and clears it when the control now permits work, or (b) `resolve_gate`, which for `budget_*` reasons clears only if the current windows have available budget (otherwise `denied` with reason `gate_unresolved`) and for `capability_disabled`, `connection_*` and `network_denied` records the owner's acknowledgement and clears the reason (the next dispatch gates again if the control still denies). `reconciliation_pending` is derived, not persisted, and disappears when the holds are reconciled. Persisted `gated_reason` stores only the machine reason, never a destination, payload or credential.

### Gate reasons (denial vocabulary, owner E11-2 for the gate; E11-1 for budget reasons)

`instance_not_active`, `capability_disabled`, `confirmation_required`, `confirmation_expired`, `confirmation_used`, `confirmation_mismatch`, `connection_unavailable`, `network_denied`, `budget_exhausted`, `budget_unavailable`, `price_unavailable`, `estimate_missing`, `reconciliation_pending`, `gate_unresolved`, `check_unavailable`. Those that set `gated_reason`: `capability_disabled`, `connection_unavailable` (as `connection_revoked` or `connection_reauthorization_required`), `network_denied`, `budget_exhausted`, `budget_unavailable` (also used for `price_unavailable`). Confirmation, estimate, not-active and reconciliation denials do not persist a reason.

### BudgetPort (owner E11-1)

Estimate source: the caller (the dispatch gate) supplies a bounded `Estimate {inference_input_tokens, inference_output_tokens, compute_minutes}` (nonnegative integers, the maximum the work may use). The work request declares it; a missing or unbounded estimate is `estimate_missing`. Cost of an estimate or of measured usage is computed by the `PriceTable` with integer ceiling arithmetic. Inference cost counts against the inference limits and compute cost against the compute limits; a capability does not gate compute separately (compute is a metered resource of any dispatched work).

Shapes:

- `Hold {id, instance_id, work_id, price_table_version, inference_micro_usd, compute_micro_usd, window_day, window_month, state, created_at}` with `state` of `held | settled | released | unknown`; `window_day` is the UTC date and `window_month` the UTC `YYYY-MM` of `created_at`.
- `Usage {hold_id, instance_id, inference_input_tokens, inference_output_tokens, compute_minutes, inference_micro_usd, compute_micro_usd, price_table_version, window_day, window_month, recorded_at}`; usage is never rewritten.
- `BudgetView {instance_id, limits, windows: {day, month}, per category and window: {limit, settled, held, available}, unknown_hold_count, price_table_version}` where `available = max(0, limit - settled - held)`.

Operations (every one runs in one `BEGIN IMMEDIATE` SQLite transaction; a lock timeout or any storage error is `unavailable` and denies):

- `reserve(instance_id, work_id, estimate) -> Hold`: idempotent on `(instance_id, work_id)`; a repeat returns the original hold even if terminal, a repeat with a different estimate is `conflict`. In the same transaction it selects the effective price-table version, prices the estimate, sums settled usage plus outstanding `held` and `unknown` holds for the inference-day, inference-month, compute-day and compute-month windows, and creates the hold only if every one of the four checks passes. Concurrent reservations that jointly exceed any limit cannot both succeed because the writer lock serializes them. Denials: `budget_exhausted` (limit would be exceeded or is 0), `budget_unavailable` (limits missing or invalid, unreadable state), `price_unavailable`, `reconciliation_pending` (the instance has an `unknown` hold).
- `settle(hold_id, measured_usage) -> Usage`: idempotent per hold; same measured usage returns the stored `Usage`, different measured usage on a settled hold is `conflict`. Cost uses the price-table version stored on the hold, not the current one. The hold becomes `settled` and its reservation is released; attribution stays in the hold's original windows even if settlement happens after midnight. If measured cost exceeds the hold, the full measured cost is recorded (never truncated), the window may exceed its limit, a `budget.overrun` audit event is appended, and the instance is gated `budget_exhausted` at the next dispatch.
- `mark_unknown(hold_id)`: idempotent; the hold keeps its full reserved amount in all windows until reconciled and blocks new reservations for that instance.
- `reconcile(hold_id, outcome)`: `outcome` is `{measured_usage}` (then behaves like `settle`) or `{no_usage: true}` (releases the hold with zero usage). Only the internal reconciler calls it, using the executor's `lookup(work_id)`; it is idempotent. Failure to reconcile leaves the hold in place and the instance denied.
- `release(hold_id)`: for work that the executor reports as definitely not started; idempotent.
- `read_budget(instance_id) -> BudgetView`: read-only; used by E11-5 projections.

An unreconciled hold blocks both the reserved amount in every applicable window and any new work for that instance. A new owner mutation or window rollover does not release it.

### PriceTable (owner E11-1)

Source: an operator-managed JSON file named by `AICL_PRICE_TABLE_PATH`, imported at startup into insert-only tables (`price_table_version`, `price_rate`). There is no environment variable that selects a version; selection is by effective date.

```json
{"version": "2026-10-01", "effective_from": "2026-10-01T00:00:00Z",
 "rates": [{"meter": "inference.input_tokens", "unit_size": 1000, "micro_usd": 1000},
           {"meter": "inference.output_tokens", "unit_size": 1000, "micro_usd": 3000},
           {"meter": "compute.minutes", "unit_size": 1, "micro_usd": 5000}]}
```

Validation: `version` unique non-empty string `[A-Za-z0-9._-]{1,32}`; `effective_from` UTC timestamp; all three meters present exactly once; `unit_size` positive integer; `micro_usd` nonnegative integer; no floats. Cost for a meter is `ceil(units * micro_usd / unit_size)`.

Immutability: the import stores the SHA-256 of the canonical JSON next to the version. Re-importing the same version with a different hash is a startup failure; database triggers reject `UPDATE` and `DELETE` on both tables. A price change is a new version with a later `effective_from`. The effective version for a request is the one with the greatest `effective_from` not later than `now`.

Failure behavior: at startup, a missing file, invalid schema, hash conflict, or no version effective at startup time fails startup. At use, no version effective at `now`, or a missing meter, denies the reservation as `price_unavailable` (never a default price). Each hold and usage row stores the applied version, so historical USD totals stay explainable.

### AuditEvent (owner E11-1)

`AuditEvent {seq, id, tenant_id, owner_id, instance_id | null, connection_id | null, event_type, actor_kind, outcome, reason | null, details, occurred_at}`. `seq` is a strictly increasing integer from the table's autoincrement key and is the ordering authority. `actor_kind` is `owner | chat | system | gate`; `outcome` is `committed | denied`.

Event types: `instance.created`, `instance.lifecycle_changed`, `instance.capability_changed`, `instance.limits_changed`, `instance.domain_added`, `instance.domain_removed`, `instance.gated`, `instance.gate_resolved`, `connection.created`, `connection.attached`, `connection.detached`, `connection.revoked`, `connection.provider_revoke_succeeded`, `connection.provider_revoke_failed`, `confirmation.requested`, `confirmation.created`, `confirmation.used`, `work.denied`, `work.dispatched`, `budget.reserved`, `budget.settled`, `budget.unknown`, `budget.reconciled`, `budget.overrun`, `auth.signed_in`, `auth.signed_out`, `access.denied`.

Redaction allow-list: `details` may contain only these keys (any other key is dropped by the writer, and a test asserts it): `from`, `to`, `action`, `capability`, `enabled`, `version`, `limit_field`, `old_micro_usd`, `new_micro_usd`, `host` (owner-added domain), `provider`, `connection_id`, `hold_id`, `micro_usd`, `price_table_version`, `denial_reason`, `confirmation_id`, `payload_digest_prefix` (first 12 hex characters), `template_id`, `surface` (`wizard | chat | ui`), `target_kind`. Never recorded: instructions, instance names, email addresses, tokens, authorization codes, secrets, message or post bodies, full payloads, full digests, destination URLs with paths or queries.

Append-only: the only writer is `AuditLog.append(conn, event)`, called inside the same transaction as the change it records (so a rolled-back change leaves no event). Denial events append in their own transaction because no state changes. Database triggers abort `UPDATE` and `DELETE`. Readers are `list_for_instance(auth, instance_id, after_seq, limit<=100)` and `list_for_owner(auth, after_seq, limit<=100)`, newest first, always filtered by `auth.tenant_id`; E11-5 uses them for the audit history views. Appenders by ticket: E11-1 (budget, instance primitives, gate-state events), E11-2 (creation, operations, connection, confirmation, gate events), E11-3 (`auth.*`).

### ActionConfirmation and PendingAction (owner E11-1)

Per D11-1, `gmail.send` and `reddit.post` need a per-action owner confirmation in addition to an enabled capability and available limits.

- `payload_digest = sha256(canonical_json({instance_id, capability, payload}))` where canonical JSON uses sorted keys, no whitespace, UTF-8. The dispatch gate computes the digest itself from the request; callers never supply it.
- `PendingAction {id, instance_id, tenant_id, capability, payload_digest, preview, created_at}`: created by the gate when it denies `confirmation_required`. `preview` is a bounded allow-listed summary (for example recipient domain, subreddit, body length), never the body.
- `ActionConfirmation {id, pending_action_id, instance_id, capability, payload_digest, owner_id, tenant_id, created_at, expires_at, used_at | null}`: single use, bound to exactly one digest, expires after `AICL_CONFIRMATION_TTL_SECONDS` (default 300).
- Creation: `create_confirmation(auth, pending_action_id)` creates it only from an owner-authenticated, CSRF-protected UI form request. It is not in the web-app tool registry, is not reachable through `/app-tools/*`, and the chat orchestrator holds no reference to it, so chat text or a tool call cannot create or approve one. It is idempotent per pending action (a second call returns the existing unused unexpired confirmation).
- Consumption: the gate consumes it with a single conditional update (`used_at IS NULL AND expires_at > now AND payload_digest = computed`) inside the same transaction as the budget reservation, so a denial earlier or later in the check order never burns a confirmation wrongly and two concurrent dispatches cannot both use it. A missing confirmation is `confirmation_required` (and a `PendingAction` is created or reused); an expired one is `confirmation_expired`; a used one is `confirmation_used`; one for a different digest (changed payload) is `confirmation_mismatch`. Each is audited (`confirmation.requested`, `confirmation.created`, `confirmation.used`, `work.denied`).
- If the executor reports the work definitely did not send, the hold is released but the confirmation stays consumed; the owner must confirm again.

### WebAppToolSchemas (owner E11-2)

First-party web-app tools (not a public or external MCP API) are served at `POST /app-tools/{name}` for same-origin authenticated callers (session cookie plus `X-CSRF-Token`). The registry is a static dict of name to pydantic input model and handler; the same handlers back the wizard where applicable. Every input model forbids extra fields, so `tenant_id`, `owner_id`, `session_id`, credential fields and confirmation fields are rejected as `validation_failed`/`unknown_argument`. Tool list and schemas:

| Tool | Input | Result |
|---|---|---|
| `list_templates` | `{}` | the catalog (`template_id`, `name`, `capabilities`, constraints) |
| `create_instance` | `CreateInstanceRequest` fields | `CreateInstanceResult` |
| `read_instance` | `{instance_id}` | `InstanceView` (the caller's tenant only) |

No other operation is a tool. Lifecycle, capability, limit, domain, connection, confirmation and gate operations are owner-UI form operations only, so chat cannot reach them. Tools return the error taxonomy above. The registry exposes no connection, secret, budget-writing or confirmation operation.

## Process topology

One FastAPI process (plus Uvicorn) serves HTML pages, form posts, `/app-tools/*` and the chat API. All services run in-process and share one SQLite database file (WAL mode, `busy_timeout` 5000 ms, foreign keys on). The call direction is: routes (E11-3/E11-4/E11-5) → `InstanceOperations` and `create_instance` (E11-2) → control-plane repositories, `BudgetPort`, `AuditLog` (E11-1). The authenticated `AuthContext` is resolved once per request by the configured `AuthProvider` and passed down explicitly. The budget controller owns holds, usage and the price table; UI projections only call `read_budget` and the audit readers. Transactions: each operation is one SQLite transaction (`BEGIN IMMEDIATE` for anything that writes), with the audit append inside it. There is no cross-process channel in the MVP; the optional reconciler runs as an in-process periodic task (`reconcile_unknown_holds`) every `AICL_RECONCILE_INTERVAL_SECONDS` and once at startup.

## Configuration

The authoritative variable table is in [architecture.md](../architecture.md#consolidated-configuration). Rows owned here: `AICL_DATABASE_URL`, `AICL_PRICE_TABLE_PATH`, `AICL_RECONCILE_INTERVAL_SECONDS`, `AICL_CONFIRMATION_TTL_SECONDS`. Startup fails on a missing or unreadable database path, a missing or invalid price table, or a failed schema migration. Per instance, default limits are 0 and enforcement is at use: unavailable budget state, unknown price or invalid limits deny the request. `PRICE_TABLE_VERSION` no longer exists. No real inference, compute or other provider adapter exists in this feature; the default and only composition uses the fake ports (safe disabled mode).

## Verification pointers

E11-1 proves F1-S1 to F1-S13 with unit tests (cost math, transition table, redaction allow-list, price validation) and integration tests against real SQLite (isolation, `BudgetPort` atomicity with two threads, idempotency, over-measured usage, unknown holds, immutability triggers, append-only triggers). E11-2 proves F1-S14 to F1-S16 and the creation tool boundary through the real service and `/app-tools/*` with the same database. Consumer tickets reuse these rather than re-testing them.
