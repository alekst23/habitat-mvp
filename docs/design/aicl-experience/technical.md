# AICL experience technical design

Scope: E11-3 (landing, magic-link sign-in, workspace shell, creation wizard), E11-4 (built-in chat creation surface) and E11-5 (read projections, Connections area, instance management pages, confirmation prompt, production wiring). Canonical creation, instance operations, tool schemas, budget, audit and confirmation contracts are owned by E11-1 and E11-2: see [aicl-control-plane/technical.md](../aicl-control-plane/technical.md) and [connection-network-policy/technical.md](../connection-network-policy/technical.md). This document does not redefine them. Stack, layout and the consolidated configuration table are in [architecture.md](../architecture.md).

## Contracts

### Contract ownership

| Contract | Owner | Consumers | Notes |
|---|---|---|---|
| `CreateInstanceRequest`, `CreateInstanceResult`, `WebAppToolSchemas`, `InstanceOperations` | E11-2 | E11-3, E11-4, E11-5 | Canonical service; the wizard, chat and tools all call it |
| `SessionAuthProvider` | E11-3 | E11-5 | Real implementation of the E11-1 `AuthProvider` Protocol |
| `ChatModelPort` | E11-4 | E11-5 | Deterministic engine behind the chat |
| Read projections (`WorkspaceView`, `InstanceView`, `ConnectionsView`) | E11-5 | none | Read-only compositions of other contracts |

### SessionAuthProvider and magic-link sign-in (owner E11-3)

Implements `AuthProvider.resolve` from the control-plane document and produces `AuthContext`. Tables: `owner (id, email_hash, created_at)`, `magic_link (token_hash, email_hash, created_at, expires_at, used_at, requested_ip_hash)`, `session (id_hash, owner_id, created_at, expires_at, revoked_at)`.

- Email handling: the address is trimmed, lowercased, and must be at most 254 characters with one `@`; the stored form is `HMAC-SHA256(AICL_SESSION_SECRET, email)`. The plaintext address is held in memory only long enough to hand it to the `MagicLinkSender`. The first successful sign-in for a new email hash creates the `owner` row with `owner_id = tenant_id = new UUID4` (tenant equals owner for the MVP).
- `POST /auth/magic-link {email}` always responds with the same 202 page ("If the address can receive mail, a link is on its way") with the same status and a constant-shape body whether or not an owner exists, the address is valid for delivery, or sending failed. Rate limit: at most 5 requests per email hash and 20 per client IP hash per hour, counted in the database; over the limit still returns the same 202 and sends nothing (no existence or limit leak; the counter is audited as `access.denied`).
- Token: 32 random bytes, URL-safe base64, only the SHA-256 hash is stored, expiry `AICL_MAGIC_LINK_TTL_SECONDS` (default 900), single use. A new request does not invalidate older unexpired tokens. The link is `AICL_PUBLIC_BASE_URL/auth/verify?token=...`; the page is a GET that renders a confirmation form and the sign-in itself is a `POST /auth/verify` so mail scanners that prefetch links cannot consume it. Verification marks the token used in a conditional update (`used_at IS NULL AND expires_at > now`), rotates any prior session cookie, creates a session, sets the cookie and appends `auth.signed_in`. Unknown, expired and reused tokens all show the same generic "link invalid or expired" page.
- Session: opaque 32 random byte id, stored hashed, cookie `aicl_session` with `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` unless the non-production test flag is set, `Max-Age` equal to `AICL_SESSION_TTL_SECONDS` (default 28,800, absolute expiry, no sliding renewal). `POST /auth/logout` (CSRF protected) sets `revoked_at`, clears the cookie and appends `auth.signed_out`; a revoked or expired session resolves to no `AuthContext`.
- CSRF: every non-GET browser request requires the `X-CSRF-Token` header or `csrf_token` form field equal to `HMAC(AICL_SESSION_SECRET, session_id)`, rendered into pages; the `Origin` header must equal `AICL_PUBLIC_BASE_URL` when present. A client-supplied `tenant_id` or `owner_id` is ignored by form handlers and rejected by tool schemas.
- `MagicLinkSender` Protocol: `send(email, link)`. `SmtpMagicLinkSender` (production) uses the `AICL_SMTP_*` settings. `CaptureMagicLinkSender` (test only) appends `{email, link}` to an in-memory list exposed by `GET /__test__/last-magic-link?email=` and is installed only when `AICL_TEST_MODE=1` AND `AICL_ENVIRONMENT=test`; the route does not exist otherwise.

### Wizard and workspace (owner E11-3)

Routes (server-rendered Jinja2 templates with minimal vanilla JS; no SPA framework): `GET /` landing (F3-S1, with **Create your first agent** linking to sign-in), `GET /workspace` (empty state shows **Create with wizard** and **Create with chat**, per D11-10; non-empty shows the E11-5 list), `GET /agents/new` and `POST /agents/new` (wizard). The wizard collects `name`, `instructions` and capability checkboxes (all unchecked by default) on one page, submits `CreateInstanceRequest` fields with a hidden per-form idempotency key through `create_instance` (E11-2) and renders the `CreateInstanceResult` (draft instance, "not active until you activate it") or the `field_errors`. It has no budget, connection or credential fields; it links to the instance page where E11-5 provides activation, limits and attachments. Unauthenticated access to any workspace route redirects to the landing page.

### ChatModelPort and the chat surface (owner E11-4)

`ChatModelPort` (Protocol): `next_step(state: ChatState, user_text: str) -> ChatStep` where `ChatStep` is one of `Ask {field, text}`, `ToolCall {tool, arguments}`, `Say {text}`. `ChatState {chat_session_id, turn, slots: {name, instructions, enabled_capabilities}, awaiting}` is stored per chat session in SQLite (`chat_session`, `chat_message` tables, tenant scoped, retained until the owner deletes them or 30 days). `ScriptedChatModel` is the only enabled implementation (`AICL_CHAT_MODEL_MODE=fake`): a deterministic slot-filling state machine that asks for name, then instructions, then capabilities (listing the six catalog names), summarizes, and on an explicit "yes"/"create" calls the `create_instance` tool; it uses only keyword matching and no network or model call. A real language model is provider enablement, is rejected at startup, and would require its own reviewed enablement.

Boundary rules (all enforced by the chat orchestrator, not by the model):

- The only tools reachable from chat are `list_templates`, `create_instance`, `read_instance` with the exact schemas in the control-plane document, invoked with the session's own `AuthContext` and no tenant, owner, credential, connection or confirmation argument (the schemas forbid them). The orchestrator holds no reference to `create_confirmation`, `revoke_connection`, lifecycle, limit, capability, domain or work-request operations.
- User text and any instance text (names, instructions) are untrusted data. They are inserted into replies only as escaped plain text, never interpreted as tool names, arguments or instructions; a tool call is produced only by the state machine from validated slots.
- The idempotency key for `create_instance` is `chat:<chat_session_id>:<turn>`, so a retried turn creates one instance. A `validation_failed` result produces an `Ask` for the offending field with the field error; `unavailable` produces a retryable message; `denied` is displayed verbatim in safe form. Chat never receives OAuth credentials: connection setup is an owner-UI flow, and the chat only links to the Connections area.
- Chat consumes no instance budget: it is not an instance work request and does not call `BudgetPort`. The fake model has no cost; any future real model would need its own spending control as part of enablement.
- Routes: `GET /chat`, `POST /chat/messages` (session and CSRF protected). The chat message returns the reply and, after creation, a link to the new instance page.

### Read projections and management pages (owner E11-5)

Read models, all filtered by `auth.tenant_id` and built only from the other contracts' read operations: `WorkspaceView {instances: [InstanceSummary]}`, `InstanceView {id, name, instructions, lifecycle, status, gated_reason, version, capabilities, attachments, network_domains, budget: BudgetView, usage_history, audit: [AuditEvent], pending_actions}`, `ConnectionsView {connections, attachments}`. `InstanceSummary` shows name, lifecycle, derived status and the gate reason. `budget` is rendered as USD with six decimals from micro-USD. Audit is rendered from `AuditLog.list_for_instance`, which already holds only allow-listed fields.

Mutation UIs, each a server-rendered form that posts the `expected_version` and a CSRF token to the E11-2 operation and re-renders the committed instance or the structured denial (F3-S5, F3-S7). Ownership:

| UI | Ticket | Calls |
|---|---|---|
| Landing, sign-in, logout, workspace shell, wizard | E11-3 | `SessionAuthProvider`, `create_instance` |
| Chat | E11-4 | `ChatModelPort`, tools |
| Connections area: list, begin OAuth, revoke | E11-5 | `begin_oauth`, callback result, `revoke_connection` |
| Instance detail, activate, pause, resume, archive | E11-5 | `set_lifecycle` |
| Capability toggles, attach and detach connection | E11-5 | `set_capability`, `attach_connection`, `detach_connection` |
| Daily and monthly limit editing | E11-5 | `set_limits` |
| Owner `network.fetch` domain editing | E11-5 | `add_network_domain`, `remove_network_domain` |
| Resolve-gate button | E11-5 | `resolve_gate` |
| Simulated work request form (labelled simulated) | E11-5 | `POST /instances/{id}/work-requests` |
| Confirmation prompt for `gmail.send` and `reddit.post` | E11-5 | `create_confirmation` via `POST /pending-actions/{id}/confirm` |

The instance page states plainly that revocation does not undo actions already taken, that real provider adapters are not enabled, and that gated reasons stay until the owner resolves them.

### Production wiring (owner E11-5)

`backend/aicl/app.py` exposes `create_app(settings)`, the only application factory: it loads configuration, runs migrations, imports the price table, builds the production composition (real SQLite repositories, real `SessionAuthProvider`, real `WorkAuthorization`, real `CredentialBroker` and `SecretStore`, `BudgetPort`, audit log, and the reconciler) and registers every route. Only the leaf ports are fakes: `FakeProviderOAuth`, `FakeWorkExecutor`, `ScriptedChatModel`, `CaptureMagicLinkSender` (test mode only) and the controllable `Clock`. The browser journeys run this same factory through `python -m aicl.test_server` (below) with no in-test replacement of internal services; no route, service or gate is mocked, stubbed or bypassed for any journey. Wiring evidence (E11-5.AC1): one real-browser journey series proves, on that composition, the sign-in, wizard creation, chat creation producing an equivalent instance, activation, limits, capability and attachment (through the fake OAuth page), a simulated work request that is settled and visible in usage, an over-limit request that gates, a confirmation-requiring send that is denied, confirmed once, executed once and denied on replay, revocation that detaches and gates, another tenant's isolation, and the redacted audit history.

## Process topology

Landing and authentication pages are public; every other route resolves `AuthContext` through `SessionAuthProvider` and redirects (pages) or returns `unauthenticated` (tools and JSON routes) when absent. The authenticated workspace hosts wizard, chat, connections, list and detail routes. Wizard and chat call the one canonical `create_instance`; management pages call `InstanceOperations`; work and confirmation call `WorkAuthorization`. All in one process, one database; the only external edges are email delivery (`MagicLinkSender`) and the fake provider and executor. Pages never accept a tenant ID and never include a credential or secret.

## Configuration

Authoritative table: [architecture.md](../architecture.md#consolidated-configuration). Rows owned here: `AICL_SESSION_SECRET`, `AICL_SESSION_TTL_SECONDS`, `AICL_MAGIC_LINK_TTL_SECONDS`, `AICL_SMTP_HOST`, `AICL_SMTP_PORT`, `AICL_SMTP_USERNAME`, `AICL_SMTP_PASSWORD`, `AICL_SMTP_FROM`, `AICL_TEST_MODE`, `AICL_ENVIRONMENT`, `AICL_CHAT_MODEL_MODE`. Startup fails when `AICL_SESSION_SECRET` is missing or shorter than 32 bytes, and when magic-link delivery is not configured (`AICL_SMTP_HOST` unset) unless the test composition (`AICL_TEST_MODE=1` and `AICL_ENVIRONMENT=test`) is active. `AICL_TEST_MODE=1` with `AICL_ENVIRONMENT` other than `test`, or either value being anything unexpected, fails startup, so email capture cannot be enabled in production by one flag. UI code never accepts a tenant ID.

## Verification pointers

E11-3 proves F3-S1, F3-S2, F3-S8 and the wizard half of F3-S3 and F3-S5 with integration tests (token TTL, single use, hash storage, no-existence-leak equality, cookie flags, logout, CSRF, cross-tenant `not_found`) and one browser journey. E11-4 proves F3-S6 and the chat half of F3-S3 with unit tests of the state machine, tool allow-list and schema rejection plus a browser chat journey. E11-5 proves F3-S4, F3-S7 and F3-S9 and the wiring criterion with the production-wired browser journeys above.
