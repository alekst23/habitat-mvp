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
| design.json | Explicit capability IDs/purposes, feature paths and ticket mapping, contract inventory, decision owners/blocking scope and wiring ownership | Design |
| Typed contract stubs and safe .env.example entries | Executable interfaces/models and minimal external-port fakes before tests; no business implementation | Development design worker |

Product behavior and technical choices remain separate. Do not turn a broad
overview into the entire technical design or duplicate interfaces in every ticket.
Use named tables and shared contract references. No minimum document length or
one-test-per-scenario requirement applies.

## Guided session and feature layout

A scoped request is one Design session, not a sequence of user-managed saves.
Design leads grounding, feature mapping, behavior interview, contracts, ticket/AC
reconciliation, self-check/CI readback and final handoff. After each answer it
advances unblocked work and saves coherent checkpoints. Its response includes the
next concrete question, or a real blocker and unblock action, not just "saved" or
"remaining tasks". Do not ask "continue?" for ordinary work or repeat permission
to save a product decision. Configured GitLab tool approval cards still apply.
Chat cannot promise unattended continuation after ending a turn; runtime limits
require an explicit checkpoint and resume action.

Maintain Design progress in _epic.md: each feature's document paths, behavior,
contracts and ticket/AC progress, unresolved decision IDs, and next action. This
does not change state.json statuses or attest readiness. Check it against actual
files and decisions when resuming. Distinguish product questions from unavailable
external evidence, review and Development gates; finish independent design work
before pausing on a scoped evidence blocker. Do not repeatedly ask the user to
verify the same unavailable provider fact or invent an answer.

Map independently describable capabilities before drafting. Each gets
`docs/design/<feature>/spec.md` and, where applicable, `technical.md`. Onboarding,
funding, private memory and action approvals do not become one feature because
they share the Habitat epic. A real single-feature change can use one pair. This
is a semantic boundary, not a minimum file count or one folder per ticket.

Features and tickets are many-to-many. Each contract has one canonical owning
feature's technical.md; consumers link to its section. docs/design/README.md is
the navigation index. An optional docs/design/architecture.md holds shared context
and links, not a second monolithic contract dump. After initial grounding, read
the current feature and required dependencies; re-read changed/touched files and
all saved files at their exact SHA, then perform the epic-wide consistency pass.

When splitting an existing umbrella, preserve the full content, confirmed decisions,
scenario/AC IDs and evidence; update the index, inventory, ticket/epic pointers and
contract links together. Do not invent new tickets or summarize away detail. Keep
historical navigation where needed without duplicate scenario definitions. Resolve
concurrent writers before moving files.

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

New/reorganized handoff metadata uses version 2, the actual epic ID, draft/specified
status, features with id/purpose/tickets/spec and technical paths, contracts with id/owner/consumers/document/
status/stub_phase, wiring with ticket/criteria, and decisions with id/status/owner/
question/blocks. See the templates. Scenario definitions use **F1-S1:** followed by
Given/When/Then; acceptance scenario fields contain exact comma-separated IDs.
UI criteria require browser. Inspection uses method inspection plus inspection_reason,
not a new method named justified_inspection. One focused check may prove many ACs.

Each version-2 feature ID is a unique lowercase kebab-case directory name; its
paths are exactly docs/design/<id>/spec.md and docs/design/<id>/technical.md.
Purpose is required. Its nonempty, unique ticket list must exactly match the
tickets whose ACs refer to scenarios defined in that spec. Sharing one technical
file across feature records is rejected; link shared contract sections instead.
Version-1 handoffs remain readable and report feature_layout=legacy_unclassified;
they do not claim an explicit feature map. Version 2 reports feature_layout=explicit.
These are structural results: a purpose field cannot prove that a multi-feature
MVP was decomposed well. The agent and independent reviewer must check boundaries.
Neither schema imposes a document-size limit beyond the existing safety bound.

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

This continuity/layout repair is a Design v1.4.0 publication candidate; v1.3.0
remains the recorded published agent. Review and merge the procedures, templates
and helper first. A maintainer must synchronize existing epics' trusted helper
revision before Design writes version-2 design.json; the chat agent cannot change
scripts/CI itself. Then publish/read back the existing Design catalog entry, keeping
its tool/access settings. No Planning or Development republish is needed for this
Design prompt repair; their independent pending work stays separate.
Do not run the obsolete catalog against new unreviewed policy or claim a repository
edit updates the registered agent. Keep prior catalog versions for rollback.

In a fresh chat verify a real resolved answer leads to artifact updates and the
next question in the same turn, without a "continue" prompt. Verify multiple
capabilities have distinct paths with complete AC coverage; verify a scoped blocker
does not hide unfinished independent work. Unit tests and prompt-text guardrails
do not prove native model behavior. Do not invent product decisions for a smoke test.
