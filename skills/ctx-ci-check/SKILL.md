---
name: ctx-ci-check
description: Run proportionate verification and reconcile actual GitLab job evidence for the current candidate.
---

Read the lean-testing policy in docs/development/ctx-contract.md. Run focused checks
first and required CI checks before closure; do not repeatedly run an unchanged
suite after it passes. Broaden only for integration risk, a failure or new changes.
Reuse existing coverage and add no tests merely to increase counts.

Use reviewed commands in .gitlab/ctx/commands.yml. The verify adapter must emit
application results and .ctx/acceptance.json per the acceptance contract. The
separate acceptance job checks that manifest requirements have matching evidence.
Read docs/development/acceptance-evidence.md. CI resolves scope with
`python scripts/ctx_ci_context.py resolve`; never ask the user to override pipeline
variables. Ticket context is prepared/committed by implementation before verification;
whole-epic context by epic docs before final verification. A mismatch is owned
technical recovery, not a product question or permission to weaken the manifest.
Use the current candidate's ordinary CI; inspect actual scope/hash/jobs. Native
workers must not mistake inherited runner CI identity for their isolated worktree:
`prepare` uses the actual Git branch/head; CI `resolve` validates the real pipeline
candidate. Do not change CI identity to manufacture local evidence. If the
only missing step is a permitted CI retry, perform it through available approved
tools; if not permitted, give exactly that access action, without requesting new
tokens/scopes. A policy/helper publication gap needs reviewed maintenance first.
Fetch actual job status and source SHA: workflow self-tests, skipped jobs, allowed
failures, pending CI and stale results do not establish application acceptance.

For failure, identify the smallest cause and affected checks. Persist diagnostics.
In version-2 Development, publish the verification bundle defined in
docs/development/single-shot-development.md, including actual jobs and full AC/browser
reports. Confirmed scoped code/test/AC defects return structured findings with
blocker_kind=defect for the same supervisor's bounded repair loop. Missing adapters,
permissions or reports are evidence blockers, pending CI is ci_pending; neither is a
pass or license to weaken controls. New commits require fresh checks for all scoped
ACs and required integration gates, followed by a new independent review.
For an idle evidence-blocked verify step, the supervisor can use `resume-evidence`
with a fresh full valid bundle and saved/read-back recovery receipt, preserving
all consumed counters. A new pipeline alone does not reopen the journal. Changed
SHA requires the reviewed maintenance-adoption protocol or ordinary bounded code
repair; do not relabel a blocker, reset the run or skip independent review.
