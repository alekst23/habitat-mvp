---
name: ctx-epic-design
description: Turn planned scope into coherent behavioral, technical and ticket designs with a checked handoff.
---

# Epic design

Read AGENTS.md, docs/development/ctx-contract.md and
docs/development/design-readiness.md. Ground project/source/epic identities and
read every scoped ticket, state, issue note, existing spec and active MR at coherent
SHAs. Read the actual templates. Explore source contracts and composition roots;
distinguish missing code from verified reuse. Use ctx-spec-interview's full tree.

## Produce design, not a summary

1. Map independent capabilities to concept-named directories before writing. Use
   docs/design/<feature>/spec.md and feature-local technical.md, not one umbrella
   pair for a whole multi-feature epic. Update docs/design/README.md and version-2
   design.json's id/purpose/tickets/spec/technical inventory. Tickets and features
   are many-to-many; do not create scope, renumber, or split mechanically per ticket.
   Preserve requirements and stable scenario IDs; record the exact delta.
2. Write feature-local technical.md for new interfaces/nontrivial integration. Define contract
   names, fields/types, request/results/errors, invariants, owner and consumers,
   idempotency/recovery behavior and intended source location. "Typed tools" or
   "atomic ledger" is not a contract definition. Each contract has one authoritative
   feature document; consumers link to its section. Shared architecture/topology
   may have a small overview in docs/design/architecture.md, not a second full spec.
3. Add **Process topology**: component, runtime process, construction/entry point,
   state owner, authenticated cross-process channel and failure behavior. Name the
   channel (HTTP, table/outbox, stream, etc.), not assumed shared memory. State when
   everything is in one process.
4. Add **Configuration**: settings, working defaults or deliberately unset values,
   service ownership, secret references (never values), and startup validation.
   Unknown provider facts stay disabled/pending verification.
5. Run ctx-ticket-design for all scoped tickets. Preserve agreed ACs, dependencies
   and completed evidence. Designs must be implementable, not security slogans.
6. Assign production wiring and smoke ownership. New instantiated/cross-process
   components require an existing integration ticket covering entry points,
   consumers, channels and live observable results, dependent on all providers.
   A video/storyboard is not a wiring check. Missing scope becomes a specific
   Planning delta, not an invented ticket or silent omission.
7. Save acceptance.json and design.json using actual schemas. Reconcile every spec
   scenario to ticket ACs; preserve IDs. Methods: test, browser, inspection.
   Inspection requires inspection_reason. Structural validation is not semantic
   completeness or application evidence.

## Conversational continuity

In chat own the progression across the scoped epic, not one question/commit at a
time. Track a compact Design progress section in _epic.md: feature documents,
behavior/contracts/ticket-mapping progress, unresolved decision IDs and next action.
Update it alongside coherent document saves, without changing execution statuses.
Resume from verified files and decisions, not stale cursor text. Read feature-local
context and direct contract dependencies after initial grounding; finish with an
epic-wide consistency pass. Required procedure reads and exact-SHA saved-file
readback remain mandatory.

After an answer, reconcile the affected design, finish unblocked routine work,
save/read back when useful, and ask the next material question in the same response.
Do not end on a checkpoint receipt or ask permission to continue ordinary work.
Only pause for a concrete unanswered decision, actual permission/tool/runtime
blocker, explicit user pause, or completed Design handoff. State why and the exact
next action. Honor configured tool approval cards; no unattended/self-resuming chat
promise. Record unavailable external evidence once with owner and affected scope,
then continue independent work. Do not invent provider verification or review.

Before completion check every mapped feature's behavior/failures, technical
contracts/applicability, ticket/AC coverage and saved files; reconcile CI if available.
Separate incomplete design work from external evidence, independent review and
Development prerequisites. No Planning/Development detour to finish Design's saves.

## Reconcile without erasing history

Enrich approved scope; do not shorten tickets into summaries losing ACs, prerequisite,
verification or closure records. For genuinely new/contradictory requirements,
record the delta and affected IDs in the epic, preserve old commitments/evidence,
and request Planning's approved delta allocation. No renumbering or fake completion.
Editorial corrections and already-scoped details do not require new tickets.

State statuses are pending, running, blocked, done. "Selected" is metadata, not a
status. Historically merged work missing required review stays evidence-blocked,
with merge facts preserved; never fabricate URLs or redo completed implementation
merely to convert its status. Derive waves from dependencies.

## Review and save

Semantically review producer/consumer contracts, trust boundaries, every scenario,
configuration, failures, decisions and wiring: can a fresh implementer work without
inventing product rules? Record gaps. Independent semantic review is required before
implementation readiness; self-review is not approval.

With a shell run `python scripts/ctx_design.py docs/plan/E<epic-IID>` and the wave
helper. CI automatically checks generated artifacts. Without a shell save artifacts
and inspect actual job results; never claim execution happened. Use --handoff for
specified design with no open design-stage questions; --ready additionally requires
all later decisions and blocked state resolved. Neither replaces semantic review.
Set specified when the documents are complete, not only after Development gates
pass. Later open decisions retain stage, owner, scope and a fail-closed safeguard.
Missing stage means design; do not reclassify unknown behavior to evade completion.

For legacy umbrella documents, move existing sections without summarizing away
detail, preserving IDs/decisions/evidence. Update index, contract inventory and all
ticket/epic pointers in one coherent change. Retain historical navigation where
needed, without duplicate scenario definitions. Resolve concurrent writers first.
Move complete contract tables, recovery/transaction rules and configuration, not
summaries. Replace the old umbrella with section redirects and an immutable history
link only after every substantive section has a canonical destination.

Commit on the verified epic branch with concurrency guards; read every changed
file at the returned SHA. Report saved draft versus specified design, file/commit
links, checks and remaining review/decisions. A checkpoint report includes the next
question/action; it is not the final handoff. Notes do not replace artifacts.
Do not dispatch implementation.

Design completion, documentation MR merge, implementation readiness and provider
enablement are distinct. Missing independent/historical review or later provider
evidence alone does not keep complete specifications in draft. Development obtains
reviews and reconciles execution evidence; Design publishes one source-issue
handoff with SHA, artifact links, actual CI, later gates/owners and the next human
Development invocation. A supplied unreadable MR note is unverified, not failed;
do not make manual copying or another interview the default exit path.
