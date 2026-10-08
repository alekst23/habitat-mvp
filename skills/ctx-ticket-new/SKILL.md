---
name: ctx-ticket-new
description: Allocate a stable epic-local ticket, GitLab issue mapping and scoped acceptance criteria.
---

Follow version-2 numbering in docs/development/ctx-contract.md. Reconcile remote
state and use one planning writer per epic. Deduplicate before creating the ticket
issue; record its returned IID separately from its E<epic-iid>-<number> ID.

For additions preview with scripts/ctx_workflow.py add-ticket when a shell is available.
Chat must preserve its allocation invariants without claiming the helper ran. Persist the returned
mapping, next_ticket_number, dependencies, issue title and matching ticket file.
Never recycle numbers or recreate issues after an uncertain write without readback.

Planning records high-level acceptance expectations and Design pending, preserving
existing AC IDs. It need not invent final scenarios/technical design before ticket
creation. CTX Design then gives ACs stable IDs (for example E2-1.AC1), links them to
spec scenarios and saves verification methods in acceptance.json. Several ACs
may share one test; IDs identify requirements, not a quota of tests to write.
