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
