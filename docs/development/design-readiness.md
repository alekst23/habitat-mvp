# CTX design handoff requirements

Planning saves scope and tickets. Design turns that scope into specifications that
another developer can implement without inventing product behavior. Development
prepares typed contracts, writes meaningful failing tests, implements and reviews.
Saving a document proves persistence, not design completeness.

## Artifacts and responsibilities

| Artifact | Required content | Owner |
|---|---|---|
| docs/design/README.md | Concept-named feature index; retain superseded design history | Design |
| Feature spec.md | Intent, prerequisites, feature behavior, stable Given/When/Then scenarios, failures, non-goals, decisions | Design |
| Feature technical.md | Typed contracts, producer/consumer ownership, process topology, channels, transactions, failure/recovery behavior, configuration and source locations | Design |
| Ticket Markdown | Preserved ACs, solution approach, contracts, dependencies, verification and execution/review/closure records | Planning scope; Design detail |
| acceptance.json | Every scenario assigned to stable ticket ACs with test/browser/inspection methods | Design |
| design.json | Feature paths, contract inventory, decision owners/blocking scope and wiring ownership | Design |
| Typed contract stubs and safe .env.example entries | Executable interfaces/models and minimal external-port fakes before tests; no business implementation | Development design worker |

Product behavior and technical choices remain separate. Do not turn a broad
overview into the entire technical design or duplicate interfaces in every ticket.
Use named tables and shared contract references. No minimum document length or
one-test-per-scenario requirement applies.

## Structural validation

Run from the repository root:

```sh
python scripts/ctx_design.py docs/plan/E2
python scripts/ctx_design.py --all
python scripts/ctx_design.py docs/plan/E2 --ready
```

The normal check permits explicitly saved drafts and unresolved decisions. It
rejects invalid state/acceptance schemas, wrong waves, missing/unknown scenario
mappings, unknown ticket identities, missing required documents, undeclared contract
dependencies and incomplete wiring ownership. It does not judge contract semantics.
The --ready check additionally rejects draft designs, pending contracts, open
decisions and blocked plan records. Neither mode grants implementation authority.

CI runs the normal structural check automatically on MRs/default branch and on
branches with CTX_WORKFLOW_CHECKS=1. New E-numbered plan directories are checked;
legacy EPIC-I directories require explicit migration. Scope-only plans without
either acceptance.json or design.json remain valid Planning outputs. Once either
design artifact exists, both are required. Never delete one to hide a failed design.

The handoff metadata uses version 1, the actual epic ID, draft/specified status,
features with spec and technical paths, contracts with id/owner/consumers/document/
status/stub_phase, wiring with ticket/criteria, and decisions with id/status/owner/
question/blocks. See the templates. Scenario definitions use **F1-S1:** followed by
Given/When/Then; acceptance scenario fields contain exact comma-separated IDs.
UI criteria require browser. Inspection uses method inspection plus inspection_reason,
not a new method named justified_inspection. One focused check may prove many ACs.

Documentation-only work can omit a technical file with technical_not_applicable,
use an empty contract inventory with contracts_not_applicable, and omit a wiring
ticket with wiring.not_applicable. Each requires a specific rationale; the reviewer
checks its validity. New interfaces/components cannot use that path to evade wiring.

## Semantic review and execution gates

An independent reviewer reads the actual specs, contracts, tickets and plan at the
design SHA. The reviewer checks that each criterion actually proves its scenario,
contracts agree across consumers, state has an owner, channels cross process
boundaries explicitly, startup configuration is coherent, and wiring has observable
results. Record reviewer identity, exact SHA, findings and source-note URL. A
structurally green JSON file, self-check or file readback cannot replace this review.

The coordinator reuses a verified independent review at the same design SHA or
delegates the existing read/comment-only epic_review component in design-readiness
mode before ticket claims. No new bot is required. It saves that review separately
from ticket journal receipts, counts the delegation against the engine cap, and
still performs the normal final integrated-epic review after implementation.

Development reconciles the review and live dependencies before preparing contract
stubs. Reuse correct stubs; otherwise create only specified models/interfaces and
minimal external-port fakes, commit them, then prepare tests. Tests must collect and
fail for the intended business assertion, not because a module is absent. Foundation
and CI-policy changes need explicit scope and independent review, not silent edits
to make acceptance pass.

Chat agents have no shell. They save useful drafts, inspect available CI results
and report remaining gates without pretending to run commands. An open question
names its affected tickets; unrelated resolved design may continue. A human can
request a narrower ready scope after its decision and dependency gates are satisfied;
the whole-epic --ready check remains conservative.

## Reconciliation and historical work

Only pending, running, blocked and done are state statuses. Selection is metadata.
Done requires the existing integration evidence fields and actual remote review/CI
verification. For historically merged work with missing review, preserve merge SHA,
MR and original status in historical metadata, mark the execution gate blocked,
and obtain the missing independent review. Do not reopen the GitLab issue, repeat
the completed implementation, forge a review or weaken the done schema.

Change scenarios, contracts, AC mappings and dependency waves together. Preserve
stable IDs and prior evidence. New/contradictory scope becomes an explicit Planning
delta; editorial repair and detail within existing scope do not create new tickets.
Wiring belongs in an existing scoped integration ticket where possible, with a real
startup path and observable evidence, not just a demonstration checklist.

## Publication

This repair changes repository procedures and draft prompt definitions. Review and
merge the workflow repair first, synchronize the epic's trusted helper revision,
then publish/read back the existing Planning/Design/Development catalog entries.
Do not run the obsolete catalog against new unreviewed policy or claim a repository
edit updates the registered agent. Keep prior catalog versions for rollback.
