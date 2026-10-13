# E11: AICL MVP — Configurable AI Control Layer

Project ID: 87329027  
Source issue: #10  
Epic issue: #11  
Epic branch: `ctx/epic-i11`

## Outcome and scope

A signed-in owner creates and manages configurable instances of predefined agent templates through one canonical creation model. The first-party creation surfaces are a web wizard, web-app tools, and built-in chat. “WebMCP” means web-app tools, not a public MCP API.

The MVP includes a public landing page; authenticated workspace; template catalog and configuration wizard; agent list; agent detail/status; built-in chat creation flow; and visible configuration/control history. Tenant identity derives from authentication and all mutation/validation fails closed.

## Exclusions

No PayPal, funding, billing, ads, external action execution, BYOA sandboxing, arbitrary user code, direct credentials, provider enablement, deployment, live spend, or public/external MCP API.

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

Planning published. Design pending an interview covering template catalog, configuration fields, lifecycle/status vocabulary, authentication entry point, and page-level behavior.
