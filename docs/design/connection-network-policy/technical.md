# Connection and network policy technical design

## Contracts

E11-2 owns `Connection {id, owner_id, provider, status, secret_ref}`, `ConnectionAttachment {connection_id, instance_id, capability}`, and `NetworkPolicy {instance_id, capability, exact_https_domains}`. Secrets are encrypted behind `secret_ref`; neither tools nor chat receive their value.

`attach_connection` verifies same-owner attachment and capability compatibility. `revoke_connection` invalidates the secret reference, removes every attachment, and appends a redacted audit event. `authorize_destination` permits only a capability’s fixed endpoints or an exact owner-added HTTPS `network.fetch` domain; all other destinations deny.

## Process topology

Connections UI and creation tools call the connection policy service with authenticated owner context. The execution boundary requests a short-lived provider credential or network authorization from that service; it never reads stored OAuth material directly.

## Configuration

Provider scopes and fixed endpoints are allow-listed configuration. Unknown provider, scope, endpoint, wildcard pattern, or unavailable secret backend denies startup or use.
