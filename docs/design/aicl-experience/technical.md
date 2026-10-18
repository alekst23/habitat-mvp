# AICL experience technical design

Scope: E11-3 (landing, magic-link sign-in, workspace shell, creation wizard), E11-4 (built-in chat creation surface) and E11-5 (read projections, Connections area, instance management pages, confirmation prompt, production wiring). Canonical creation, instance operations, tool schemas, budget, audit and confirmation contracts are owned by E11-1 and E11-2: see [aicl-control-plane/technical.md](../aicl-control-plane/technical.md) and [connection-network-policy/technical.md](../connection-network-policy/technical.md). This document does not redefine them. Stack, layout and the consolidated configuration table are in [architecture.md](../architecture.md).

## Contracts

### Contract ownership

| Contract | Owner | Consumers | Notes |
|---|---|---|---|
| `CreateInstanceRequest`, `CreateInstanceResult`, `InstanceSnapshot`, `WebAppToolSchemas`, `InstanceOperations` | E11-2 | E11-3, E11-4, E11-5 | Canonical service; the wizard, chat and tools all call it |
| `SessionAuthProvider`, `HmacCsrfVerifier`, `MagicLinkSender` | E11-3 | E11-5 | Real implementations of the E11-1 `AuthProvider` and `CsrfVerifier` Protocols; E11-4 and E11-2 routes use the E11-1 `CsrfVerifier` through the shared `require_csrf` dependency and see the real one only once E11-3 is integrated |
| `ChatModelPort` | E11-4 | E11-5 | Deterministic engine behind the chat |
| Read projections (`WorkspaceView`, `InstanceDetailView`, `ConnectionsView`) | E11-5 | none | Read-only compositions of other contracts; `InstanceDetailView` composes the E11-2 `InstanceSnapshot` |

### SessionAuthProvider and magic-link sign-in (owner E11-3)

Implements `AuthProvider.resolve` from the control-plane document and produces `AuthContext`. Tables: `owner (id, email_hash, created_at)`, `magic_link (token_hash, email_hash, created_at, expires_at, used_at, requested_ip_hash)`, `session (id_hash, owner_id, created_at, expires_at, revoked_at)`.

- Email handling: the address is trimmed, lowercased, and must be at most 254 characters with one `@`; the stored form is `HMAC-SHA256(AICL_IDENTITY_HMAC_KEY, email)`. `AICL_IDENTITY_HMAC_KEY` is a separate required secret used only for this identity hash and for the derived IP-hash subkey below; it must not be rotated without a migration of `owner.email_hash` (rotation would give every returning owner a new tenant), while `AICL_SESSION_SECRET` is used only for session and CSRF tokens and may be rotated (which signs everyone out). The plaintext address is held in memory only long enough to hand it to the `MagicLinkSender`. The first successful sign-in for a new email hash creates the `owner` row with `owner_id = tenant_id = new UUID4` (tenant equals owner for the MVP).
- `POST /auth/magic-link {email}` always responds with the same 202 page ("If the address can receive mail, a link is on its way") with the same status and a constant-shape body whether or not an owner exists, the address is valid for delivery, or sending failed. Rate limit: at most 5 requests per email hash and 20 per client IP hash per hour, counted in the database; over the limit still returns the same 202 and sends nothing (no existence or limit leak). The denial is audited as the pre-authentication system event `auth.link_rate_limited` (`access.denied` is reserved for authorization denials) with `tenant_id` and `owner_id` null, `actor_kind=system`, and only `reason_code=rate_limit`, `count` and, for an email window, `email_hash_prefix` in `details`; no email address, IP or IP hash is recorded. At most one such event is appended per email-hash or IP-hash window (`count` is set at append, since the log is append-only); later over-limit requests in that window append none, so a flood cannot grow the log. `magic_link.requested_ip_hash` is `HMAC-SHA256(ip_subkey, client_ip)` with `ip_subkey = HMAC-SHA256(AICL_IDENTITY_HMAC_KEY, "aicl-ip-hash-v1")`, never an unkeyed hash; rotating the key only resets rate-limit counting. Purge: the E11-3 `MagicLinkPurge` hook (registered in `STARTUP_HOOKS`, `run_once()`) deletes `magic_link` rows expired for more than 24 hours at startup and hourly. The `owner` row is not created for it.
- Token: 32 random bytes, URL-safe base64, only the SHA-256 hash is stored, expiry `AICL_MAGIC_LINK_TTL_SECONDS` (default 900), single use. A new request does not invalidate older unexpired tokens. The link is `AICL_PUBLIC_BASE_URL/auth/verify?token=...`; the page is a GET that renders a confirmation form and the sign-in itself is a `POST /auth/verify` so mail scanners that prefetch links cannot consume it. Verification marks the token used in a conditional update (`used_at IS NULL AND expires_at > now`), rotates any prior session cookie, creates a session, sets the cookie and appends `auth.signed_in`. Unknown, expired and reused tokens all show the same generic "link invalid or expired" page and append the pre-authentication event `auth.link_rejected` (null tenant and owner, `reason_code` of `unknown`, `expired` or `used`, `token_hash_prefix`). These events are never returned by the owner readers.
- Session: opaque 32 random byte id, stored hashed, cookie `aicl_session` with `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` unless the non-production test flag is set, `Max-Age` equal to `AICL_SESSION_TTL_SECONDS` (default 28,800, absolute expiry, no sliding renewal). `POST /auth/logout` (CSRF protected) sets `revoked_at`, clears the cookie and appends `auth.signed_out`; a revoked or expired session resolves to no `AuthContext`.
- CSRF: E11-3 implements `HmacCsrfVerifier` behind the E11-1 `CsrfVerifier` Protocol. Authenticated non-GET browser requests require the `X-CSRF-Token` header or `csrf_token` form field equal to `HMAC(AICL_SESSION_SECRET, session_id)`, rendered into pages; the `Origin` header must equal `AICL_PUBLIC_BASE_URL` when present. Routes call the shared E11-1 `require_csrf` dependency and never the HMAC directly. A client-supplied `tenant_id` or `owner_id` is ignored by form handlers and rejected by tool schemas.
- Pre-session sign-in confirmation has its own origin boundary: `POST /auth/verify` requires `Origin` to equal the scheme and authority of `AICL_PUBLIC_BASE_URL` and rejects `Sec-Fetch-Site: cross-site`. Missing, foreign or `null` origins are denied before reading or consuming the token or creating a session. A valid email link does not by itself prove that a browser intended to enter that account. The GET confirmation page remains safe to prefetch. Non-browser clients must send the same expected `Origin` header; this check is not disabled in tests.
- `MagicLinkSender` Protocol: `send(email, link)`. `SmtpMagicLinkSender` (production) uses the `AICL_SMTP_*` settings of the operator-configured SMTP server; this is the application's one real outbound edge and is distinct from Gmail and from the rejected provider, executor and chat-model adapters. `CaptureMagicLinkSender` (test only) appends `{email, link}` to an in-memory list exposed by `GET /__test__/last-magic-link?email=` and is installed only when `AICL_TEST_MODE=1` AND `AICL_ENVIRONMENT=test`; the route does not exist otherwise. The real magic-link flow is proven by E11-3 (and by E11-5 on the production composition). Tests of other tickets that need a signed-in browser use the seeded test session below instead.

### Wizard and workspace (owner E11-3)

Routes (server-rendered Jinja2 templates with minimal vanilla JS; no SPA framework): `GET /` landing (F3-S1, with **Create your first agent** linking to sign-in), `GET /workspace` (empty state shows **Create with wizard** and **Create with chat**, per D11-10; non-empty shows the E11-5 list), `GET /agents/new` and `POST /agents/new` (wizard). The wizard collects `name`, `instructions` and capability checkboxes (all unchecked by default) on one page, submits `CreateInstanceRequest` fields with a hidden per-form idempotency key `wiz_<32 hex>` (a fresh UUID4 per rendered form) through `create_instance` (E11-2) and renders the `CreateInstanceResult` (draft instance, "not active until you activate it") or the `field_errors`. It has no budget, connection or credential fields; it links to the instance page where E11-5 provides activation, limits and attachments. Unauthenticated access to any workspace route redirects to the landing page.

### ChatModelPort and the chat surface (owner E11-4)

`ChatModelPort` (Protocol): `next_step(state: ChatState, user_text: str) -> ChatStep` where `ChatStep` is one of `Ask {field, text}`, `ToolCall {tool, arguments}`, `Say {text}`. `ChatState {chat_session_id, turn, slots: {name, instructions, enabled_capabilities}, awaiting}` is stored per chat session in SQLite (`chat_session`, `chat_message` tables, tenant scoped, retained until the owner deletes them or 30 days). `ScriptedChatModel` is the only enabled implementation (`AICL_CHAT_MODEL_MODE=fake`): a deterministic slot-filling state machine that asks for name, then instructions, then capabilities (listing the six catalog names), summarizes, and on an explicit "yes"/"create" calls the `create_instance` tool; it uses only keyword matching and no network or model call. A real language model is provider enablement, is rejected at startup, and would require its own reviewed enablement.

Boundary rules (all enforced by the chat orchestrator, not by the model):

- The only tools reachable from chat are `list_templates`, `create_instance`, `read_instance` with the exact schemas in the control-plane document, invoked with the session's own `AuthContext` and no tenant, owner, credential, connection or confirmation argument (the schemas forbid them). The orchestrator holds no reference to `create_confirmation`, `revoke_connection`, lifecycle, limit, capability, domain or work-request operations.
- User text and any instance text (names, instructions) are untrusted data. They are inserted into replies only as escaped plain text, never interpreted as tool names, arguments or instructions; a tool call is produced only by the state machine from validated slots.
- The idempotency key for `create_instance` is `chat_<32 lowercase hex of chat_session_id>_<turn>` (`turn` a decimal integer from 1; 39 to 44 characters, within the 16 to 64 character `[A-Za-z0-9_-]` pattern), so a retried turn creates one instance. A unit assertion in E11-4 checks the pattern and length for the first and the largest turn. A `validation_failed` result produces an `Ask` for the offending field with the field error; `unavailable` produces a retryable message; `denied` is displayed verbatim in safe form. Chat never receives OAuth credentials: connection setup is an owner-UI flow, and the chat only links to the Connections area.
- Chat consumes no instance budget: it is not an instance work request and does not call `BudgetPort`. The fake model has no cost; any future real model would need its own spending control as part of enablement.
- E11-4 browser sign-in uses the seeded test session of the E11-1 test server (below), not the production sign-in route; E11-3 proves the real magic-link flow and E11-5 proves production-wired real sign-in. E11-4 declares no dependency on E11-3.
- Routes: `GET /chat`, `POST /chat/messages` (session and CSRF protected, through `require_csrf`). The chat message returns the reply and, after creation, a link to the new instance page.

Source pointers (E11-4 contract stubs, behavior-free, committed on `ctx/ticket-i15`; the implementation replaces the `NotImplementedError` bodies): `backend/aicl/chat/models.py` (`ChatState`, `ChatSlots`, `Ask`, `ToolCall`, `Say`, `ChatStep`, `ChatMessage`, `ChatReply`, `ALLOWED_CHAT_TOOLS`, `MAX_TURN`), `backend/aicl/chat/ports.py` (`ChatModelPort`, `ScriptedChatModel`), `backend/aicl/chat/service.py` (`chat_key`, `ChatStore`, `ChatOrchestrator`, `SqliteChatOrchestrator`) and `backend/aicl/chat/routes.py` (`chat_router`). `chat_router` is added to `ROUTE_FACTORIES`, and `ScriptedChatModel` to `PORT_REGISTRY` and `REQUIRED_PORTS` as `chat_model`, by the implementation, not by the stubs; the `chat_session` and `chat_message` migration is likewise implementation work. `AICL_CHAT_MODEL_MODE` is already validated by `settings.py` (only `fake`) and listed in `.env.example`. The orchestrator validates tool arguments with the E11-2 `TOOL_REGISTRY` input models and creates instances through `aicl.creation.service.create_instance(..., actor_kind="chat", surface="chat")`, because the HTTP tool handler records `owner` and `ui`; chat makes no HTTP hop to `/app-tools/*`.

### Read projections and management pages (owner E11-5)

Read models, all filtered by `auth.tenant_id` and built only from the other contracts' read operations: `WorkspaceView {instances: [InstanceSummary]}`, `InstanceDetailView {snapshot: InstanceSnapshot, budget: BudgetView, usage_history, audit: [AuditEvent], pending_actions}` (the E11-2 `InstanceSnapshot` supplies id, name, instructions, lifecycle, status, gated reason, version, capabilities, attachments and network domains; E11-5 adds nothing to it), `ConnectionsView {connections, attachments}`. `InstanceSummary` shows name, lifecycle, derived status and the gate reason. `budget` is rendered as USD with six decimals from micro-USD. Audit is rendered from `AuditLog.list_for_instance`, which already holds only allow-listed fields.

Mutation UIs, each a server-rendered form that posts the `expected_version` and a CSRF token to the E11-2 operation and re-renders the committed instance or the structured denial (F3-S5, F3-S7). Ownership:

| UI | Ticket | Calls |
|---|---|---|
| Landing, sign-in, logout, workspace shell, wizard | E11-3 | `SessionAuthProvider`, `create_instance` |
| Chat | E11-4 | `ChatModelPort`, tools |
| Non-empty workspace list and instance read page | E11-5 | `WorkspaceView`, `InstanceDetailView`; E11-3 shows only the empty state and the wizard result, so visible-list tenant isolation and chat versus wizard equivalence across surfaces (F3-S3) are E11-5's, while E11-3 proves cross-tenant `not_found` at integration level and E11-4 compares the chat result with a direct canonical `create_instance` call |
| Connections area: list, begin OAuth, revoke | E11-5 | `begin_oauth`, callback result, `revoke_connection` |
| Instance detail, activate, pause, resume, archive | E11-5 | `set_lifecycle` |
| Capability toggles, attach and detach connection | E11-5 | `set_capability`, `attach_connection`, `detach_connection` |
| Daily and monthly limit editing | E11-5 | `set_limits` |
| Owner `network.fetch` domain editing | E11-5 | `add_network_domain`, `remove_network_domain` |
| Resolve-gate button | E11-5 | `resolve_gate` (labelled **Re-check and clear**; it clears the gate only when the control now permits work, otherwise it shows the `gate_unresolved` denial and the gate stays) |
| Simulated work request form (labelled simulated) | E11-5 | `POST /instances/{id}/work-requests` |
| Confirmation prompt for `gmail.send` and `reddit.post` | E11-5 | `create_confirmation` via `POST /pending-actions/{id}/confirm` |

The instance page states plainly that revocation does not undo actions already taken, that real provider adapters are not enabled, and that gated reasons stay until the owner fixes the control and the system re-checks it as permitting work.

### Test server and seeded test session (owner E11-1)

`python -m aicl.test_server` and `npm run start:test` are owned by E11-1 (architecture document), together with `backend/requirements.txt` and the root `package.json` and `package-lock.json`. In the test composition (`AICL_TEST_MODE=1` and `AICL_ENVIRONMENT=test`, both required) the server additionally registers `POST /__test__/seed-session {fixture}` which creates a session for a seeded fixture owner (`fixture-a` or `fixture-b`, tenant equals owner) through the E11-1 `FixedAuthProvider`/`FixedCsrfVerifier` path and sets the `aicl_session` cookie. It never calls or replaces the production sign-in route, does not exist outside the test composition (the route is absent, startup refuses the test flags in any other environment) and is not a general bypass: there is no password, no production account bypass and no fixed credential in any other composition. Once E11-3 is integrated the same test server also routes real sessions to `SessionAuthProvider`.

### Production wiring (owner E11-5)

E11-1 owns the `create_app` skeleton and the router-registration extension point (control-plane document, AppComposition); E11-2 to E11-5 each add their routers and real ports. E11-5 owns the proof that the composition is complete, run with the test flags on (`AICL_TEST_MODE=1`, `AICL_ENVIRONMENT=test`, as `python -m aicl.test_server` builds it): `create_app(settings)` with `ports=None` (default `build_ports`, control-plane AppComposition) resolves every required port, registers every `ROUTE_FACTORIES` entry and every `STARTUP_HOOKS` hook (sweeper, reconciler, magic-link purge) and registers every route of every ticket and every real port (real SQLite repositories, real `SessionAuthProvider`, `HmacCsrfVerifier`, `WorkAuthorization`, `CredentialBroker`, `SecretStore`, `BudgetPort`, audit log and the reconciler), and fails startup when any is missing. This is test-composition evidence: production differs only by the absent `/__test__/*` routes, the SMTP sender instead of the capture sender, the absent seeded session and the absent fake OAuth page. Only the leaf ports are fakes: `FakeProviderOAuth`, `FakeWorkExecutor`, `ScriptedChatModel`, `CaptureMagicLinkSender` (test mode only) and the controllable `Clock`. The browser journeys of E11-5 start the server with the real sign-in (no seeded session) through `python -m aicl.test_server`, which is `create_app(test settings)` plus the test-only routes, so every journey uses the registry-built real services with no in-test replacement of internal services; no route, service or gate is mocked, stubbed or bypassed for any journey. Wiring evidence (E11-5.AC1): one real-browser journey series proves, on that composition, the real magic-link sign-in, wizard creation, chat creation producing an equivalent instance, activation, all four limits raised to positive values (a zero limit is exhausted even for a zero-cost category), capability and attachment (through the fake OAuth page), a simulated work request that is settled and visible in usage, an over-limit request that gates, a gate that stays after **Re-check and clear** while the control still denies and clears once the limit is raised, a confirmation-requiring send that is denied, confirmed once, executed once and denied on replay (the replay resubmits the same payload with a new `work_id` and gets `confirmation_used`), revocation that detaches and gates, another tenant's isolation, and the redacted audit history.

Source pointers (E11-5 contract stubs, behavior-free, committed on `ctx/ticket-i16`; the implementation replaces the `NotImplementedError` bodies): `backend/aicl/web/views.py` (`WorkspaceView`, `InstanceSummary`, `InstanceDetailView`, `ConnectionsView`, `ConnectionSummary`, `AttachmentRow`, `format_usd`, `parse_usd`, `ProjectionStore`, `ProjectionService`, `SqliteProjectionService`), `backend/aicl/web/manage.py` (`manage_router` and the proposed `MANAGEMENT_ROUTES` table) and `backend/aicl/web/proof.py` (`FINAL_REQUIRED_PORTS`, `FINAL_STARTUP_HOOKS`, `EQUIVALENCE_FIELDS`, `CompositionReport`, `inspect_composition`, `equivalent_surfaces`, `CompositionIncomplete`). `manage_router` is appended to `ROUTE_FACTORIES` by the implementation, and `GET /workspace` (E11-3, `web/routes.py`) is changed there to render `WorkspaceView`. The E11-1 `build_ports` currently substitutes a `SystemClock` for a required port without a registered factory, so the missing-port startup failure that this section requires is implementation work (`CompositionIncomplete`), as is the `usage_history` and pending-action read through `ProjectionStore` (no other contract lists those rows).

## Process topology

Landing and authentication pages are public; every other route resolves `AuthContext` through `SessionAuthProvider` and redirects (pages) or returns `unauthenticated` (tools and JSON routes) when absent. The authenticated workspace hosts wizard, chat, connections, list and detail routes. Wizard and chat call the one canonical `create_instance`; management pages call `InstanceOperations`; work and confirmation call `WorkAuthorization`. All in one process, one database; the only external edges are magic-link email through the operator-configured SMTP server (`MagicLinkSender`, distinct from Gmail) and the fake provider and executor. The fake provider authorize page exists only in the test and development compositions; every `/__test__/*` route exists only when both `AICL_TEST_MODE=1` and `AICL_ENVIRONMENT=test`. Pages never accept a tenant ID and never include a credential or secret.

## Configuration

Authoritative table: [architecture.md](../architecture.md#consolidated-configuration). Rows owned here for behavior: `AICL_SESSION_SECRET`, `AICL_IDENTITY_HMAC_KEY`, `AICL_SESSION_TTL_SECONDS`, `AICL_MAGIC_LINK_TTL_SECONDS`, `AICL_SMTP_HOST`, `AICL_SMTP_PORT`, `AICL_SMTP_USERNAME`, `AICL_SMTP_PASSWORD`, `AICL_SMTP_FROM`, `AICL_CHAT_MODEL_MODE`. The validation of every row, including these, is implemented in E11-1 `settings.py`; `AICL_ENVIRONMENT` and `AICL_TEST_MODE` are owned by E11-1. Startup fails when `AICL_SESSION_SECRET` or `AICL_IDENTITY_HMAC_KEY` is missing, a placeholder or shorter than 32 bytes (or when the two are equal), and when magic-link delivery is not configured (`AICL_SMTP_HOST` unset) unless the test composition (`AICL_TEST_MODE=1` and `AICL_ENVIRONMENT=test`) is active. `AICL_TEST_MODE=1` with `AICL_ENVIRONMENT` other than `test`, or either value being anything unexpected, fails startup, so email capture and the seeded test session cannot be enabled in production by one flag. UI code never accepts a tenant ID.

## Verification pointers

E11-3 proves F3-S1, F3-S2, F3-S8 and the wizard half of F3-S3 and F3-S5 with integration tests (token TTL, single use, hash storage under the identity key, no-existence-leak equality, pre-authentication audit events with null identity and no owner-reader exposure, cookie flags, logout, `HmacCsrfVerifier`, cross-tenant `not_found`) and one browser journey with the real magic-link flow. E11-4 proves F3-S6 and the chat half of F3-S3 with unit tests of the state machine, tool allow-list, schema rejection and the idempotency-key pattern and length, plus a browser chat journey that signs in through the seeded test session. E11-5 proves F3-S4, F3-S7 and F3-S9 and the wiring criterion with the production-wired browser journeys above.


## UI refinement (E11-6)

### Presentation contract

The UI refinement consumes the existing `WorkspaceView`, `InstanceDetailView`,
`ConnectionsView`, wizard/chat contexts and structured errors described above.
The service and route layers remain the producers; Jinja templates and the small
browser handlers remain consumers. The presentation changes
`backend/aicl/web/pages.py`, `backend/aicl/web/manage_pages.py`, and the new
repository-owned `backend/aicl/web/styles.py` stylesheet constant. The only route
adapter change is CRLF-to-LF normalization of the wizard instructions field in
`backend/aicl/web/routes.py`, as specified below. There are no
new backend models, ports, settings, migrations, provider adapters or routes, so
new typed contract stubs are not applicable.

`pages.py` owns a shared public/authenticated base shell. The authenticated shell
provides Workspace, Create an agent and Connections navigation; child templates
select an active page and provide the heading, subtitle and actions. Public pages
retain the landing and email-link entry flow. The shell advertises the simulated
environment. Styles use local system fonts and repository-owned inline SVGs; no
external font, script, image or CDN request is introduced. All untrusted names,
instructions, messages, errors, domain names and provider data remain autoescaped.
The stylesheet is trusted source concatenated into the base template, never
untrusted template data or a blanket `safe` escape bypass.

Workspace totals derive only from the supplied owner-scoped instance collection.
Active lifecycle counts are labeled as subject to controls rather than claiming
work eligibility. Gated status remains distinct from lifecycle. Budget amounts
retain six-decimal USD precision and the distinction between limits, settled
usage and held reservations. Connections and simulated work retain truthful fake
provider wording and revocation limitations. Empty states explain actual state;
no example records or invented activity/metrics are shown.

At desktop and 375 CSS pixels, all page actions remain reachable. Forms use
associated labels, visible keyboard focus, semantic headings and buttons, and
status regions for action feedback. Narrow tables scroll inside their own
container rather than widening the page. Long owner text wraps safely. Visual
presentation changes no server field names, HTTP methods/actions, CSRF tokens,
expected versions, idempotency keys, tenant derivation, canonical creation calls
or confirmation authorization.

### Wizard textarea transport normalization

HTML form submission serializes textarea newlines as CRLF even when the owner
entered ordinary line breaks. The canonical instructions contract permits LF and
tab but rejects a bare CR as a control character. The wizard route therefore
normalizes only each CRLF pair to LF before constructing `CreateInstanceRequest`;
it does not strip or normalize bare CR, change other characters, or relax
canonical validation. This is a boundary conversion from HTML transport to the
existing text contract, with no schema, route signature or business-rule change.
The browser regression submits multiline instructions through the real wizard
and verifies the created agent displays the line breaks correctly instead of a
spurious `instructions: control_character` denial.

### Asynchronous action feedback

The simulated-work handler submits the existing work request schema and uses a
single newly generated work ID for one intentional submission. It validates the
minute field as a non-negative safe integer before sending, disables its submit
button synchronously, sets `aria-busy`, and exposes an accessible in-flight
message. A second submit event while disabled does nothing. Existing JSON
`outcome`, `reason`, `error` and optional `message` fields are rendered as text;
known denials remain denials. A returned `unknown` outcome explains the retained
reservation and keeps repeat submission disabled in that view. A network or
unreadable-response failure cannot prove whether work ran: it stays disabled and
asks the owner to reload and check activity. No automatic retry is issued. A
known terminal result links back to the actual instance page so refreshed usage,
gates and confirmations can be read from the server.

Confirmation and connection-begin controls likewise prevent simultaneous repeated
clicks and show in-flight and failure feedback. A confirmation response is never
reported as executed work; successful confirmation keeps its one-use semantics
and tells the owner to resubmit the same work request through the existing flow.
Connection setup still navigates only to the authorization URL returned by the
existing authenticated OAuth endpoint. Neither handler changes server-side
transaction boundaries, replay protection, authentication or capability checks.

### Verification and wiring

E11-6.AC1 maps F3-S10 and F3-S11. A minimal real-browser journey on the existing
registered test composition covers the shared shell, actual owner projections,
desktop and 375-pixel usability, form labels and preserved control semantics,
plus duplicate suppression and honest pending/failed/unknown work feedback.
Response interception may exercise transport failure and uncertain UI states;
such cases are presentation evidence only and do not replace the existing real
service and gate journeys. Existing E11-3, E11-4 and E11-5 browser journeys remain
unchanged regression evidence for sign-in, canonical creation, tenant isolation
and the actual management entry points. The expanded plan's current final wiring
checkpoint moves to E11-6 because it consumes the fully integrated E11-5 pages;
E11-5.AC1 and all earlier wiring evidence remain intact. Final E11-6 verification
and independent review must name its own new candidate SHA and acceptance hash;
the completed five-ticket baseline is not evidence for the new UI revision.
