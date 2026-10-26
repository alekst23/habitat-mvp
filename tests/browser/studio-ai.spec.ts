import { test, expect } from '@playwright/test';

// The actual official bundle and application UI run with legacy opt-ins injected.
// All model transport is blocked by the test as an additional no-charge guard.
test('Studio AI stays absent despite legacy page flags and runtime globals', async ({ page }) => {
  const requests: string[] = [];
  const mutations: string[] = [];
  const errors: string[] = [];
  await page.setViewportSize({ width: 1440, height: 1000 });
  expect((await page.request.post('/__test__/seed-session', { data: { fixture: 'owner-b' } })).status()).toBe(200);
  const beforeState = await (await page.request.get('/audit/studio/state')).json();
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path === '/audit/studio/ai' || path === '/static/vendor/ag-studio-runtime.js') requests.push(path);
    if (!['GET', 'HEAD'].includes(request.method())) mutations.push(`${request.method()} ${path}`);
  });
  await page.addInitScript(() => {
    (window as any).legacyStudioAdapterCalls = 0;
    (window as any).HabitatStudioRuntime = {
      createHabitatAdapter() {
        (window as any).legacyStudioAdapterCalls += 1;
        throw new Error('The retired Studio model adapter must never be called');
      },
    };
  });
  await page.route(url => url.pathname === '/audit/studio', async route => {
    const response = await route.fetch();
    const html = await response.text();
    expect(html).not.toContain('data-ai-enabled');
    expect(html).not.toContain('ag-studio-runtime.js');
    expect(html).not.toContain('operations-open-ai');
    await route.fulfill({ response, body: html.replace('id="operations"', 'id="operations" data-ai-enabled="true"') });
  });
  await page.route(url => url.pathname === '/audit/studio/ai' || url.origin !== 'http://127.0.0.1:4173', route => route.abort());

  await page.goto('/audit/studio');
  await expect(page.locator('#operations-status')).toContainText('Updated');
  await expect(page.locator('#operations')).toHaveAttribute('data-ai-enabled', 'true');
  await expect(page.locator('#operations-studio')).toContainText('Jobs & outcomes');
  await expect(page.getByRole('button', { name: 'AI Assistant', exact: true })).toHaveCount(0);
  await expect(page.getByPlaceholder('Ask the AI Assistant...')).toHaveCount(0);
  await expect(page.locator('#operations-open-ai')).toHaveCount(0);

  await page.getByRole('button', { name: 'Edit layout', exact: true }).click();
  await expect(page.locator('#operations-studio').getByRole('button', { name: 'Compose', exact: true })).toBeVisible();
  await expect(page.locator('#operations-studio').getByRole('button', { name: 'Data', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'AI Assistant', exact: true })).toHaveCount(0);
  await expect(page.getByPlaceholder('Ask the AI Assistant...')).toHaveCount(0);
  await page.getByRole('button', { name: 'Done editing', exact: true }).click();
  await page.getByRole('button', { name: /Spending without accepted work/ }).click();
  await expect(page.locator('#operations-layout-status')).toContainText('predefined rule');
  await page.getByRole('button', { name: 'Refresh data', exact: true }).click();
  await expect(page.locator('#operations-status')).toContainText('Updated');

  expect(await page.evaluate(() => (window as any).legacyStudioAdapterCalls)).toBe(0);
  expect(requests).toEqual([]);
  expect(mutations).toEqual([]);
  expect(errors).toEqual([]);
  expect(await (await page.request.get('/audit/studio/state')).json()).toEqual(beforeState);
});
