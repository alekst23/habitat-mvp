import { test, expect, Page } from '@playwright/test';

// E11-6.AC1: presentation regression boundary over the same real application as E11-3/4/5.
// Seeded identity is test-only. Creation, limits, activation and settled work use the real server.
// Only the explicit unknown-result and lost-response cases below mock the HTTP boundary;
// they prove browser recovery behavior, not provider execution or backend reconciliation.
test('responsive owner controls preserve real work and handle pending or uncertain results safely',
  { annotation: { type: 'ac', description: 'E11-6.AC1' } }, async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  expect((await page.request.post('/__test__/seed-session', { data: { fixture: 'owner-a' } })).status()).toBe(200);
  await page.goto('/workspace');
  await page.getByRole('link', { name: /Create with wizard/i }).click();
  // Valid boundary-length content must wrap rather than disappear behind a clipped card.
  const agentName = 'ResponsiveControls'.padEnd(80, 'x');
  await page.getByLabel(/^Name$/).fill(agentName);
  const instructions = 'Keep the owner informed.\n' + 'Boundaries'.repeat(50);
  await page.getByLabel(/^Instructions$/).fill(instructions);
  await page.getByRole('checkbox', { name: 'inference', exact: true }).check();
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.setViewportSize({ width: 375, height: 1000 });
  await contained(page, '375px created agent');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('link', { name: /Configure goals & schedule|Review agent controls/i }).click();
  if (page.url().endsWith('/workflow')) await page.getByRole('link', { name: 'Review AICL controls', exact: true }).click();
  expect(await page.getByText(instructions, { exact: true }).innerText()).toBe(instructions);
  const instancePath = new URL(page.url()).pathname;
  expect(instancePath).toMatch(/^\/instances\/[0-9a-f-]{36}$/);
  const form = page.locator('#work-form');
  const submit = form.getByRole('button');
  const result = page.locator('#work-result');

  // The optional diagnostic is collapsed in the task-first commerce workspace.
  // Non-commerce pages keep the same controls directly visible.
  async function openDiagnostics(p: Page) {
    const diagnostic = p.locator('#diagnostics');
    if (await diagnostic.count() && await diagnostic.getAttribute('open') === null) {
      await diagnostic.locator('summary').click();
    }
  }
  if (await page.locator('#diagnostics').count()) {
    await expect(page.locator('#diagnostics')).not.toHaveAttribute('open');
    await expect(form).not.toBeVisible();
  }
  await openDiagnostics(page);

  // Lifecycle eligibility is distinct from budget checks, and only enabled capabilities can be selected.
  await expect(submit).toBeDisabled();
  await expect(form.locator('select[name="capability"] option')).toHaveCount(1);
  await expect(form.locator('select[name="capability"]')).toHaveValue('inference');
  await expect(page.getByRole('button', { name: 'Re-check and clear', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Activate', exact: true }).click();
  await openDiagnostics(page);
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(result).toContainText('Result: budget_exhausted.');
  await expect(result).toBeVisible();
  await expect(page.getByText('budget_exhausted', { exact: true })).toBeVisible();
  await expect(page.locator('.stat-grid .status-badge')).toHaveText('gated');
  await expect(submit).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Re-check and clear', exact: true })).toBeVisible();

  await page.getByLabel('Inference daily', { exact: true }).fill('1');
  await page.getByLabel('Inference monthly', { exact: true }).fill('10');
  await page.getByLabel('Compute daily', { exact: true }).fill('1');
  await page.getByLabel('Compute monthly', { exact: true }).fill('10');
  await page.getByRole('button', { name: 'Save limits', exact: true }).click();
  await openDiagnostics(page);
  await expect(page.locator('.stat-grid .status-badge')).toHaveText('active');
  await expect(page.getByText('budget_exhausted', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Re-check and clear', exact: true })).toHaveCount(0);
  await expect(submit).toBeEnabled();
  await expect(page.getByText('No usage yet.', { exact: true })).toBeVisible();
  await expect(page.getByText('Control test', { exact: true })).toBeVisible();
  await expect(page.getByText(/Check permissions and budget limits with a fixed compute estimate/)).toBeVisible();

  await page.getByRole('checkbox', { name: 'inference', exact: true }).uncheck();
  await page.getByRole('button', { name: 'Save capabilities', exact: true }).click();
  await openDiagnostics(page);
  await expect(submit).toBeDisabled();
  await expect(page.locator('#work-readiness')).toContainText('Enable at least one capability');
  await page.getByRole('checkbox', { name: 'inference', exact: true }).check();
  await page.getByRole('button', { name: 'Save capabilities', exact: true }).click();
  await openDiagnostics(page);
  await expect(submit).toBeEnabled();

  const workUrl = `**${instancePath}/work-requests`;
  let submissions = 0;
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === `${instancePath}/work-requests`) {
      submissions += 1;
    }
  });

  // Reject invalid minutes locally, before creating any work request or usage.
  await page.getByLabel('Compute minutes', { exact: true }).fill('1.5');
  await submit.click();
  await expect(result).toHaveText('Enter a non-negative whole number of compute minutes.');
  expect(submissions).toBe(0);
  await page.reload();
  await openDiagnostics(page);
  await expect(page.getByText('No usage yet.', { exact: true })).toBeVisible();
  await page.getByLabel('Compute daily', { exact: true }).fill('3'); // unsaved owner edit

  // Delay one genuine request, submit again while it is pending, then release it to the real server.
  let releaseResponse!: () => void;
  let sawRequest!: () => void;
  const responseGate = new Promise<void>(resolve => { releaseResponse = resolve; });
  const requestSeen = new Promise<void>(resolve => { sawRequest = resolve; });
  await page.route(workUrl, async route => {
    sawRequest();
    await responseGate;
    await route.continue();
  });
  await submit.click();
  await requestSeen;
  await expect(submit).toBeDisabled();
  await expect(form).toHaveAttribute('aria-busy', 'true');
  await expect(result).toContainText('Checking permissions and budget');
  await form.dispatchEvent('submit');
  expect(submissions).toBe(1);
  releaseResponse();
  await expect(result).toContainText('Result: succeeded.');
  await expect(result).toBeVisible();
  await expect(submit).toBeEnabled();
  await expect(form).not.toHaveAttribute('aria-busy');
  await page.unroute(workUrl);
  // A definite result refreshes all dependent controls without losing its notice or requiring a reload.
  await expect(page.locator('#activity table tbody tr')).toHaveCount(1);
  await expect(page.locator('#activity table tbody tr')).toContainText('0.005000');
  await expect(page.locator('#instance-state > .stat-grid')).toContainText('$0.995000');
  await expect(page.getByText('budget.settled', { exact: true })).toBeVisible();
  await expect(result).toContainText('Result: succeeded.');
  await expect(page.getByLabel('Compute daily', { exact: true })).toHaveValue('3');
  expect(submissions).toBe(1);

  // Losing only the follow-up read must preserve a known work outcome without inviting another POST.
  const detailUrl = `**${instancePath}`;
  await page.route(detailUrl, route => route.abort('failed'));
  await submit.click();
  await expect(result).toContainText('Result: succeeded.');
  await expect(result.getByRole('link')).toBeVisible();
  await expect(submit).toBeDisabled();
  await form.dispatchEvent('submit');
  expect(submissions).toBe(2);
  await page.unroute(detailUrl);
  await result.getByRole('link').click();
  await openDiagnostics(page);
  await expect(submit).toBeEnabled();
  await expect(page.locator('#activity table tbody tr')).toHaveCount(2);
  await expect(page.locator('#instance-state > .stat-grid')).toContainText('$0.990000');

  // An explicitly unknown result must not invite another submission while the owner checks activity.
  await page.route(workUrl, route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ outcome: 'unknown', hold_state: 'unknown' }),
  }));
  await submit.click();
  await expect(result).toContainText('Result: unknown.');
  await expect(result).toContainText('reservation remains held');
  await expect(submit).toBeDisabled();
  await form.dispatchEvent('submit');
  expect(submissions).toBe(3);
  await page.unroute(workUrl);
  await result.getByRole('link').click();
  await openDiagnostics(page);
  await expect(submit).toBeEnabled();
  await expect(page.locator('#activity table tbody tr')).toHaveCount(2);

  // A lost response is uncertain, not a license to retry automatically or claim success.
  await page.route(workUrl, route => route.abort('failed'));
  await submit.click();
  await expect(result).toContainText('The request result could not be verified.');
  await expect(result).toContainText('It may have been processed.');
  await expect(submit).toBeDisabled();
  await form.dispatchEvent('submit');
  expect(submissions).toBe(4);
  await page.unroute(workUrl);
  await result.getByRole('link').click();
  await openDiagnostics(page);
  await expect(submit).toBeEnabled();
  await expect(page.locator('#activity table tbody tr')).toHaveCount(2);

  // A denial can inject a new confirmation: its button must be bound after the automatic refresh.
  await page.getByRole('checkbox', { name: 'gmail.send', exact: true }).check();
  await page.getByRole('checkbox', { name: 'network.fetch', exact: true }).check();
  await page.getByRole('button', { name: 'Save capabilities', exact: true }).click();
  await openDiagnostics(page);
  await page.goto('/connections');
  await page.getByRole('button', { name: 'Connect Gmail', exact: true }).click();
  await expect(page).toHaveURL(/\/connections\?oauth=connected/);
  await page.goto(instancePath);
  await page.getByRole('button', { name: 'Attach', exact: true }).click();
  await openDiagnostics(page);
  await form.locator('select[name="capability"]').selectOption('gmail.send');
  await submit.click();
  await expect(result).toContainText('Result: confirmation_required.');
  await expect(page.getByRole('button', { name: 'Confirm', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Confirm', exact: true }).click();
  await expect(page.getByText('Confirmed once; send it again to execute.', { exact: true })).toBeVisible();
  expect(submissions).toBe(5);

  // The network option carries its selected destination to the real gate, which still rejects private hosts.
  await form.locator('select[name="capability"]').selectOption('network.fetch');
  await expect(page.getByLabel('HTTPS destination', { exact: true })).toBeVisible();
  await page.getByLabel('HTTPS destination', { exact: true }).fill('https://127.0.0.1/private');
  const networkRequest = page.waitForRequest(request => request.method() === 'POST' &&
    new URL(request.url()).pathname === `${instancePath}/work-requests`);
  await submit.click();
  expect((await networkRequest).postDataJSON().destination_url).toBe('https://127.0.0.1/private');
  await expect(result).toContainText('Result: network_denied.');
  await expect(submit).toBeEnabled(); // structurally invalid destinations deny this request without a persistent gate
  await expect(page.locator('#activity table tbody tr')).toHaveCount(2);
  expect(submissions).toBe(6);

  await page.getByRole('button', { name: 'Pause', exact: true }).click();
  await openDiagnostics(page);
  await expect(submit).toBeDisabled();
  await form.dispatchEvent('submit');
  expect(submissions).toBe(6);
  await page.getByRole('button', { name: 'Resume', exact: true }).click();
  await openDiagnostics(page);
  await expect(submit).toBeEnabled();

  async function contained(p: Page, label: string) {
    await expect(p.getByRole('main')).toBeVisible();
    await expect(p.getByRole('heading', { level: 1 })).toBeVisible();
    const nav = p.getByRole('navigation', { name: 'Main navigation', exact: true });
    for (const name of ['Workspace', 'Create an agent', 'Connections']) {
      await expect(nav.getByRole('link', { name, exact: true })).toBeVisible();
    }
    const layout = await p.evaluate(() => {
      const width = document.documentElement.clientWidth;
      const overflow = Array.from(document.querySelectorAll<HTMLElement>(
        'main input:not([type="hidden"]), main textarea, main select, main button',
      )).filter(element => {
        const box = element.getBoundingClientRect();
        return box.width > 0 && (box.left < -1 || box.right > width + 1);
      }).map(element => element.id || element.textContent?.trim() || element.tagName);
      const clippedText = Array.from(document.querySelectorAll<HTMLElement>(
        'main h1, main .agent-card h3, main .created-card h2, main p[style*="white-space"], .breadcrumb span:last-child',
      )).filter(element => {
        const box = element.getBoundingClientRect();
        let left = Math.max(0, box.left);
        let right = Math.min(width, box.right);
        for (let ancestor = element.parentElement; ancestor; ancestor = ancestor.parentElement) {
          if (['hidden', 'clip'].includes(getComputedStyle(ancestor).overflowX)) {
            const clip = ancestor.getBoundingClientRect();
            left = Math.max(left, clip.left);
            right = Math.min(right, clip.right);
          }
        }
        const range = document.createRange();
        range.selectNodeContents(element);
        return Array.from(range.getClientRects()).some(fragment => fragment.left < left - 2 || fragment.right > right + 2);
      }).map(element => ({ element: element.tagName, text: element.textContent?.slice(0, 90) }));
      return { width, documentWidth: document.documentElement.scrollWidth, overflow, clippedText };
    });
    expect(layout.documentWidth, `${label}: page must not scroll horizontally`).toBeLessThanOrEqual(layout.width + 1);
    expect(layout.overflow, `${label}: form controls remain inside the viewport`).toEqual([]);
    expect(layout.clippedText, `${label}: names and instructions remain readable within their containers`).toEqual([]);
  }

  // Dense tables may scroll within their own containers; page content and actionable controls must fit.
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const path of ['/workspace', '/agents/new', instancePath, '/connections', '/chat']) {
      await page.goto(path);
      await contained(page, `${width}px ${path}`);
      if (path === '/agents/new') {
        await expect(page.getByLabel('Name', { exact: true })).toBeVisible();
        await expect(page.getByLabel('Instructions', { exact: true })).toBeVisible();
        await expect(page.getByRole('checkbox', { name: 'inference', exact: true })).toBeVisible();
      } else if (path === instancePath) {
        const sections = page.getByRole('navigation', { name: 'Agent sections', exact: true });
        const sectionNames = await page.locator('#diagnostics').count()
          ? ['Goals & schedule', 'Setup', 'Funding', 'Budget', 'Capabilities', 'Activity']
          : ['Overview', 'Budget', 'Capabilities', 'Activity'];
        for (const name of sectionNames) {
          await expect(sections.getByRole('link', { name, exact: true })).toBeVisible();
        }
        await openDiagnostics(page);
        await contained(page, `${width}px ${path} with diagnostics open`);
        await expect(page.getByLabel('Compute minutes', { exact: true })).toBeVisible();
        await expect(page.getByRole('button', { name: 'Run control test', exact: true })).toBeEnabled();
        const amounts = await page.locator('#budgets table td').evaluateAll(cells => cells
          .filter(cell => /^\d+\.\d{6}$/.test(cell.textContent?.trim() || ''))
          .map(cell => {
            const lineTops = new Set<number>();
            const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
            for (let text = walker.nextNode(); text; text = walker.nextNode()) {
              if (!text.textContent?.trim()) continue;
              const range = document.createRange();
              range.selectNodeContents(text);
              for (const fragment of range.getClientRects()) {
                if (fragment.width > 0) lineTops.add(Math.round(fragment.top));
              }
            }
            return { amount: cell.textContent?.trim(), lines: lineTops.size };
          }));
        expect(amounts.length).toBeGreaterThan(0);
        expect(amounts.filter(amount => amount.lines !== 1), `${width}px: budget amounts remain on one readable line`).toEqual([]);
        const screenshot = testInfo.outputPath(`owner-controls-${width}px.png`);
        await page.screenshot({ path: screenshot, fullPage: true });
        await testInfo.attach(`owner-controls-${width}px`, { path: screenshot, contentType: 'image/png' });
      } else if (path === '/connections') {
        await expect(page.getByRole('button', { name: 'Connect Gmail', exact: true })).toBeVisible();
        await expect(page.getByRole('button', { name: 'Connect Reddit', exact: true })).toBeVisible();
      } else if (path === '/chat') {
        await expect(page.getByLabel('Message', { exact: true })).toBeVisible();
      }
    }
    await page.getByRole('navigation', { name: 'Main navigation', exact: true }).getByRole('link', { name: 'Connections', exact: true }).click();
    await expect(page).toHaveURL(/\/connections$/);
    await page.getByRole('navigation', { name: 'Main navigation', exact: true }).getByRole('link', { name: 'Workspace', exact: true }).click();
    await expect(page).toHaveURL(/\/workspace$/);
  }
  await page.getByRole('link', { name: agentName, exact: true }).click();
});
