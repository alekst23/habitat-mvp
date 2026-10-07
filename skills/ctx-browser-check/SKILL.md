---
name: ctx-browser-check
description: Exercise UI acceptance criteria in a real headless browser and retain per-criterion observable evidence.
---

Read the ticket/spec, acceptance.json and docs/development/browser-checks.md.
Classify ACs by verification method. Backend-only behavior needs backend evidence;
record browser not-applicable with a reason when there are no UI ACs.

Use the candidate app started inside the GitLab CI job. Preview testing needs a
separately reviewed SHA-binding adapter; the current harness does not supply one.
Readiness and fixture setup must succeed before testing.
Use test accounts/fixtures, never real ads, payments or customer actions.

Preserve the original live-browser procedure: establish Given, perform When, inspect
Then using DOM state and corroborating requests, capture screenshots and relevant
console/network evidence. A source-code reading or screenshot alone is not proof
that a user interaction worked. Expected negative responses, such as a budget
denial, pass when they match the AC; unexpected failures are findings.

Use the minimum browser journeys necessary. Reuse existing Playwright tests; one
journey can prove several ACs. Prefer backend tests for backend invariants and do
not repeat an entire test matrix in the browser. Use isolated browser contexts.

Agent-driven checks may use an installed Playwright CLI through the browser component's
execution tools. Repeatable checks use .gitlab/ctx/playwright.config.ts in CI.
Both need real browser/runtime setup; do not invent tool availability. If absent,
record blocked. The read-only code reviewer consumes evidence and cannot run a browser.

Report each UI AC as passed, failed or blocked with checked SHA, pipeline, test ID
and artifact links. Follow the acceptance evidence contract. Close only sessions
and servers this run started. Unexpected failures go back to development.
