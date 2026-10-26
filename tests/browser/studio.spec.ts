import { test, expect, type Page } from '@playwright/test';

async function expectSpendingChart(page: Page) {
  const chart = page.locator('.ag-studio-layout-widget').filter({ has: page.getByText('Spending by agent', { exact: true }) });
  await expect(chart.getByRole('figure')).toBeVisible();
  await expect(chart.getByRole('figure')).toHaveAttribute('aria-label', /3 series/);
  await expect(chart.locator('.ag-studio-widget-loading')).toBeHidden();
  await expect(chart.locator('canvas').first()).toBeVisible();
}

// Real application routes, durable SQLite records and the official Studio
// runtime. Payment and scheduled work are explicitly the local fixtures.
test('Agent Operations links costs and work, filters consistently, and persists a layout', async ({ page }) => {
  test.setTimeout(90_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    if (response.status() >= 500) errors.push(`${response.status()} ${response.url()}`);
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.request.post('/__test__/seed-session', { data: { fixture: 'owner-a' } });
  await page.goto('/agents/new');
  const name = `Studio review ${Date.now()}`;
  await page.getByLabel('Name', { exact: true }).fill(name);
  await page.getByLabel('Instructions', { exact: true }).fill('Prepare a practical neighborhood garden checklist.');
  await page.getByRole('checkbox', { name: 'inference', exact: true }).check();
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.getByRole('link', { name: /Configure goals & schedule/ }).click();
  const workflowPath = new URL(page.url()).pathname;
  const agentId = workflowPath.split('/')[2];
  await page.locator('#deliverable-name-0').fill('Garden checklist');
  await page.locator('#deliverable-description-0').fill('A short useful checklist.');
  await page.locator('#deliverable-criteria-0').fill('Includes three clear actions');
  await page.getByLabel('Schedule', { exact: true }).selectOption('hourly');
  await page.getByRole('button', { name: 'Save configuration' }).click();
  await expect(page.getByRole('status')).toContainText('Configuration saved');
  await page.getByRole('link', { name: 'Review AICL controls', exact: true }).click();
  for (const label of ['Inference daily', 'Inference monthly', 'Compute daily', 'Compute monthly']) {
    await page.getByLabel(new RegExp(label, 'i')).fill(label.includes('monthly') ? '10' : '1');
  }
  await page.getByRole('button', { name: 'Save limits', exact: true }).click();
  await page.getByRole('button', { name: 'Add $5.00 with PayPal' }).click();
  await page.getByLabel('PayPal account', { exact: true }).selectOption('demo-buyer');
  await page.getByRole('button', { name: 'Pay $5.00 with PayPal', exact: true }).click();
  await page.goto(workflowPath);
  await page.getByRole('button', { name: 'Enable schedule', exact: true }).click();
  await page.getByText('Demo controls', { exact: true }).click();
  await page.getByRole('button', { name: 'Advance to next scheduled run' }).click();
  await expect(page.getByRole('status')).toContainText('Scheduled occurrence processed');

  const dashboard = `/audit/studio?instance_id=${agentId}`;
  await page.goto(dashboard);
  await expect(page.locator('#operations-status')).toContainText('Updated');
  await expect(page.locator('#operations-studio')).toContainText('Jobs & outcomes');
  await expect(page.locator('#operations-studio')).toContainText('Scenario data');
  await expect(page.locator('.operations-attention')).toContainText('Garden checklist');
  const composePanel = page.locator('#operations-studio').getByRole('button', { name: 'Compose', exact: true });
  const dataPanel = page.locator('#operations-studio').getByRole('button', { name: 'Data', exact: true });
  await expect(composePanel).toBeHidden();
  await expect(dataPanel).toBeHidden();
  await page.getByRole('button', { name: 'Edit layout', exact: true }).click();
  await expect(composePanel).toBeVisible();
  await expect(dataPanel).toBeVisible();
  await page.getByRole('button', { name: 'Done editing', exact: true }).click();
  await expect(composePanel).toBeHidden();
  await expect(dataPanel).toBeHidden();
  await expect(page.locator('#metric-work')).toHaveText('1 / 0');
  const snapshot = await (await page.request.get(`/audit/studio/data?instance_id=${agentId}`)).json();
  expect(snapshot.jobs).toHaveLength(1);
  expect(snapshot.totals.inference_usd).toBeGreaterThan(0);
  await expect(page.locator('#metric-inference')).not.toHaveText('$0.00');
  const credit = await page.locator('#metric-credit').innerText();
  const source = page.locator('#operations-studio a.operations-evidence-link').filter({ hasText: 'Open source' }).first();
  await expect(source).toBeVisible();
  const sourcePath = await source.getAttribute('href');
  expect(sourcePath).toMatch(/^\/(audit\/jobs|commerce\/orders)\//);
  await source.click();
  await expect(page).toHaveURL(new RegExp(sourcePath!.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  await page.goto(dashboard);
  await expect(page.locator('#operations-status')).toContainText('Updated');

  await page.getByLabel('From', { exact: true }).fill('2000-01-01');
  await page.getByLabel('Through', { exact: true }).fill('2000-01-02');
  await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
  await expect(page.locator('#metric-inference')).toHaveText('$0.00');
  await expect(page.locator('#metric-work')).toHaveText('0 / 0');
  await expect(page.locator('#metric-credit')).toHaveText(credit);
  await page.getByRole('button', { name: 'Clear', exact: true }).click();
  await page.getByLabel('Agent', { exact: true }).selectOption(agentId);
  await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
  await expect(page.locator('#metric-work')).toHaveText('1 / 0');
  await page.getByRole('button', { name: /Spending without accepted work/ }).click();
  await expect(page.locator('#operations-preset')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#operations-layout-status')).toContainText('Preset applied');
  await page.getByRole('button', { name: /Spending without accepted work/ }).click();
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();
  await expect(page.locator('#operations-layout-status')).toContainText('Layout saved');
  const saved = await (await page.request.get('/audit/studio/state')).json();
  expect(saved.version).toBeGreaterThan(0);
  expect(saved.state.pages[0].widgets).toHaveProperty('attention');
  await page.reload();
  await expect(page.locator('#operations-layout-status')).toContainText('saved layout');
  await expect(page.locator('#operations-studio')).toContainText('Scenario data');
  await expectSpendingChart(page);
  await page.getByRole('heading', { name: 'Agent operations', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Skip to content', exact: true })).not.toBeInViewport();
  await page.screenshot({ path: '.ctx/studio/desktop.png', fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.locator('#operations-status')).toContainText('Updated');
  await expect(page.getByRole('button', { name: 'Apply filters', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Save view', exact: true }).click();
  await expect(page.locator('#operations-layout-status')).toContainText('desktop widget arrangement is preserved');
  const mobileSaved = await (await page.request.get('/audit/studio/state')).json();
  expect(mobileSaved.state.pages[0].widgetLayout).toEqual(saved.state.pages[0].widgetLayout);
  await expectSpendingChart(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.getByRole('heading', { name: 'Agent operations', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Skip to content', exact: true })).not.toBeInViewport();
  await page.screenshot({ path: '.ctx/studio/mobile.png', fullPage: true });
  expect(errors).toEqual([]);
});
