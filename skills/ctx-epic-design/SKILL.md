---
name: ctx-epic-design
description: Reconcile a feature specification, epic tickets and acceptance manifest when intent changes.
---

Compare the current spec with every ticket, dependency and active MR. Retain stable
IDs and completed evidence; mark changed requirements as needing fresh verification.
Use ctx-spec-interview for unresolved behavior. In CTX Design, work across all scoped
tickets and own spec, technical design, ticket Design sections and acceptance.json.
For genuinely new scope, hand off to Planning's ctx-ticket-new; first save resolved
in-scope design. Do not send existing scoped work back to Planning merely to save it.

Ensure the plan covers required contracts, runtime prerequisites and final wiring.
Update acceptance.json so its criteria match the spec/tickets; update test mappings
only as needed. Run scripts/ctx_workflow.py waves on state.json when a shell exists;
otherwise explicitly mark runner validation pending. This does not block saving
resolved design. Commit on the verified epic branch and compare all saved files
at the returned SHA. Publish file/commit links and a ctx-development handoff after
design is resolved, not only an issue note. Do not dispatch implementation sessions.
