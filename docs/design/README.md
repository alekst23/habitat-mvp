# Design index

## AICL development standard

- [Brief project ethos](../../AGENTS.md#aicl-ethos): required context for application development.
- [Public research within AICL](aicl-public-research.md): local public-research boundary, web-access levels, disclosure separation, and remaining production limitations.

## Durable general-agent execution

- [Durable execution plan](durable-agent-execution.md): runtime core and opt-in
  local chat integration implemented October 26, 2026, with run/plan/step state,
  saved evidence, owner conversations, worker recovery and shared accounting.
  Includes live structured decisions, approved-domain page reads, the scripted
  proof, local testing instructions and remaining tool/worker integration.
  Current application behavior remains in [General agents](../general-agents.md).
- [Agent data and trust](agent-data-trust.md): proposed confidentiality, access,
  processing/disclosure, encrypted content, worker identity and retention contracts,
  including confirmed gaps in the current implementation.
- [Encrypted agent storage implementation plan](../plan/encrypted-agent-storage.md):
  deferred to the production release; four packages covering the content store,
  active data paths and a fresh protected database. The initial durable-session
  proof uses a replaceable nonproduction adapter; current data is disposable. See the
  [reset/recreate procedure](../development/encrypted-content-reset.md).

## Owner workflow implementation plan

- [Owner workflow change plan](owner-workflow-change-plan.md): current implementation
  fit, gaps and an ordered mock-only MVP plan for configured deliverable criteria,
  scheduled work, purchase continuation, AG Grid Audit and versioned output review.
  Real execution, live providers and deployment remain separate work.

## PayPal funding and agent purchases

- [Funding specification](paypal-funding/spec.md): captured PayPal top-ups, prepaid
  service credit, agent allocation, and metered inference/compute.
- [Technical contracts](paypal-funding/technical.md): payment verification, ledger,
  atomic AICL reservations, provider bounds, recovery, UI, and acceptance cases.
- [Agent purchase specification](agent-purchases/spec.md): select an item, obtain
  exact owner approval and PayPal buyer consent, then complete an integrated seller
  purchase and use the delivered resource.
- [Purchase broker contracts](agent-purchases/technical.md): controlled agent tools,
  policy holds, merchant adapters, single-use capture claims, receipt/delivery
  recovery, and separation from inference funding.

This is the proposed PayPal hackathon extension, not implemented E11 behavior.
It supersedes the per-job authorization/capture demo proposal with captured
top-ups funding agent operations. The E11 records below retain their original scope.
Both funding and owner-approved purchases are required for the revised demo.

## AICL MVP (E11)

- [AICL control plane](aicl-control-plane/spec.md): configurable Default instances, budgets, capabilities, lifecycle, audit, confirmation and the canonical creation service ([technical](aicl-control-plane/technical.md)).
- [Connection and network policy](connection-network-policy/spec.md): owner connections, OAuth, credential broker, capability attachment, outbound authorization and the dispatch gate ([technical](connection-network-policy/technical.md)).
- [AICL experience](aicl-experience/spec.md): landing, sign-in, workspace, wizard, chat, connections and instance management views ([technical](aicl-experience/technical.md)).
- [Shared architecture](architecture.md): boundaries, application stack and layout, test layers, command argv and the consolidated configuration table.

Implementation status: all five E11 tickets are integrated into `ctx/epic-i11`, with their application integration evidence reconciled. The reviewed ticket candidate passed application, browser, acceptance, security, packaging and configuration-validation CI. Final assembled-epic verification and independent review are tracked on [MR !45](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/45); see [completion evidence](../plan/E11/completion.md). Real providers and deployment remain excluded. The original design repair history is preserved.

The follow-on [E11-6 UI refinement](../plan/E11/E11-6.md) was reviewed at
`419e77b` on `codex/e11-ui-polish`. It appends responsive-presentation and asynchronous-feedback
scenarios to the experience feature while preserving the completed five-ticket
baseline. It is included in the stable-main integration; current acceptance uses
the expanded six-criterion manifest. See the [baseline and next-release backlog](../paypal-mvp-backlog.md).

## History

- [Habitat foundation](habitat-foundation/spec.md): the earlier Habitat E2 design (PayPal-funded marketing agent). It is historical and is not the MVP source of truth; it is retained for traceability.
