# AICL control plane

## Intent

A signed-in owner configures a Default template instance without giving it direct credentials or authority outside AICL.

## Scenarios

**F1-S1:** Given an authenticated owner, when they create Default with a name and free-form instructions, then AICL creates a tenant-owned draft instance.

**F1-S2:** Given a draft instance, when the owner enables a listed capability, then only that capability becomes eligible for evaluation.

**F1-S3:** Given an active instance, when inference or compute is requested, then AICL reserves the maximum estimated USD against daily and monthly limits before work begins. All four limits (inference and compute, daily and monthly) must be positive before any work is dispatched: a zero limit is exhausted even for a zero-cost category (fail closed).

**F1-S4:** Given measured token/minute usage, when work completes, then AICL settles usage with the applied versioned price table and exposes USD totals.

**F1-S5:** Given an exhausted, missing, invalid, or unavailable limit, when work is requested, then AICL denies it and reports `gated`. An instance whose four limits are not all positive therefore dispatches no work.

**F1-S6:** Given an active instance, when the owner pauses or archives it, then new work is denied and its history remains visible.

**F1-S7:** Given an instance, when the owner requests a lifecycle change, then only the transitions in the lifecycle table succeed (`draft`→`active`, `active`↔`paused`, any non-archived state→`archived`); every other request is refused as `invalid_transition` and `archived` is terminal.
**F1-S8:** Given any request, when AICL resolves identity, then owner and tenant come only from the authenticated `AuthContext`, a client-supplied `tenant_id` or `owner_id` is ignored, and another tenant's instance, connection or history is indistinguishable from one that does not exist (`not_found`).
**F1-S9:** Given an active instance, when work is denied because the daily or monthly budget is exhausted, a required connection is revoked, a required capability is disabled or a network destination is denied because its host is not in the owner's allow-list (`host_not_allowed` for `network.fetch`, the only owner-resolvable network denial), then `gated_reason` is recorded and persists, including across a daily or monthly window rollover, until the owner resolves that control and the system re-checks it as now permitting work, either through the committed mutation that fixes the control or through `resolve_gate`; `resolve_gate` re-evaluates the control for every reason and, while the control still denies, is refused as `denied` with `gate_unresolved` and the gate stays; an owner-initiated pause is `paused`, never `gated`. A structurally invalid destination (scheme, port, userinfo, address, redirect, method or path) denies that request, is audited with its rule and does not gate the instance, because no owner control can fix it.
**F1-S10:** Given two concurrent reservations that together exceed the remaining daily or monthly limit, when both arrive, then exactly one hold is created and the other is denied; a repeated reservation with the same idempotency key returns the original hold.
**F1-S11:** Given a hold, when measured usage is settled, a settlement is repeated, measured usage exceeds the hold, the outcome is unknown, or an unknown outcome is later reconciled, then the hold, usage record and remaining budget follow the BudgetPort rules (actual measured cost is recorded, unknown holds keep their full reserved maximum until reconciliation, repeats are idempotent).
**F1-S12:** Given the price table, when it is loaded at startup or used for a reservation, then an invalid, mutated or missing table fails startup, an unavailable price at use denies work as `price_unavailable`, and every hold and usage record stores the applied table version.
**F1-S13:** Given any state change or denial, when it commits, then an append-only `AuditEvent` containing only allow-listed redacted fields is stored in order with the change, and the owner-scoped reader returns it without secrets, tokens, instructions or message bodies.
**F1-S14:** Given an authenticated owner, when they or a first-party tool create Default with the same idempotency key twice, then exactly one draft instance exists and the second call returns the original `CreateInstanceResult`; the same key with a different payload is a `conflict`, and an unknown template, out-of-bounds name or instructions, or unknown capability is `validation_failed` with no instance created.
**F1-S15:** Given an owner-owned instance, when the owner activates it, enables or disables a capability, sets daily and monthly limits, or adds or removes an owner `network.fetch` domain with a stale `expected_version`, then the change is refused as `conflict` without effect; with the current version it commits once, bumps `version`, appends an audit event and returns the committed instance.
**F1-S16:** Given an enabled `gmail.send` or `reddit.post` capability with an attached connection and sufficient budget, when work arrives without a valid owner confirmation, or with a confirmation that is expired, already used, or bound to a different payload, then the single dispatch gate denies it before any dispatch; a confirmation created through the owner-authenticated UI request authorizes exactly one dispatch of exactly that payload.

## Failures and non-goals

Unknown prices, disabled capabilities, and uncertain outcomes fail closed; uncertain outcomes retain reservations until reconciliation. Tests and browser journeys run against deterministic fake ports; real inference, compute, provider and chat-model adapters are disabled by default and rejected at startup. Magic-link email through the operator-configured SMTP server is the one real outbound edge of the application; it is distinct from Gmail and is not a rejected adapter. This feature has no payment rail, provider enablement, BYOA runtime, or arbitrary code execution.
