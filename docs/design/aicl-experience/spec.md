# AICL experience

## Intent

Owners understand and control Default instances through a landing page, authenticated workspace, wizard, built-in chat, connection area, and instance views.

## Scenarios

**F3-S1:** Given a visitor, when they open the landing page, then they see AICL controls and a Create your first agent action.

**F3-S2:** Given a visitor following that action, when they complete email magic-link sign-in, then the server derives their owner and tenant session.

**F3-S3:** Given an empty workspace, when an owner chooses wizard or chat, then both guide creation of the same Default instance model.

**F3-S4:** Given an instance, when the owner views its detail page, then they see lifecycle, `gated` reason if any, instructions, enabled capabilities, budgets, attachments, and redacted audit/usage history.

**F3-S5:** Given an owner, when they change budgets, capabilities, connections, or lifecycle, then the UI shows the committed result or a truthful denial.
**F3-S6:** Given the built-in chat, when an owner describes an agent, then a deterministic slot-filling engine calls only the listed first-party tools with no tenant, owner, credential or confirmation arguments, treats instance text as untrusted data, never creates an `ActionConfirmation`, recovers from validation errors by asking for the corrected field, and consumes no instance budget.
**F3-S7:** Given an owner viewing the Connections area or an instance detail page, when they connect or revoke a connection, attach or detach it, toggle a capability, edit daily and monthly limits, pause, archive or activate the instance, edit owner `network.fetch` domains, or confirm a `gmail.send` or `reddit.post` action in the confirmation prompt, then the UI submits one authenticated request per action with `expected_version` and shows the committed result or the truthful structured denial.
**F3-S8:** Given a visitor requesting a magic link, when they submit an email address, open the link, reuse or let it expire, or sign out, then the response never reveals whether the account exists, a link works once within its TTL, the session cookie is `HttpOnly`, `Secure` outside test mode, `SameSite=Lax` and expires, and logout invalidates it server-side.
**F3-S9:** Given the production-wired composition, when the browser journeys run, then sign-in, wizard creation, chat creation, owner mutations, simulated work, gating, revocation and audit history all pass through the same HTTP entry points and gate that production uses, with fake ports only at the provider, executor, chat model and email edges.

## Failures and non-goals

Chat and wizard never receive OAuth credentials or bypass server validation. Another tenant’s instances, connections, usage, or history are never shown.
