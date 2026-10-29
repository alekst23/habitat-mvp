import { test, expect } from '@playwright/test';

test('review scope survives every audit tab and dashboard filter changes', async ({ page }) => {
  const seed = await (await page.request.post('/__test__/seed-session', { data: { fixture: 'owner-a' } })).json();
  const origin = new URL(test.info().project.use.baseURL as string).origin;
  const created = await page.request.post('/app-tools/create_instance', {
    headers: { 'X-CSRF-Token': seed.csrf_token, Origin: origin },
    data: { idempotency_key: `wiz_${Date.now().toString(16).padStart(32, '0')}`, template_id: 'default',
      name: 'Audit navigation', instructions: 'Prepare a report.', enabled_capabilities: [] },
  });
  expect(created.status()).toBe(200);
  const agent = (await created.json()).instance.id;
  await page.goto(`/audit?view=actions&instance_id=${agent}&date_from=2000-01-01&date_to=2000-01-02`);
  for (const name of ['Agent operations', 'Deliverables', 'Purchases', 'Campaigns', 'Costs & statistics', 'Actions']) {
    const tab = page.getByRole('navigation', { name: 'Audit views' }).getByRole('link', { name, exact: true });
    await tab.click();
    await expect(tab).toHaveAttribute('aria-current', 'page');
    const query = new URL(page.url()).searchParams;
    expect(query.get('instance_id')).toBe(agent);
    expect(query.get('date_from')).toBe('2000-01-01');
    expect(query.get('date_to')).toBe('2000-01-02');
    await expect(page.getByLabel('Agent', { exact: true })).toHaveValue(agent);
  }
  await page.getByRole('navigation', { name: 'Audit views' }).getByRole('link', { name: 'Agent operations', exact: true }).click();
  await expect(page.locator('#operations-status')).toContainText('Updated');
  await page.getByLabel('From', { exact: true }).fill('2001-01-01');
  await page.getByLabel('Through', { exact: true }).fill('2001-01-02');
  await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
  await expect(page.locator('#operations-status')).toContainText('Updated');
  await page.getByRole('link', { name: 'Full audit history', exact: true }).click();
  expect(new URL(page.url()).searchParams.get('date_from')).toBe('2001-01-01');
  await page.getByRole('navigation', { name: 'Audit views' }).getByRole('link', { name: 'Deliverables', exact: true }).click();
  await page.getByLabel('Status', { exact: true }).selectOption('draft');
  await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
  for (const name of ['Agent operations', 'Costs & statistics', 'Deliverables']) {
    await page.getByRole('navigation', { name: 'Audit views' }).getByRole('link', { name, exact: true }).click();
  }
  await expect(page.getByLabel('Status', { exact: true })).toHaveValue('draft');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('navigation', { name: 'Audit views' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});
