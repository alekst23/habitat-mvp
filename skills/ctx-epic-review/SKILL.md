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
do not treat it as semantic proof. Return blocked for material design findings or
open design-stage decisions in scope, ready for a satisfactory design review only.
Inspect later-gate classification and safeguards: unknown behavior cannot be hidden
as enablement. Report legitimate later execution/enablement gates separately; they
are not design defects. Neither human signoff nor a green pipeline replaces review.
Publish a source-issue note with mode, scope, exact design SHA, reviewer identity,
findings and verdict; read it back. This is not implementation evidence, a ticket
review, a merge approval or the final epic review. Do not require unbuilt application
tests for design review. Normal integrated-epic mode below remains unchanged.

## Historical evidence mode

For mode=historical-evidence, independently inspect the named historically merged
ticket, original ACs, exact source/integration SHAs, actual MR/ancestry, original CI
and retained artifacts. Use current evidence only for what it actually proves;
do not retroactively attribute current-SHA results to the old commit. Changed ACs
need fresh verification. Publish/read back a source-issue report with original
identity, reviewer, criterion findings, actual evidence URLs and missing items.
Return ready only when all required historical integration evidence is verified;
otherwise blocked with the precise missing evidence and next actor/action.
Do not edit state, fabricate receipts, reopen the issue or redo merged implementation.
The coordinator alone reconciles state after independently verifying this report.
This preflight report is not a current ticket/epic completion receipt or merge approval.

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

In version-2 integrated-epic mode, bind verification_url to the saved full-epic
verification at this SHA. Publish actionable scoped defects as structured findings
with blocker_kind=defect, per docs/development/single-shot-development.md. The
supervisor may repair the assembled epic and return after docs and fresh full-epic
checks. Recheck the findings independently; never reuse a stale pass. This repair
contract does not apply to design-readiness mode or unresolved product decisions.
