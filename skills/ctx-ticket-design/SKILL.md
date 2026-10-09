---
name: ctx-ticket-design
description: Define implementable ticket contracts and prepare typed stubs before behavioral tests.
---

# Ticket design

Read the full ticket, parent scope, behavioral spec, technical design, acceptance
manifest, design.json and dependency contracts. Explore actual source and sibling
patterns before claiming reuse. A committed behavioral spec is required to complete
design; Planning may create design-pending tickets earlier.

Resolve relevant feature specs through design.json's feature/ticket map; a ticket
may consume several features and a feature may span tickets. Link exact feature
scenarios and canonical technical contract sections, not an entire umbrella MVP
document or copied contract definitions. After initial grounding, load the current
slice and its dependencies; keep the epic-wide reconciliation in ctx-epic-design.

## Chat Design output

Save on the verified epic branch, across all scoped tickets when requested:

- **Solution approach:** exact behavioral slice, layers/boundaries, proposed paths,
  verified reuse and concrete sequence. Short is fine; "implement the services" is
  not a solution approach.
- **Contracts:** link technical.md's named models/ports/HTTP/event schemas. Identify
  producer, consumers, inputs/results/errors, transaction boundary and invariants.
  Reuse existing interfaces. Label proposed locations versus actual source.
- **Configuration:** service-owned settings, default/required values and startup
  denial conditions, documented in technical.md and later .env.example. No secrets.
- **Verification:** every AC and its spec scenarios, minimum meaningful checks,
  expected behavioral failures, material races/replays and UI evidence. No test-per-AC
  quota; do not remove requirements to reduce test count.
- **Dependency/wiring impact:** consumed/exported contracts and how integration
  will exercise them at the real entry point.

Preserve original ACs and execution/review/closure evidence. Scope changes become
specific Planning deltas. Missing intent returns to the interview. Routine
technical decisions do not require repetitive approval.

## Development design phase: mandatory contract preparation

Chat Design writes documents and has no shell. The Development design worker owns
**typed contract stubs before tests**, on the isolated ticket branch. Consume the
saved design; do not repeat interviews or substitute requirements. Verify dependency
integration, structural checks and independent semantic design review.

For every new contract, define the appropriate typed model, interface or Protocol
and minimal fake/stub for external ports. Signatures and validation only: no business
logic, real dispatch, credentials or broad scaffolding. Use the project language;
an absent foundation/harness is an explicit bootstrap dependency, not permission
to change CI policy in an unrelated ticket. Deliberate unimplemented results are
acceptable; missing imports are not a behavioral red baseline.

Document safe config defaults/placeholders in .env.example. Update technical.md's
source pointers to actual files, commit contracts and record the SHA. Reuse correct
existing contracts with a reason. Do not require a new design commit when contracts
already satisfy the design. Documentation-only tickets explain why stubs are not
applicable. Then hand off to ctx-ticket-tests.

Return ready only with verified artifact identity, contracts, candidate SHA and
report readback. Missing decisions, integration or checks block dependent execution.
An issue note alone never satisfies the committed-design gate.
