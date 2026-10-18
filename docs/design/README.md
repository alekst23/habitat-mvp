# Design index

## AICL MVP (E11)

- [AICL control plane](aicl-control-plane/spec.md): configurable Default instances, budgets, capabilities, lifecycle, audit, confirmation and the canonical creation service ([technical](aicl-control-plane/technical.md)).
- [Connection and network policy](connection-network-policy/spec.md): owner connections, OAuth, credential broker, capability attachment, outbound authorization and the dispatch gate ([technical](connection-network-policy/technical.md)).
- [AICL experience](aicl-experience/spec.md): landing, sign-in, workspace, wizard, chat, connections and instance management views ([technical](aicl-experience/technical.md)).
- [Shared architecture](architecture.md): boundaries, application stack and layout, test layers, command argv and the consolidated configuration table.

Implementation status: E11-1 through E11-4 are integrated into `ctx/epic-i11`; E11-5 has a reviewed implementation candidate awaiting integration. Backend, browser and ticket acceptance adapters now exist. Final assembled-epic checks and review remain pending; see the [completion evidence](../plan/E11/completion.md). Real provider enablement remains excluded. The design repair cycles recorded in the epic are preserved historical evidence, not the current implementation status.

## History

- [Habitat foundation](habitat-foundation/spec.md): the earlier Habitat E2 design (PayPal-funded marketing agent). It is historical and is not the MVP source of truth; it is retained for traceability.
