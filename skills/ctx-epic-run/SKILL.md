---
name: ctx-epic-run
description: Reconcile an epic's dependencies and select a bounded development slice from verified remote state.
---

Read state.json, current issues/MRs, session notes and branch/CI state. Resolve actual
issue mappings and run scripts/ctx_workflow.py waves. Done dependencies require
real ancestry, review and integration evidence. Preserve blocked and in-flight work.

The initial ctx-development flow processes one ticket per run, in dependency order.
Persist the selected ticket and branch on the source issue before component handoff.
Use one coordinator per epic. This is a deliberate serial first version: the wave
helper identifies parallelism but does not launch or lease independent workers.

After ticket closure, save the next ready work. When every ticket is integrated,
hand off internally to ctx-epic-review. No agent-to-agent mention dispatch, automatic
retriggering or unbounded repair loops are implemented.
