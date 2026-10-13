# Connection and network policy

## Intent

Owners control reusable Gmail and Reddit connections and AICL-controlled outbound access without exposing credentials to Default instances.

## Scenarios

**F2-S1:** Given an authenticated owner, when they create a Gmail or Reddit connection in Connections, then credentials remain outside agent context.

**F2-S2:** Given an owner connection, when it is explicitly attached to an instance capability, then only that owner’s instance may request its use.

**F2-S3:** Given a revoked connection, when an attached capability requests it, then AICL denies use, detaches all attachments, invalidates credentials, and appends a redacted audit event.

**F2-S4:** Given a capability endpoint or an owner-added exact HTTPS domain for `network.fetch`, when network access is requested, then AICL permits only that allow-listed destination.

**F2-S5:** Given any other destination, wildcard pattern, unknown capability, or missing policy, when network access is requested, then AICL denies it.

## Failures and non-goals

Connections may be shared only across instances owned by the same owner, through explicit per-instance/capability attachments. No public MCP API or direct credential access exists.
