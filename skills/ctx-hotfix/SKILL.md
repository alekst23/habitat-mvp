---
name: ctx-hotfix
description: Route a bounded defect through a minimal specification delta, regression check and reviewed fix.
---

Confirm the expected behavior and reproduction from the issue/spec. If the change
expands intent, return to planning. Otherwise reuse the smallest ticket path and
ctx-ticket-design/tests/start/review/close with the normal prerequisites.

Prefer one focused regression test, or an existing failing test that already proves
the defect. Do not bypass tenant, cost, review or merge controls for urgency. Report
the repaired behavior and actual verification; missing infrastructure remains blocked.
