---
name: ctx-ticket-new
description: Allocate a stable epic-local ticket, GitLab issue mapping and scoped acceptance criteria.
---

Follow version-2 numbering in docs/development/ctx-contract.md. Reconcile remote
state and use one planning writer per epic. Deduplicate before creating the ticket
issue; record its returned IID separately from its E<epic-iid>-<number> ID.

For additions preview with scripts/ctx_workflow.py add-ticket. Persist the returned
mapping, next_ticket_number, dependencies, issue title and matching ticket file.
Never recycle numbers or recreate issues after an uncertain write without readback.

Give ACs stable IDs (for example E2-1.AC1) linked to spec scenarios. Put their
verification methods in the epic's acceptance.json using the template. Several ACs
may share one test; IDs identify requirements, not a quota of tests to write.
