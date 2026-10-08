---
name: ctx-epic-review
description: Independently assess whether integrated tickets deliver the complete feature and are wired into the running system.
---

## Design readiness mode

When the coordinator explicitly delegates mode=design-readiness before ticket claims,
read docs/development/design-readiness.md and the pinned spec, technical contracts,
ticket designs, design.json and acceptance manifest. Apply the five perspectives
below to the proposed design: producer/consumer agreement, coverage, process channels,
configuration, failure/recovery and wiring ownership. Inspect the structural report;
do not treat it as semantic proof. Return blocked for material findings or unresolved
decisions in the requested scope, ready for a satisfactory design review only.
Publish a source-issue note with mode, scope, exact design SHA, reviewer identity,
findings and verdict; read it back. This is not implementation evidence, a ticket
review, a merge approval or the final epic review. Do not require unbuilt application
tests for design review. Normal integrated-epic mode below remains unchanged.

## Integrated epic mode

Read the feature spec, epic ACs, all tickets and full changed files at the integrated
epic SHA. Also inspect entry points/configuration where missing wiring would appear.
Use read/comment tools only. Ticket reviews do not replace this review.

Preserve the original five perspectives without requiring five separate agents:

- Intent and conceptual fit: all feature scenarios and non-goals, assumptions and scope.
- Integration/wiring: routes registered, adapters constructed, UI connected, required
  configuration documented/applied, prerequisites present and integration work complete.
- Orchestration: what starts the feature, lifecycle, error/retry handling and observability.
- Architecture across tickets: coherent contracts, dependency direction and no orphan code.
- Operational quality: idempotency, realistic failure behavior, secrets and bounded work.

Require the complete epic acceptance manifest and integration/browser evidence at
the epic SHA. Trace every criterion; do not infer end-to-end success from isolated
unit tests. Reuse a small number of meaningful integration journeys and do not add
tests solely because another review layer exists.

Report AC/scenario verdicts, wiring findings, current evidence and readiness. Missing
required evidence or unfinished tickets blocks epic closure. Record a separate
epic-review report even if the same model performed ticket review.
