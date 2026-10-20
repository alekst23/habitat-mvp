# Connection and network policy

## Intent

Owners control reusable Gmail and Reddit connections and AICL-controlled outbound access without exposing credentials to Default instances.

## Scenarios

**F2-S1:** Given an authenticated owner, when they create a Gmail or Reddit connection in Connections, then credentials remain outside agent context.

**F2-S2:** Given an owner connection, when it is explicitly attached to an instance capability, then only that owner’s instance may request its use.

**F2-S3:** Given an owner connection with attachments, when the owner revokes it, then AICL immediately detaches it from every instance, blocks new use, invalidates the stored credentials, appends a redacted audit event, and records `gated_reason=connection_revoked` on any active instance that required it; historical activity stays visible in redacted form. If the provider-side revoke call fails, local detach and credential invalidation still commit, the connection records `provider_revoke_status=failed`, and the owner is told to remove access in the provider's own account settings; there is no later retry because the credential is already destroyed.
**F2-S4:** Given a capability endpoint or an owner-added exact HTTPS domain for `network.fetch`, when network access is requested, then AICL permits only that allow-listed destination.

**F2-S5:** Given any other destination, wildcard pattern, unknown capability, or missing policy, when network access is requested, then AICL denies it.
**F2-S6:** Given a revoked or detached connection, when an attached capability later requests its use, then the dispatch gate denies the request with `connection_unavailable` before any credential is read and the instance reports `gated`.
**F2-S7:** Given an owner starting a Gmail or Reddit OAuth connection, when the callback returns, then AICL accepts it only for the same authenticated owner session with a matching single-use `state`, a valid PKCE verifier and the exact scopes of the capabilities requested; any mismatch, replay, expiry, provider error or missing scope creates no connection.
**F2-S8:** Given an owner-added `network.fetch` domain, when it is added or when any request or redirect hop is authorized, then only a lowercase exact DNS host over `https` on port 443 without userinfo, IP literals, private, loopback, link-local or metadata addresses is accepted, each redirect hop is re-authorized, and every other form is rejected.
**F2-S9:** Given work requested for an instance, when the dispatch gate runs, then it checks identity, instance, lifecycle, capability, confirmation, connection, network destination and budget in that fixed order, denies at the first failure, reserves budget only after every other check passes, and dispatches only through the work executor port.
**F2-S10:** Given an authorized dispatch that needs a provider credential, when the credential broker injects it, then the secret is decrypted and applied inside the broker's outbound call only, and never appears in a tool argument, chat message, agent context, executor request, log, audit event or API response.
**F2-S11:** Given a configuration that selects a real provider adapter, real inference or real compute without a recorded human-approved enablement, when the application starts, then startup fails; the default composition uses only the fake provider, fake executor and fake chat model ports and makes no live call.

## Failures and non-goals

Connections may be shared only across instances owned by the same owner, through explicit per-instance/capability attachments. No public MCP API or direct credential access exists.
