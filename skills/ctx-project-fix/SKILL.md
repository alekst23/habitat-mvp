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
automatic flow retriggers. Inside Development's version-2 supervisor, use the bounded
repair protocol in docs/development/single-shot-development.md: verify actionable
findings and in-scope AC IDs, reproduce with minimal regression coverage, commit a
new candidate, report resolved_findings, then run fresh full-scope verification and
independent review. A ticket repair stays on its isolated branch; an explicitly
delegated assembled-epic repair uses its owned non-default consolidation branch and
returns through docs, full-epic verification and epic review. Preserve integrated
ticket history. Three cumulative repairs per target and the global action bound
apply; no reset per SHA. Missing infrastructure/authority/intent requires a checkpoint,
not a workaround or another catalog flow. Continue unrelated ready work.
