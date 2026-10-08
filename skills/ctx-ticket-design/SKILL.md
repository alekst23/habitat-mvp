---
name: ctx-ticket-design
description: Define the smallest solution and required contracts for a scoped implementation ticket.
---

In CTX Design chat, read the planned ticket, spec and dependency contracts; dependencies
need not be implemented to design them. Save all scoped ticket designs on the verified
epic branch, preserving unrelated changes. In Development, consume/validate that
committed design from the correct epic base on the ticket branch and verify integrated
dependencies before implementation. Record the solution
approach, touched boundaries, contracts, failure behavior and AC mapping. Reuse
existing design and abstractions where they fit. Add technical.md only when useful.

No business implementation in this phase. Design owns the design commit and exact-SHA
file readback; record its SHA before ctx-ticket-tests. Development need not manufacture
a new design commit if valid committed design already exists. Missing design intent
returns to CTX Design; only changed scope/decomposition returns to Planning. A routine
implementation choice does not require another approval. An issue note alone never
satisfies the committed-design gate.
