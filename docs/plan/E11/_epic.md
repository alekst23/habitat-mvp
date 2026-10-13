# E11: AICL MVP — Configurable AI Control Layer

Project ID: 87329027  
Source issue: #10  
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

Detailed limit units, connection scopes, consent/revocation behavior, network-policy schema, and capability-to-domain mapping are Design pending.

## Exclusions

No PayPal, funding/billing capture, ads, external action execution, BYOA sandboxing, arbitrary user code, direct credentials, provider enablement, deployment, live spend, or public/external MCP API.

## Tickets and dependencies

| Ticket | Issue | Dependencies | State |
|---|---|---|---|
| E11-1 AICL domain and control foundation | #12 | — | design pending |
| E11-2 Canonical creation service and web-app tools | #13 | E11-1 | design pending |
| E11-3 Authenticated workspace and agent-creation wizard | #14 | E11-1, E11-2 | design pending |
| E11-4 Built-in chat agent creation surface | #15 | E11-2 | design pending |
| E11-5 AICL web pages, instance management, and cross-surface proof | #16 | E11-3, E11-4 | design pending |

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

Planning published. Confirmed: Default is the initial generic template; users set name, free-form instructions and enabled AICL capabilities. Control-policy delta confirmed: per-instance inference/compute limits, owner-authorized Gmail/Reddit connections and outbound allow-list policy.

**D11-1 — Default capability controls (user, chat, 2026-10-13):** Default starts with granular capabilities `inference`, `gmail.read`, `gmail.send`, `reddit.read`, `reddit.post`, and `network.fetch`, all disabled until enabled by the owner. `gmail.send` and `reddit.post` additionally require a per-action owner confirmation; enabled capability and available limits alone do not authorize those outbound writes. Affected tickets: E11-1, E11-2, E11-3, E11-4 and E11-5.

**D11-2 — AICL limit periods (user, chat, 2026-10-13):** Every Default instance has both daily and monthly inference and compute caps. A request is denied if it would exceed either applicable cap; missing, invalid, or unavailable limit state also denies. Affected tickets: E11-1, E11-2, E11-3, E11-4 and E11-5.

**D11-3 — Usage and budget presentation (user, chat, 2026-10-13):** AICL records usage in each base metric available (initially inference tokens and compute minutes). A versioned cost function converts that measured usage to USD for owner-facing budget display and daily/monthly limit evaluation. This is a control budget, not PayPal funding, billing capture, or a payment rail. Affected tickets: E11-1, E11-2, E11-3, E11-4 and E11-5.

**D11-4 — Price table source (user, chat, 2026-10-13):** An operator-managed, versioned internal price table with effective dates supplies the cost function. Every usage record stores the applied price-table version so historical USD totals remain explainable after prices change. Affected tickets: E11-1, E11-3 and E11-5.

**D11-5 — Default budgets (user, chat, 2026-10-13):** Default instances start with $0 daily and $0 monthly inference and compute budgets. No inference or compute proceeds until the owner explicitly configures a positive applicable limit. Affected tickets: E11-1, E11-3, E11-4 and E11-5.

**D11-6 — Connection consent model (user, chat, 2026-10-13):** Owners create Gmail and Reddit connections in a dedicated Connections area, then explicitly attach a connection to an instance capability. The creation wizard and built-in chat may guide this process but never receive OAuth credentials. Connection credentials remain outside agent context; revocation detaches the connection and blocks its later use. Affected tickets: E11-2, E11-3, E11-4 and E11-5.

**D11-7 — Network policy model (user, chat, 2026-10-13):** Each enabled capability uses a fixed system allow-list for its required endpoints. `network.fetch` may additionally use owner-added exact HTTPS domains. All other destinations are denied; wildcard deny rules are not used as a substitute for this allow-list. Affected tickets: E11-1, E11-2, E11-3, E11-4 and E11-5.

**D11-8 — Instance lifecycle (user, chat, 2026-10-13):** Instances have `draft`, `active`, `paused`, and `archived` lifecycle states. Only active instances are eligible to use enabled capabilities. A zero budget, unavailable connection, or denied network destination is a visible blocked condition, not a lifecycle state. Affected tickets: E11-1, E11-3, E11-4 and E11-5.

Design pending an interview covering reservation/reconciliation behavior, detailed connection revocation/audit behavior, authentication entry point, and page-level behavior.
