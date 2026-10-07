---
name: ctx-ticket-tests
description: Select the absolute minimum meaningful tests for ticket acceptance criteria and establish a valid failing baseline.
---

Read the ticket design, acceptance.json and the lean-testing policy in
docs/development/ctx-contract.md. Inspect existing tests first. Map every applicable
AC to evidence, reusing existing tests and letting one focused test cover several
related ACs. Write new tests only for an uncovered behavior or a concrete regression.

Keep tests lean: small fixtures, direct assertions about observable behavior, the
lowest sufficient test layer, and parameterization only for meaningfully different
cases. No test per method/class/AC quota, coverage-percentage target, duplicated
assertions across layers, implementation-mirroring mocks or tests of trivial wiring.
Do not manufacture tests for documentation or reversible low-impact edits; record
an inspection/validator justification. Preserve existing unrelated tests.

For changed executable behavior, run the smallest applicable test set before
implementation. Reuse a failing existing test when it proves the missing behavior.
The red baseline must collect and fail for the expected behavioral assertion;
missing imports, infrastructure or selectors are not proof of the intended failure.
Bootstrap tickets establish the minimal harness first. Unchanged behavior may
reuse green evidence with an explicit reason; never invent a failing test for ritual.

Record AC-to-test IDs, why each new test is necessary, command, collected count,
expected failures and red SHA. Commit the tests; hand off to ctx-ticket-start.
