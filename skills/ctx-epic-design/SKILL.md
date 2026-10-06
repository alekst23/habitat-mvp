---
name: ctx-epic-design
description: Reconcile a feature specification, epic tickets and acceptance manifest when intent changes.
---

Compare the current spec with every ticket, dependency and active MR. Retain stable
IDs and completed evidence; mark changed requirements as needing fresh verification.
Use ctx-spec-interview for unresolved behavior and ctx-ticket-new for new work.

Ensure the plan covers required contracts, runtime prerequisites and final wiring.
Update acceptance.json so its criteria match the spec/tickets; update test mappings
only as needed. Run scripts/ctx_workflow.py waves on state.json. Publish spec/plan
commit links and a ctx-development handoff. Do not dispatch implementation sessions.
