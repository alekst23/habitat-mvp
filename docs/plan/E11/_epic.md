# E11: AICL MVP — Configurable AI Control Layer

Project ID: 87329027  
Source issue: #11  
Epic issue: #11  
Epic branch: `ctx/epic-i11`

## Outcome and scope

A signed-in owner creates and manages configurable instances of predefined agent templates through one canonical creation model. The first-party creation surfaces are a web wizard, web-app tools, and built-in chat. “WebMCP” means web-app tools, not a public MCP API.

The MVP includes a public landing page; authenticated workspace; template catalog and configuration wizard; agent list; agent detail/status; built-in chat creation flow; and visible configuration/control history. Tenant identity derives from authentication and all mutation/validation fails closed.

## Control-policy MVP delta

Default instances begin with a name, free-form instructions, and enabled AICL capabilities. The AICL MVP also includes:

- per-instance inference and compute limits, enforced before use with fail-closed handling for missing or exhausted limits;
- owner-authorized Gmail and Reddit OAuth connections, stored outside agent context and injected only by the relevant AICL component; and
- outbound network policy with an allow-list as the baseline. Wildcard deny rules are not a substitute for an allow-list and are deferred unless a concrete use case requires them.

Limit units (integer micro-USD), connection scopes, consent/revocation behavior, the network-policy schema and the capability-to-domain mapping are specified in the feature technical documents under `docs/design/` (design specified, independent review pending).

## Exclusions

No PayPal, funding/billing capture, ads, external action execution, BYOA sandboxing, arbitrary user code, direct credentials, provider enablement, deployment, live spend, or public/external MCP API.

## Tickets and dependencies

| Ticket | Issue | Dependencies | State |
|---|---|---|---|
| E11-1 AICL domain and control foundation | #12 | — | design specified; review pending |
| E11-2 Canonical creation service and web-app tools | #13 | E11-1 | design specified; review pending |
| E11-3 Authenticated workspace and agent-creation wizard | #14 | E11-1, E11-2 | design specified; review pending |
| E11-4 Built-in chat agent creation surface | #15 | E11-2 | design specified; review pending |
| E11-5 AICL web pages, instance management, and cross-surface proof | #16 | E11-3, E11-4 | design specified; review pending |

## Waves

1. E11-1
2. E11-2
3. E11-3 and E11-4
4. E11-5

## Planning decisions

- Agent means a configurable instance of a predefined template, not a BYOA sandbox.
- All creation surfaces invoke the same canonical service.
- Layout scope includes landing, workspace, create wizard, agent list, agent detail/status, and built-in chat.
- The previous E2/PayPal direction is historical and remains unclosed for traceability.

## Design progress

Status: design specified (a review candidate, not Design complete). Repair cycle 1 of 3 (mode=design-repair) addressed independent review findings DR-1 to DR-12 and DR-15 from issue #11 note 4008793549; DR-13 (verify/browser command adapters) and DR-14 (provider enablement) remain later gates and are not actioned here. Execution status in `state.json` is unchanged (all tickets pending, `design_status` pending).

Ownership after repair (dependencies and waves unchanged): E11-1 owns `AuthContext`, instances, `BudgetPort`, `PriceTable`, `AuditEvent` and `ActionConfirmation`; E11-2 owns the canonical creation service, `CreateInstanceRequest`/`CreateInstanceResult`, the first-party web-app tool schemas, instance operations, connections, OAuth, credential broker, network policy and the `WorkAuthorization` dispatch gate; E11-3 owns sign-in, workspace and the wizard; E11-4 owns chat; E11-5 owns read projections, the management UIs, the production wiring and the cross-surface proof. Features: aicl-control-plane, connection-network-policy, aicl-experience under `docs/design/`. History: the earlier [Habitat foundation design](../../design/habitat-foundation/spec.md) is not the MVP source of truth.

Planning published. Confirmed: Default is the initial generic template; users set name, free-form instructions and enabled AICL capabilities. Control-policy delta confirmed: per-instance inference/compute limits, owner-authorized Gmail/Reddit connections and outbound allow-list policy.

**D11-1 — Default capability controls (user, chat, 2026-10-13):** Default starts with granular capabilities `inference`, `gmail.read`, `gmail.send`, `reddit.read`, `reddit.post`, and `network.fetch`, all disabled until enabled by the owner. `gmail.send` and `reddit.post` additionally require a per-action owner confirmation; enabled capability and available limits alone do not authorize those outbound writes. Affected tickets: E11-1, E11-2, E11-3, E11-4 and E11-5.

**D11-2 — AICL limit periods (user, chat, 2026-10-13):** Every Default instance has both daily and monthly inference and compute caps. A request is denied if it would exceed either applicable cap; missing, invalid, or unavailable limit state also denies. Affected tickets: E11-1, E11-2, E11-3, E11-4 and E11-5.

**D11-3 — Usage and budget presentation (user, chat, 2026-10-13):** AICL records usage in each base metric available (initially inference tokens and compute minutes). A versioned cost function converts that measured usage to USD for owner-facing budget display and daily/monthly limit evaluation. This is a control budget, not PayPal funding, billing capture, or a payment rail. Affected tickets: E11-1, E11-2, E11-3, E11-4 and E11-5.

**D11-4 — Price table source (user, chat, 2026-10-13):** An operator-managed, versioned internal price table with effective dates supplies the cost function. Every usage record stores the applied price-table version so historical USD totals remain explainable after prices change. Affected tickets: E11-1, E11-3 and E11-5.

**D11-5 — Default budgets (user, chat, 2026-10-13):** Default instances start with $0 daily and $0 monthly inference and compute budgets. No inference or compute proceeds until the owner explicitly configures a positive applicable limit. Affected tickets: E11-1, E11-3, E11-4 and E11-5.

**D11-6 — Connection consent model (user, chat, 2026-10-13):** Owners create Gmail and Reddit connections in a dedicated Connections area, then explicitly attach a connection to an instance capability. The creation wizard and built-in chat may guide this process but never receive OAuth credentials. Connection credentials remain outside agent context; revocation detaches the connection and blocks its later use. Affected tickets: E11-2, E11-3, E11-4 and E11-5.

**D11-7 — Network policy model (user, chat, 2026-10-13):** Each enabled capability uses a fixed system allow-list for its required endpoints. `network.fetch` may additionally use owner-added exact HTTPS domains. All other destinations are denied; wildcard deny rules are not used as a substitute for this allow-list. Affected tickets: E11-1, E11-2, E11-3, E11-4 and E11-5.

**D11-8 — Instance lifecycle and gating (user, chat, 2026-10-13; revised):** Instances have `draft`, `active`, `paused`, and `archived` lifecycle states; `paused` is owner-initiated. `gated` is a visible operational status, not a lifecycle state: an active instance is gated when a control prevents work, including exhausted daily/monthly budget, revoked required connection, disabled required capability, or denied network destination. It returns to active eligibility only after the owner resolves that control. Affected tickets: E11-1, E11-3, E11-4 and E11-5.

**D11-9 — Authentication entry point (user, chat, 2026-10-13):** The MVP uses email magic-link sign-in. Authenticated session context derives tenant and owner identity for all AICL reads and mutations; client-supplied tenant identity is ignored. Affected tickets: E11-1, E11-2, E11-3, E11-4 and E11-5.

**D11-10 — First-run page flow (user, chat, 2026-10-13):** The landing page explains AICL control and leads to **Create your first agent**. After sign-in, an empty workspace offers **Create with wizard** and **Create with chat**. Both paths create the same canonical Default instance. Affected tickets: E11-3, E11-4 and E11-5.

**D11-11 — Budget reservation and settlement (user, chat, 2026-10-13):** Before inference or compute begins, AICL reserves the maximum estimated USD against both applicable daily and monthly budgets. It settles against measured usage after completion. Unknown outcomes retain their reservation until reconciliation; failure to price, reserve, validate, or reconcile denies further work. Affected tickets: E11-1, E11-2, E11-4 and E11-5.

**D11-12 — Connection revocation and audit (user, chat, 2026-10-13):** Revocation immediately detaches a connection from every instance, blocks new use, invalidates stored credentials, and appends an audit event. Historical activity remains visible in redacted form. Affected tickets: E11-1, E11-2, E11-3, E11-4 and E11-5.

**D11-13 — Connection sharing (user, chat, 2026-10-13):** One owner-controlled Gmail or Reddit connection may be explicitly attached to multiple Default instances of that owner. Attachment is per instance/capability; revocation detaches every attachment. Affected tickets: E11-1, E11-2, E11-3, E11-4 and E11-5.

Design specified: scenarios, contracts, ticket mappings and acceptance manifest are saved and were repaired once after independent review. A fresh independent same-SHA semantic review is pending before implementation; the later access (commands) and enablement (real providers) gates stay open.
