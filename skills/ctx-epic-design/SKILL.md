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

1. Update concept-named specs and docs/design/README.md. Preserve requirements and
   stable scenario IDs; record the exact delta from prior design.
2. Write technical.md for new interfaces/nontrivial integration. Define contract
   names, fields/types, request/results/errors, invariants, owner and consumers,
   idempotency/recovery behavior and intended source location. "Typed tools" or
   "atomic ledger" is not a contract definition.
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
helper. CI automatically checks generated artifacts. Without a shell save drafts
and inspect actual job results; never claim execution happened. Use --ready only
for fully specified handoffs with resolved decision/state gates. A pass still does
not replace independent review or execution preflight.

Commit on the verified epic branch with concurrency guards; read every changed
file at the returned SHA. Report saved draft versus specified design, file/commit
links, checks and remaining review/decisions. Notes do not replace artifacts.
Do not dispatch implementation.
