import { test, expect, Locator, Page } from '@playwright/test';

// A real browser journey over persisted controls and local payment/work fixtures.
// No request interception: the UI drives every configuration and review transition.
test('scheduled work, independent purchases, versioned deliverables and AG Grid Audit', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  expect((await page.request.post('/__test__/seed-session', { data: { fixture: 'owner-a' } })).status()).toBe(200);
  await page.goto('/agents/new');
  await page.getByLabel('Name', { exact: true }).fill('Garden workflow demo');
  const goal = 'Help balcony gardeners join the spring growing pilot.';
  await page.getByLabel('Instructions', { exact: true }).fill(goal);
  await page.getByRole('checkbox', { name: 'inference', exact: true }).check();
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.getByRole('link', { name: /Configure goals & schedule/ }).click();
  const workflowPath = new URL(page.url()).pathname;
  expect(workflowPath).toMatch(/^\/instances\/[0-9a-f-]{36}\/workflow$/);
  const agentPath = workflowPath.replace('/workflow', '');
  await expect(page.getByLabel('Agent goal', { exact: true })).toHaveValue(goal);
  await expect(page.getByRole('button', { name: /Start.*task/ })).toHaveCount(0);
  await page.getByLabel('Context and inputs').fill('Balcony gardeners preparing for spring. Keep the invitation practical and welcoming.');
  await page.locator('#deliverable-name-0').fill('Invitation copy');
  await page.locator('#deliverable-description-0').fill('A short invitation with a clear next step.');
  await page.locator('#deliverable-criteria-0').fill('Names the audience\nExplains one benefit\nIncludes a call to action');
  await page.getByLabel('Schedule', { exact: true }).selectOption('hourly');
  await page.getByLabel('Timezone', { exact: true }).fill('America/New_York');
  await page.getByRole('button', { name: 'Save configuration' }).click();
  await expect(page.getByRole('status')).toContainText('Configuration saved');
  const purchaseJobs = [
    { index: 1, name: 'Pilot launch checklist', scope: 'Three practical launch actions for the growing pilot.', criteria: ['Includes three clear actions', 'Connects the actions to the owner goal'] },
    { index: 2, name: 'Garden outreach plan', scope: 'A community outreach plan for inviting local balcony gardeners.', criteria: ['Identifies two community channels', 'Includes a welcoming invitation'] },
  ];
  for (const { index, name, scope, criteria } of purchaseJobs) {
    await page.getByText('Add another deliverable', { exact: true }).click();
    await page.locator(`#deliverable-name-${index}`).fill(name);
    await page.locator(`#deliverable-description-${index}`).fill(scope);
    await page.locator(`#deliverable-criteria-${index}`).fill(criteria.join('\n'));
    await page.locator(`#purchase-required-${index}`).check();
    // Each save replaces the document. Wait for that response before adding
    // another deliverable or reloading to check the persisted configuration.
    await Promise.all([
      page.waitForEvent('domcontentloaded'),
      page.getByRole('button', { name: 'Save configuration' }).click(),
    ]);
    await expect(page.getByRole('status')).toContainText('Configuration saved');
  }
  await page.reload();
  await expect(page.getByLabel('Agent goal', { exact: true })).toHaveValue(goal);

  await page.getByRole('link', { name: 'Review AICL controls', exact: true }).click();
  for (const label of ['Inference daily', 'Inference monthly', 'Compute daily', 'Compute monthly']) {
    await page.getByLabel(new RegExp(label, 'i')).fill(label.includes('monthly') ? '10' : '1');
  }
  await page.getByRole('button', { name: 'Save limits', exact: true }).click();
  await page.getByRole('checkbox', { name: /Enable purchases/ }).check();
  await page.getByLabel('Total purchase limit (USD)').fill('3');
  await page.getByRole('button', { name: 'Save purchase controls' }).click();
  await page.getByRole('button', { name: 'Add $5.00 with PayPal' }).click();
  await page.getByLabel('PayPal account', { exact: true }).selectOption('demo-buyer');
  await expect(page.getByText('Demo checkout — no real charges.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Pay $5.00 with PayPal', exact: true }).click();
  await page.goto(workflowPath);
  await expect(page.getByText('Service credit: $5.00', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Enable schedule', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Schedule enabled', exact: true })).toBeVisible();
  const nextRun = await page.locator('.workflow-next').innerText();
  expect(nextRun).not.toContain('No upcoming run');

  async function advance(p: Page) {
    await p.goto(workflowPath);
    await p.getByText('Demo controls', { exact: true }).click();
    await p.getByRole('button', { name: 'Advance to next scheduled run' }).click();
    await expect(p.getByRole('status')).toContainText('Scheduled occurrence processed');
  }
  await advance(page);
  const audit = `/audit?instance_id=${agentPath.split('/')[2]}`;
  await page.goto(audit + '&view=deliverables');
  await expect(page.getByRole('link', { name: 'Invitation copy', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Pilot launch checklist', exact: true })).toHaveCount(0);
  await page.goto(audit + '&view=purchases');
  const denied = page.locator('article.workflow-record').filter({ hasText: 'Garden outreach plan' });
  const approved = page.locator('article.workflow-record').filter({ hasText: 'Pilot launch checklist' });
  await expect(page.getByRole('link', { name: 'Review request', exact: true })).toHaveCount(2);
  await expect(page.getByRole('button', { name: 'Approve purchase', exact: true })).toHaveCount(0);
  const approvedRequestUrl = await approved.getByRole('link', { name: 'Review request', exact: true }).getAttribute('href');

  // Audit history exposes the work and its link to the owner decision in Requests.
  async function aboveFold(locator: Locator, description: string) {
    await expect(locator, description).toBeVisible();
    const bounds = await locator.boundingBox();
    expect(bounds, description).not.toBeNull();
    expect(bounds!.y, description).toBeGreaterThanOrEqual(0);
    expect(bounds!.y + bounds!.height, description).toBeLessThanOrEqual(page.viewportSize()!.height);
  }
  for (const viewport of [{ width: 1440, height: 900 }, { width: 717, height: 890 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.goto(audit + '&view=purchases');
    const firstRequest = page.locator('article.workflow-record').first();
    await aboveFold(firstRequest.getByRole('heading', { level: 3 }), `First request title at ${viewport.width}px`);
    if (viewport.width > 390) {
      await aboveFold(firstRequest.getByRole('link', { name: 'Review request', exact: true }), `Review request at ${viewport.width}px`);
    }
    const widths = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: innerWidth }));
    expect(widths.page, `Purchase history at ${viewport.width}px`).toBeLessThanOrEqual(widths.viewport + 1);
    await page.screenshot({ path: `.ctx/scheduled-workflow/purchases-${viewport.width}.png`, fullPage: false });
  }

  // Compact filters keep date ranges usable and retain the selected agent.
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(audit + '&view=purchases');
  await expect(page.getByLabel('Created from', { exact: true })).not.toBeVisible();
  await page.getByText('Date range', { exact: true }).click();
  await page.getByLabel('Created from', { exact: true }).fill('2000-01-01');
  await page.getByLabel('Created through', { exact: true }).fill('2099-12-31');
  await page.getByLabel('Status', { exact: true }).selectOption('pending');
  await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
  await expect(page.locator('article.workflow-record')).toHaveCount(2);
  await expect(page).toHaveURL(/date_from=2000-01-01/);
  await expect(page).toHaveURL(/date_to=2099-12-31/);
  await page.reload();
  await expect(page.getByLabel('Created from', { exact: true })).toHaveValue('2000-01-01');
  await expect(page.getByLabel('Created through', { exact: true })).toHaveValue('2099-12-31');
  await expect(page.getByLabel('Status', { exact: true })).toHaveValue('pending');
  await page.getByLabel('Created from', { exact: true }).fill('2099-01-01');
  await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
  await expect(page.locator('article.workflow-record')).toHaveCount(0);
  await page.getByRole('link', { name: 'Clear filters', exact: true }).click();
  await expect(page.getByLabel('Agent', { exact: true })).toHaveValue(agentPath.split('/')[2]);
  await expect(page.getByLabel('Status', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('Created from', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('Created through', { exact: true })).toHaveValue('');
  await expect(page.locator('article.workflow-record')).toHaveCount(2);

  // The same catalog item must remain traceable to the particular job that requested it.
  const sourceJobPaths: string[] = [];
  const requestedItems: string[] = [];
  for (const job of purchaseJobs) {
    const request = page.locator('article.workflow-record').filter({ hasText: job.name });
    requestedItems.push(await request.getByRole('heading', { level: 3 }).innerText());
    const requestId = await request.getAttribute('id');
    const source = request.getByRole('region', { name: 'Work behind this purchase', exact: true });
    await expect(source).toContainText('Supports deliverable');
    await expect(source).toContainText(job.scope);
    await expect(source).toContainText(/Why requested:\s+\S/);
    const scheduledFor = await source.locator('.audit-source-time').innerText();
    expect(scheduledFor).toMatch(/^Scheduled .+\d{1,2}:\d{2} (AM|PM) \S+$/);
    const sourceLink = request.getByRole('link', { name: 'View source job', exact: true });
    const sourcePath = await sourceLink.getAttribute('href');
    expect(sourcePath).toMatch(/^\/audit\/jobs\/[0-9a-f-]{36}$/);
    sourceJobPaths.push(sourcePath!);
    await sourceLink.click();
    await expect(page.getByRole('heading', { level: 1, name: job.name, exact: true })).toBeVisible();
    await expect(page.getByText(scheduledFor, { exact: true })).toBeVisible();
    await expect(page.getByText(goal, { exact: true })).toBeVisible();
    await expect(page.getByText(job.scope, { exact: true })).toBeVisible();
    for (const criterion of job.criteria) {
      await expect(page.getByText(criterion, { exact: true })).toBeVisible();
    }
    const otherJob = purchaseJobs.find(other => other.index !== job.index)!;
    await expect(page.getByText(otherJob.scope, { exact: true })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Review purchase', exact: true })).toHaveAttribute('href', `/audit?view=purchases&instance_id=${agentPath.split('/')[2]}#${requestId}`);
    await page.getByRole('link', { name: 'Back to purchases', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Purchase history', exact: true })).toBeVisible();
    await expect(page.getByLabel('Agent', { exact: true })).toHaveValue(agentPath.split('/')[2]);
  }
  expect(requestedItems[0]).toBe(requestedItems[1]);
  expect(sourceJobPaths[0]).not.toBe(sourceJobPaths[1]);

  await denied.getByRole('link', { name: 'Review request', exact: true }).click();
  await expect(page).toHaveURL(/\/requests\?selected=purchase%3A/);
  const requestDetail = page.locator('#request-detail');
  await expect(page.locator('.requests-item')).toHaveCount(2);
  await expect(requestDetail).toContainText('Garden outreach plan');
  await expect(requestDetail.getByRole('link', { name: 'View job', exact: true })).toHaveAttribute('href', sourceJobPaths[1]);
  await requestDetail.getByRole('button', { name: 'Decline purchase', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Request declined');
  await expect(requestDetail).toContainText('No merchant payment was made');
  await expect(page.locator('.requests-item')).toHaveCount(1);
  await expect(requestDetail.getByRole('button', { name: 'Approve purchase', exact: true })).toHaveCount(0);
  await page.goto(approvedRequestUrl!);
  await expect(requestDetail).toContainText('Pilot launch checklist');
  await expect(requestDetail.getByRole('link', { name: 'View job', exact: true })).toHaveAttribute('href', sourceJobPaths[0]);
  await expect(requestDetail).toContainText('Approval covers this exact seller, purchase and total');
  await expect(requestDetail).toContainText('approval alone does not make a payment');
  await requestDetail.getByRole('radio', { name: 'Continue on schedule', exact: true }).check();
  await requestDetail.getByRole('button', { name: 'Approve purchase', exact: true }).click();
  const orderUrl = page.url();
  await expect(page.getByRole('link', { name: 'View source job', exact: true })).toHaveAttribute('href', sourceJobPaths[0]);
  await expect(page.getByText(purchaseJobs[0].scope, { exact: true })).toBeVisible();
  await expect(page.getByText('PayPal · Demo buyer', { exact: true })).toBeVisible();
  await expect(page.getByLabel('PayPal account', { exact: true })).not.toBeVisible();
  await expect(page.getByText(/Continue the waiting work at the next eligible scheduled run/)).toBeVisible();
  await page.getByText('Payment options', { exact: true }).click();
  await page.getByRole('button', { name: 'Mark as pending' }).click();
  await expect(page).toHaveURL(orderUrl);
  await page.goto(approvedRequestUrl!);
  await expect(requestDetail).toContainText('Payment is pending');
  await expect(requestDetail.getByRole('link', { name: 'Review pending payment', exact: true })).toHaveAttribute('href', new URL(orderUrl).pathname);
  await expect(requestDetail.getByRole('button', { name: 'Approve purchase', exact: true })).toHaveCount(0);
  await page.goto(audit + '&view=deliverables');
  await expect(page.getByRole('link', { name: 'Pilot launch checklist', exact: true })).toHaveCount(0);
  await page.goto(orderUrl);
  await page.getByRole('button', { name: /^Pay \$[\d.]+ with PayPal$/ }).click();
  await expect(page).toHaveURL(/\/requests\?selected=purchase%3A/);
  await expect(page.getByRole('status')).toContainText('Payment confirmed');
  await expect(requestDetail).toContainText('Payment completed');
  await expect(page.locator('.requests-item')).toHaveCount(0);
  await page.goto(audit + '&view=deliverables');
  await expect(page.getByRole('link', { name: 'Pilot launch checklist', exact: true })).toHaveCount(0);
  await advance(page);
  await page.goto(audit + '&view=deliverables');
  await page.getByRole('link', { name: 'Pilot launch checklist', exact: true }).click();
  const approvedOutputPath = new URL(page.url()).pathname;
  await page.goto(audit + '&view=purchases');
  await expect(approved.getByRole('link', { name: 'View resulting deliverable', exact: true })).toHaveAttribute('href', approvedOutputPath);
  await approved.getByRole('link', { name: 'View resulting deliverable', exact: true }).click();
  await expect(page.getByRole('link', { name: 'View source job', exact: true })).toHaveAttribute('href', sourceJobPaths[0]);
  await page.getByRole('link', { name: 'View source job', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Pilot launch checklist', exact: true })).toBeVisible();
  const linkedOutput = page.locator(`a[href="${approvedOutputPath}"]`);
  await expect(linkedOutput).toBeVisible();
  await linkedOutput.click();
  await expect(page.getByRole('heading', { name: 'Completion criteria', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Accept deliverable' }).click();
  await expect(page.getByText('Accepted.', { exact: true })).toBeVisible();

  await page.goto(audit + '&view=deliverables');
  await page.getByRole('link', { name: 'Invitation copy', exact: true }).click();
  const originalUrl = page.url();
  await page.getByLabel('Feedback for a revision').fill('Make the invitation warmer and specify a Friday signup deadline.');
  await page.getByRole('button', { name: 'Request changes', exact: true }).click();
  await expect(page.getByText('Revision requested.', { exact: true })).toBeVisible();
  await advance(page);
  await page.goto(audit + '&view=deliverables');
  await page.getByRole('link', { name: 'Invitation copy', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Version 1', exact: true })).toHaveAttribute('href', new URL(originalUrl).pathname);
  await expect(page.getByRole('link', { name: 'Version 2', exact: true })).toBeVisible();
  await expect(page.locator('.workflow-output')).toContainText('Friday signup deadline');
  await page.getByRole('button', { name: 'Accept deliverable' }).click();
  await page.screenshot({ path: '.ctx/scheduled-workflow/deliverable-desktop.png', fullPage: true });

  await page.goto(audit + '&view=costs');
  await expect(page.locator('.ag-root-wrapper')).toBeVisible();
  await expect(page.getByRole('columnheader', { name: /Amount/ })).toBeVisible();
  await page.screenshot({ path: '.ctx/scheduled-workflow/audit-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of [workflowPath, approvedRequestUrl!, audit + '&view=purchases', audit + '&view=deliverables', audit + '&view=costs']) {
    await page.goto(path);
    const widths = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: innerWidth }));
    expect(widths.page, path).toBeLessThanOrEqual(widths.viewport + 1);
    if (path.startsWith('/audit?')) {
      const applyBounds = await page.getByRole('button', { name: 'Apply filters', exact: true }).boundingBox();
      expect(applyBounds, `${path} filter action`).not.toBeNull();
      expect(applyBounds!.height, `${path} filter action height`).toBeLessThanOrEqual(48);
      expect(applyBounds!.width, `${path} filter action width`).toBeGreaterThanOrEqual(95);
    }
    if (path.endsWith('&view=costs')) {
      const pager = page.locator('#audit-cost-grid .ag-paging-page-summary-panel');
      await expect(pager).toBeVisible();
      const pagerBounds = await pager.boundingBox();
      const gridBounds = await page.locator('#audit-cost-grid').boundingBox();
      expect(pagerBounds!.x, 'Mobile grid paging controls start inside the grid').toBeGreaterThanOrEqual(gridBounds!.x);
      expect(pagerBounds!.x + pagerBounds!.width, 'Mobile grid paging controls fit inside the grid').toBeLessThanOrEqual(gridBounds!.x + gridBounds!.width);
    }
  }
  await page.screenshot({ path: '.ctx/scheduled-workflow/audit-mobile.png', fullPage: true });
  await page.goto(workflowPath);
  await page.getByRole('button', { name: 'Pause schedule', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Schedule paused', exact: true })).toBeVisible();
  await page.getByText('Demo controls', { exact: true }).click();
  await expect(page.getByRole('button', { name: 'Advance to next scheduled run' })).toBeDisabled();
  expect(errors).toEqual([]);
});
