---
name: ctx-project-fix
description: Triage development failures into scoped repairs while preserving the approved product intent.
---

Read current failure evidence and the existing issue/MR before changing code.
Distinguish application defects, test/harness defects and unavailable infrastructure.
Use ctx-hotfix for a bounded behavioral repair; return broader intent changes to
planning. Preserve the original failing evidence and record the repair SHA.

Run the affected checks and required integration gates. Never weaken a requirement,
mock away the failing boundary or change CI policy to turn a failure green. No
automatic retrigger loop: persist a blocker when the scoped repair cannot complete.
