# Design index

## AICL MVP (E11)

- [AICL control plane](aicl-control-plane/spec.md): configurable Default instances, budgets, capabilities, lifecycle, audit, confirmation and the canonical creation service ([technical](aicl-control-plane/technical.md)).
- [Connection and network policy](connection-network-policy/spec.md): owner connections, OAuth, credential broker, capability attachment, outbound authorization and the dispatch gate ([technical](connection-network-policy/technical.md)).
- [AICL experience](aicl-experience/spec.md): landing, sign-in, workspace, wizard, chat, connections and instance management views ([technical](aicl-experience/technical.md)).
- [Shared architecture](architecture.md): boundaries, application stack and layout, test layers, command argv and the consolidated configuration table.

Status: E11 design is **specified** on `ctx/epic-i11` (a review candidate, not Design complete). Independent design reviews found issues that were repaired in cycles 1 and 2 of 3; a fresh independent review is pending. Provider enablement and the verify/browser command adapters are later gates and are not enabled.

## History

- [Habitat foundation](habitat-foundation/spec.md): the earlier Habitat E2 design (PayPal-funded marketing agent). It is historical and is not the MVP source of truth; it is retained for traceability.
