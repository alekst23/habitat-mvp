# AICL shared architecture context

AICL manages configurable instances of predefined templates. Default is the initial template. It receives no direct credentials and cannot bypass the AICL control plane.

## Shared boundaries

- Authenticated server sessions derive owner and tenant identity; client tenant fields are ignored.
- A canonical instance-creation service is used by the wizard, first-party web-app tools, and built-in chat.
- Connections and encrypted credentials remain outside agent context. A capability may use a connection only after explicit owner attachment.
- The budget controller reserves estimated USD before inference or compute, settles measured token/minute usage using the applied versioned price table, and fails closed.
- Network authorization uses capability-owned fixed allow-lists plus owner-added exact HTTPS domains only for `network.fetch`.

## Non-goals

No PayPal or payment capture, public MCP API, BYOA sandbox, arbitrary user code, direct provider credentials, provider enablement, deployment, or live spend.
