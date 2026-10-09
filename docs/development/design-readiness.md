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
python scripts/ctx_design.py docs/plan/E2 --handoff
python scripts/ctx_design.py docs/plan/E2 --ready
```

The normal check permits explicitly saved drafts and unresolved decisions. It
rejects invalid state/acceptance schemas, wrong waves, missing/unknown scenario
mappings, unknown ticket identities, missing required documents, undeclared contract
dependencies and incomplete wiring ownership. It does not judge contract semantics.
The --handoff check additionally rejects draft designs, pending contracts and open
design-stage decisions. It reports, but does not clear, later gates and blocked
tickets. The --ready check remains the conservative all-gates check: it rejects
every open decision and blocked plan record as before. Neither grants authority.

CI runs the normal structural check automatically on MRs/default branch and on
branches with CTX_WORKFLOW_CHECKS=1. New E-numbered plan directories are checked;
legacy EPIC-I directories require explicit migration. Scope-only plans without
either acceptance.json or design.json remain valid Planning outputs. Once either
design artifact exists, both are required. Never delete one to hide a failed design.

New/reorganized handoff metadata uses version 2, the actual epic ID, draft/specified
status, features with id/purpose/tickets/spec and technical paths, contracts with id/owner/consumers/document/
status/stub_phase, wiring with ticket/criteria, and decisions with id/status/owner/
question/blocks and optional stage/safeguard. See the templates. Scenario definitions use **F1-S1:** followed by
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

### Completion is not one global ready flag

| Outcome | Required | Does not require or authorize |
|---|---|---|
| Design specified | Complete canonical documents, resolved design decisions, consistent mappings, saved-file readback, self-check and truthful CI status | Independent technical review, historical evidence repair or provider enablement |
| Documentation MR merge | Human acceptance and actual repository merge controls | Epic completion, implementation or deployment |
| Development may claim a ticket | Design handoff, independent design review, scoped decisions/dependencies/evidence and safe execution prerequisites | Enabling unverified providers or changing CI policy |
| Provider/connector enablement | Verified external facts, implemented safeguards, tested configuration and applicable human/protected controls | Inference from a design merge or sandbox funding |

Set design.json status=specified when Design's document work is complete; pending
review does not force draft. Keep incomplete design or unresolved behavior draft.
Each decision has stage=design (default for legacy records), development, or
enablement. Later stages require a nonempty safeguard explaining precisely what
remains blocked/disabled, alongside the existing owner/question/affected tickets.
This is classification, not permission: a reviewer must reject moving unknown
behavior or unverified safety assumptions to enablement without a safe specified
fallback. Unknown stage or absent safeguard fails validation. No automatic migration
of old decisions, ticket status changes or review assertions occurs in the helper.

Design's final source-issue report names the exact artifact SHA/MR/index, completed
scope, actual structural CI (or pending), later gates with owners/unblock actions,
and one next human Development invocation for that epic/SHA. Do not require a new
Design chat, repeated provider questions or a manually collected review to hand off.
The agent never changes merge controls or merges; missing later evidence alone is
not a reason to insist a documentation MR remain Draft.

### Development-owned preflight

Use this order before creating the fixed execution request/journal or claiming tickets:

1. Pin the coherent design SHA and run --handoff. Unfinished artifacts or open
   design decisions return a precise finding to Design, not a generic restart.
2. Reuse a verified same-SHA independent design review, or delegate epic_review
   mode=design-readiness. Do this even if historical ticket evidence is blocked.
3. Reconcile historically merged evidence through epic_review mode=historical-evidence
   as needed. The coordinator verifies actual MR/ancestry, original ACs, source and
   integration SHAs, CI and reviewer report. Update state only when the existing done
   requirements are genuinely met; preserve historical metadata and original receipts.
   Missing evidence produces a concrete owner/action, not repeated implementation.
4. Assess affected tickets and dependencies against design/development gates. An open
   enablement gate permits only otherwise-ready local/fixture development with its
   safeguards enforced. Never dispatch to an unverified provider. If the intended
   validation requires that provider, retain a verification blocker: fakes cannot
   substitute for required integration/browser evidence or declare the ticket done.
5. Pin reconciled state, manifest and design SHA in the execution request. No mutation
   of an existing fixed request/journal to waive a blocker. Continue the SDLC only for
   the verified ready scope; checkpoint actual remaining prerequisites with exact actions.

All preflight delegations count against the existing engine limit. Publish/read back
their reports on the resolved source issue, separately from ticket/epic completion
receipts. A design review can be ready while implementation dependencies remain
blocked. Do not use the all-gates --ready result as proof that a review happened,
or its enablement failure as a reason not to obtain a design review.

### Readable review receipts

The live catalog's existing Get Merge Request tool advertises notes/discussions
through its include option (verified 2026-10-09). Request those facets using the
native schema and pagination, then locate the supplied note ID; a missing standalone
note-by-ID tool is not a blocker. Read author, body and reviewed SHA rather than
inferring them from the URL or base MR metadata. If the deployed tool actually cannot
return the note, retain its reference as unverified, not a failed review or unfinished
design. Development also uses its MR/API tools to inspect supplied references. A
brief human "looks correct" is product acceptance, not a detailed technical review.
Verify actual reviewer independence, full report, exact design SHA, scope and
findings. If absent/stale, obtain the existing independent reviewer delegation.
Publish/read back its full source-issue note with identity, verdict, findings and
original reference when applicable. A mirrored report identifies the original
reviewer and coordinator as transcriber; copying cannot create independence.
If access fails, report the exact access remedy/owner once, not an endless request
for the user to paste comments. No broader chat tools or permissions are required.

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

Local completion-boundary repair (2026-10-09) is not yet merged or published.
It changes both the Design prompt and Development preflight, plus the helper and
shared procedures. Review/merge the workflow repair, synchronize trusted helpers
onto E2, then merge the separate product-document repair into the epic branch.
Publish/read back both existing catalog entries (Design candidate v1.5.0,
Development candidate v1.4.0), preserving tools, visibility and triggers. Verify
native handoff/review behavior before claiming success; no flow is launched here.

Design v1.4.0 is published/enabled with full prompt readback (2026-10-09 UTC).
Workflow MR !14 merged at 9f5ccbf and helper-sync MR !15 merged onto E2 at a58e623;
both pipelines passed. That publication preserved product documents. The subsequent
live Design run at 97d7e2cb split features but left full contracts in the old umbrella
and stalled on review/enablement gates; this is the evidence motivating this repair.

For subsequent revisions, review and merge the procedures, templates and helper
first. A maintainer must synchronize existing epics' trusted helper revision before
using new handoff semantics; the chat agent cannot change scripts/CI itself. Then
publish/read back the existing Design and Development catalog entries, keeping
their tool/access settings. Planning stays unchanged.
Do not run the obsolete catalog against new unreviewed policy or claim a repository
edit updates the registered agent. Keep prior catalog versions for rollback.

In a fresh chat verify a real resolved answer leads to artifact updates and the
next question in the same turn, without a "continue" prompt. Verify multiple
capabilities have distinct paths with complete AC coverage; verify a scoped blocker
does not hide unfinished independent work. Unit tests and prompt-text guardrails
do not prove native model behavior. Do not invent product decisions for a smoke test.
