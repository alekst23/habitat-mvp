---
name: ctx-spec-interview
description: Conduct a structured intent interview and synthesize durable feature specifications.
---

# Behavioral specification interview

Read the source request, existing feature specs, epic/tickets, decision notes and
actual architecture before questioning the user. Record known behavior, what exists
versus is unbuilt, and what only the user can decide. Update concept-named specs;
never replace existing requirements with a fresh summary or template.

## Assess depth

Well-specified context needs zero to two gap questions; partial context needs a
targeted interview; sparse context starts with intent, not a guessed full design.
Depth controls questioning, not artifact completeness. Reuse settled answers.

## Interview in dependency order

1. **Intent:** beneficiary, problem, observable success and prerequisites.
   Distinguish existing infrastructure, in-scope work and external dependencies.
   An unbuilt prerequisite cannot silently become an assumption that it exists.
2. **Features:** bounded capabilities, actors, triggers and outcomes. Settle gaps
   in the list before descending into behavior.
3. **Behaviors:** each feature's happy path as Given/When/Then, including observable
   outputs and state changes, not implementation slogans.
4. **Edge cases and non-goals:** material denial, failure, replay, concurrency and
   recovery behavior where relevant. Explicitly exclude adjacent scope. No speculative
   permutations or test quotas.
5. **Ticket implications:** only when answers reveal a real scope/dependency change,
   identify the precise missing or contradictory deliverable for Planning. Save
   resolved in-scope design; never bounce the user elsewhere merely to persist it.

Ask one focused intent question at a time, with a recommended interpretation and
reason. Research repository-answerable questions yourself. Routine implementation
choices belong in technical design. In chat wait for replies; in ambient execution
publish unresolved questions and checkpoint affected work. Never invent answers.

## Synthesize and persist

Every feature needs a settled happy path and material failure behavior/non-goal,
or an explicit open decision with owner and affected tickets. Present the relevant
draft/delta for correction. Honor read-only requests; otherwise CTX Design owns
ordinary draft saves, exact-SHA file readback and reporting through ctx-epic-design.
A short interview still produces a complete spec, not a shorter standard of design.

The product spec contains intent, actors, observable success, prerequisites,
features, stable scenarios, failures, non-goals and unresolved questions. Define
scenarios as `**F1-S1:** Given ..., when ..., then ...` (IDs unique across the
epic's feature specs); references elsewhere are not new definitions. Preserve IDs.
Keep model fields, class names, wiring and vendor setup in technical.md.

Maintain docs/design/README.md. Feature directories are named by concept, not epic;
many epics can evolve one feature. Do not split files/create epics to imitate an
example's size. A changed decision must update affected scenarios, contracts,
tickets and acceptance mappings, not merely append a decisions paragraph.

Every in-scope scenario maps to ticket ACs in acceptance.json with actual UI
classification and verification methods. Several scenarios may share one focused
test; none may disappear behind "MVP acceptance". Record deferrals explicitly.
Saved drafts do not imply design or implementation readiness.
