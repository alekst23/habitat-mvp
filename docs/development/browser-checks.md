# Browser checks in GitLab

The browser skill remains an internal step of `ctx-development`, before independent
ticket review. A real browser proves observable UI behavior; DOM/code inspection
alone does not. Keep the absolute minimum durable journeys and reuse each to prove
several related ACs. Backend-only tickets need a recorded not-applicable reason,
not a synthetic browser test.

## Repeatable CI path

`.gitlab/ci/browser.yml` runs Chromium through Playwright in a browser-ready Linux
image. `.gitlab/ctx/playwright.config.ts` starts the checked-out application at
`http://127.0.0.1:4173`; it never attaches to an arbitrary preview or an already
running server. `.gitlab/ctx/browser-reporter.ts` maps executed tests to ACs.

The application foundation must supply:

1. A root `package.json` with exact dev dependency `@playwright/test: 1.63.0`, plus
   a committed `package-lock.json`. Ignore `node_modules/` and generated build
   outputs; tests must not change tracked files. Keep dependency and image in sync.
2. `npm run start:test`, which builds/starts this candidate on port 4173 and prepares
   deterministic fixtures/test authentication. No live customers, payments or ads.
   Any database/service dependency needs separately reviewed CI setup.
3. The smallest useful tests in `tests/browser/`, with real observable assertions.
   Annotate the ACs proved by the test; annotations alone do not prove behavior.
4. The committed manifest and scoped pipeline variables from
   [acceptance evidence](acceptance-evidence.md), including `CTX_BROWSER_CHECKS=1`.

For example, attach these annotations to ONE real journey when it proves both ACs:

```ts
test('blocked request shows the reason and preserves the balance', {
  annotation: [
    { type: 'ac', description: 'E2-1.AC2' },
    { type: 'ac', description: 'E2-1.AC3' },
  ],
}, async ({ page }) => {
  // Use fixture credentials, perform the action, and assert both observed outcomes.
  // Implement the assertions against the actual UI; do not commit this empty example.
});
```

Use stable accessible locators. Check relevant DOM state and unexpected console,
page, request or HTTP errors; add explicit assertions/listeners where material.
Expected authorization/budget-denial responses are successful behavior when their
effects match the AC, not unconditional HTTP failures. Traces contain useful
console/network evidence but do not automatically assert that it is error-free.
Do not create broad screenshot baselines, exhaustive viewport matrices or duplicate
backend tests unless an identified risk actually needs them.

The reporter verifies that HEAD still matches the pipeline SHA and the checkout
is clean after execution; generated outputs belong in ignored paths. The runner
uses one worker, no retries, headless Chromium, screenshots and traces
for every executed test. It uploads JUnit, HTML, traces/screenshots and per-AC
JSON under `.ctx/browser/`, retained for 30 days. Missing annotations, skipped tests,
expected failures and failed runs cannot be counted as passing AC evidence.
One test may annotate multiple criteria. Never include credentials/customer data
in fixtures or artifacts; traces can contain network payloads and UI text.

No application or browser journeys are supplied by this workflow change. Enabling
the job before foundation prerequisites exist fails; it does not manufacture a pass.
`CTX_BROWSER_CHECKS` is only relevant inside the `CTX_APPLICATION_CHECKS=1` lane.
An omitted browser job is allowed for non-UI scope; acceptance still blocks any
manifest that requires browser evidence but lacks the matching report.

## Agent-driven exploration

`ctx-browser-check` also describes short Given/When/Then exploration using a
configured Playwright CLI or equivalent browser tool in the Duo runner. The browser
component has command execution; the independent reviewer does not. Record the
candidate, fixture/account, actions, DOM result, console/network findings and
screenshots in the issue/MR handoff. Fixes go back to implementation and re-verification.

The current `.gitlab/duo/agent-config.yml` is Python-only. It does NOT inherit the
browser CI image, a developer's desktop browser, or this chat's browser tools.
Agent-driven browsing needs a reviewed default-branch toolchain image/setup with
Node, Playwright/browser binaries and dependencies, plus appropriate network rules
and fixture credentials. Until that exists, consume the actual matching CI browser
artifacts instead. Missing access is blocked, never a claimed browser pass.

Exploration supplements the repeatable CI gate; it does not replace its report.
Preview-environment testing needs a future reviewed adapter that binds the tested
deployment to the exact candidate SHA. Arbitrary URLs are intentionally unsupported
by this first harness.

References: [Playwright on GitLab CI](https://playwright.dev/docs/ci#gitlab-ci),
[annotations](https://playwright.dev/docs/test-annotations),
[GitLab agent environment](https://docs.gitlab.com/user/duo_agent_platform/flows/execution/agent-config-yaml/).
