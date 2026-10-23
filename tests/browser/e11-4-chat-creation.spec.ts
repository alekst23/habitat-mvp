import { test, expect } from '@playwright/test';

// E11-4.AC1 browser journey: sign in through the E11-1 seeded test session (test composition only: the server is
// started with AICL_TEST_MODE=1 and AICL_ENVIRONMENT=test; fixture owners are owner-a and owner-b), open the
// built-in chat from the empty workspace, hit a truthful validation denial (oversized instructions: the chat
// asks for the corrected field and creates nothing), then create a draft instance through the slot-filling
// conversation. A second seeded owner does not see it. No real magic link is used here (E11-3 proves that).
test('seeded sign-in, chat denial for invalid instructions, then chat creates a draft instance',
  { annotation: { type: 'ac', description: 'E11-4.AC1' } }, async ({ page, browser }) => {

  const seeded = await page.request.post('/__test__/seed-session', { data: { fixture: 'owner-a' } });
  expect(seeded.status()).toBe(200);

  await page.goto('/workspace');
  await expect(page.getByRole('link', { name: /Create with chat/i })).toBeVisible();
  await page.getByRole('link', { name: /Create with chat/i }).click();
  await expect(page).toHaveURL(/\/chat/);

  async function say(text: string) {
    await page.getByRole('textbox', { name: /message/i }).fill(text);
    await page.getByRole('button', { name: /send/i }).click();
  }

  await say('I want a new agent');
  await expect(page.getByText(/name/i).last()).toBeVisible();
  await say('Chat Helper');
  await say('x'.repeat(4001)); // longer than the 4000 character instructions limit
  await say('inference');
  await say('yes');
  // truthful denial: the chat names the offending field and asks for it again
  await expect(page.getByText(/instructions/i).last()).toBeVisible();

  await say('Answer politely');
  await say('inference');
  for (let i = 0; i < 3; i++) {
    await say('yes');
    if (await page.getByText(/draft|not active until you activate it/i).count()) break;
  }
  await expect(page.getByText(/draft|not active until you activate it/i).first()).toBeVisible();

  // exactly one instance exists: the denied attempt created nothing
  await page.goto('/workspace');
  await expect(page.getByText('Chat Helper')).toHaveCount(1);

  // another seeded owner has their own empty workspace and cannot see it
  const second = await browser.newContext({ baseURL: new URL(page.url()).origin });
  const secondPage = await second.newPage();
  expect((await secondPage.request.post('/__test__/seed-session', { data: { fixture: 'owner-b' } })).status()).toBe(200);
  await secondPage.goto('/workspace');
  await expect(secondPage.getByRole('link', { name: /Create with chat/i })).toBeVisible();
  await expect(secondPage.getByText('Chat Helper')).toHaveCount(0);
  await second.close();
});
