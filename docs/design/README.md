# Design index

## AICL MVP (E11)

- [AICL control plane](aicl-control-plane/spec.md): configurable Default instances, budgets, capabilities, lifecycle, audit, confirmation and the canonical creation service ([technical](aicl-control-plane/technical.md)).
- [Connection and network policy](connection-network-policy/spec.md): owner connections, OAuth, credential broker, capability attachment, outbound authorization and the dispatch gate ([technical](connection-network-policy/technical.md)).
- [AICL experience](aicl-experience/spec.md): landing, sign-in, workspace, wizard, chat, connections and instance management views ([technical](aicl-experience/technical.md)).
- [Shared architecture](architecture.md): boundaries, application stack and layout, test layers, command argv and the consolidated configuration table.

Implementation status: all five E11 tickets are integrated into `ctx/epic-i11`, with their application integration evidence reconciled. The reviewed ticket candidate passed application, browser, acceptance, security, packaging and configuration-validation CI. Final assembled-epic verification and independent review are tracked on [MR !45](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/45); see [completion evidence](../plan/E11/completion.md). Real providers and deployment remain excluded. The original design repair history is preserved.

The follow-on [E11-6 UI refinement](../plan/E11/E11-6.md) is in progress on
`codex/e11-ui-polish`. It appends responsive-presentation and asynchronous-feedback
scenarios to the experience feature while preserving the completed five-ticket
baseline. Its acceptance and review must use the new candidate and expanded
manifest; it is not yet integrated.

## History

- [Habitat foundation](habitat-foundation/spec.md): the earlier Habitat E2 design (PayPal-funded marketing agent). It is historical and is not the MVP source of truth; it is retained for traceability.
