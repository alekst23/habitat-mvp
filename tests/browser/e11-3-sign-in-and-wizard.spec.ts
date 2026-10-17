import { test, expect } from '@playwright/test';

// E11-3.AC1 browser journey: the REAL magic-link flow (no seeded session) through landing, sign-in with the
// captured link, wizard creation of a draft instance, a field-error denial and, for a second user, the empty
// workspace. Needs GET /__test__/last-magic-link?email= (added by E11-3; present only in the test composition).
test('real magic-link sign-in, wizard draft creation, field-error denial and a second user empty workspace',
  { annotation: { type: 'ac', description: 'E11-3.AC1' } }, async ({ page, browser, request }) => {

  async function signIn(p: typeof page, email: string) {
    await p.goto('/');
    await expect(p.getByRole('link', { name: /Create your first agent/i })).toBeVisible();
    await p.getByRole('link', { name: /Create your first agent/i }).click();
    await p.getByLabel(/email/i).fill(email);
    await p.getByRole('button', { name: /send|link|sign in/i }).click();
    await expect(p.getByText(/a link is on its way/i)).toBeVisible();
    const captured = await request.get('/__test__/last-magic-link', { params: { email } });
    expect(captured.status()).toBe(200);
    const link = (await captured.text()).match(/https?:\/\/[^\s"'<>]+\/auth\/verify\?token=[A-Za-z0-9_-]+/);
    expect(link).not.toBeNull();
    await p.goto(link![0].replace(/^https?:\/\/[^/]+/, ''));
    await p.getByRole('button', { name: /confirm|sign in|continue/i }).click();
    await expect(p).toHaveURL(/\/workspace/);
  }

  await signIn(page, 'first-owner@example.com');
  await expect(page.getByRole('link', { name: /Create with wizard/i })).toBeVisible();
  await expect(page.getByRole('link', { name: /Create with chat/i })).toBeVisible();
  await page.getByRole('link', { name: /Create with wizard/i }).click();

  // field-error denial: an empty name is refused truthfully and nothing is created
  await page.getByLabel(/instructions/i).fill('Answer politely');
  await page.getByRole('button', { name: /create/i }).click();
  await expect(page.getByText(/name/i).first()).toBeVisible();
  await expect(page.getByText(/not active until you activate it/i)).toHaveCount(0);

  await page.getByLabel(/^name/i).fill('Browser Helper');
  await page.getByRole('button', { name: /create/i }).click();
  await expect(page.getByText(/not active until you activate it/i)).toBeVisible();
  await expect(page.getByText('Browser Helper')).toBeVisible();

  // a second user has their own empty workspace and does not see the first user's instance
  const second = await browser.newContext({ baseURL: 'http://127.0.0.1:4173' });
  const secondPage = await second.newPage();
  await signIn(secondPage, 'second-owner@example.com');
  await expect(secondPage.getByRole('link', { name: /Create with wizard/i })).toBeVisible();
  await expect(secondPage.getByText('Browser Helper')).toHaveCount(0);
  await second.close();
});
