import { test, expect, Page } from '@playwright/test';

// E11-5.AC1 production-wired journey series. NO seeded session: every owner signs in through the real magic-link
// flow of `python -m aicl.test_server` (fakes only at provider, executor, chat model, email and clock). Covers
// wizard and chat creation with equivalent results, activation, limits, capability, attachment through the fake
// OAuth page, simulated work settled and shown in usage, over-limit gating with its reason, Re-check and clear
// (gate stays with gate_unresolved while the limit is zero, clears once all four limits are positive),
// confirmation-required send denied then confirmed once, executed once and denied on replay (confirmation_used),
// revocation detaching and gating, owner-domain add/remove, another tenant's isolation and the redacted audit.
test('real sign-in, owner pages, gating, confirmation, revocation, isolation and redacted audit',
  { annotation: { type: 'ac', description: 'E11-5.AC1' } }, async ({ page, browser, request }) => {

  async function signIn(p: Page, email: string) {
    await p.goto('/');
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

  async function csrf(p: Page): Promise<string> {
    return (await p.locator('input[name="csrf_token"]').first().inputValue());
  }

  // simulated work through the same HTTP entry point the page form uses (JSON + X-CSRF-Token)
  async function work(p: Page, instanceId: string, workId: string, capability: string, payload: object) {
    return p.request.post(`/instances/${instanceId}/work-requests`, {
      headers: { 'X-CSRF-Token': await csrf(p) },
      data: { work_id: workId, capability, payload, estimate: { inference_input_tokens: 0, inference_output_tokens: 0, compute_minutes: 2 } },
    });
  }

  await signIn(page, 'e5-owner@example.com');

  // wizard creation, then chat creation of the same Default instance model
  await page.getByRole('link', { name: /Create with wizard/i }).click();
  await page.getByLabel(/^name/i).fill('Same Helper');
  await page.getByLabel(/instructions/i).fill('Answer politely');
  await page.getByRole('checkbox', { name: /^inference$/i }).check();
  await page.getByRole('button', { name: /create/i }).click();
  await expect(page.getByText(/not active until you activate it/i)).toBeVisible();

  await page.goto('/chat');
  async function say(text: string) {
    await page.getByRole('textbox', { name: /message/i }).fill(text);
    await page.getByRole('button', { name: /send/i }).click();
  }
  for (const t of ['hello', 'Same Helper', 'Answer politely', 'inference', 'yes']) await say(t);
  for (let i = 0; i < 3 && !(await page.getByText(/not active until you activate it|draft/i).count()); i++) await say('yes');

  await page.goto('/workspace');
  await expect(page.getByRole('link', { name: 'Same Helper' })).toHaveCount(2);  // wizard and chat rows, both draft
  const rows = page.getByRole('listitem').filter({ hasText: 'Same Helper' });
  await expect(rows.nth(0)).toContainText(/draft/i);
  await expect(rows.nth(1)).toContainText(/draft/i);
  expect(await rows.nth(0).innerText()).toEqual(await rows.nth(1).innerText());  // equivalent result across surfaces

  // instance detail: lifecycle, activation, capability, limits, domain
  await page.getByRole('link', { name: 'Same Helper' }).first().click();
  const instanceId = page.url().match(/\/instances\/([0-9a-f-]{36})/)![1];
  await page.goto(`/instances/${instanceId}`);
  await expect(page.locator('.simulation-note')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Boundaries & activity' })).toBeVisible();
  await page.getByRole('button', { name: /^activate$/i }).click();
  await expect(page.getByText(/active/i).first()).toBeVisible();

  await page.getByLabel(/^network\.fetch domain|domain/i).first().fill('example.com');
  await page.getByRole('button', { name: /add domain/i }).click();
  await expect(page.getByText('example.com').first()).toBeVisible();
  await page.getByRole('button', { name: /remove domain|remove example\.com/i }).first().click();
  await expect(page.getByText('example.com')).toHaveCount(0);

  // over-limit: zero limits are exhausted even for a zero-cost category => gated with its reason
  const denied = await work(page, instanceId, 'work_' + '1'.repeat(32), 'inference', { sim: { compute_minutes: 2 } });
  expect(denied.status()).toBe(403);
  expect((await denied.json()).reason).toBe('budget_exhausted');
  await page.reload();
  await expect(page.getByText(/budget_exhausted/)).toBeVisible();

  await page.getByRole('button', { name: /re-check and clear/i }).click();
  await expect(page.getByText(/gate_unresolved/)).toBeVisible();   // the specific denial, not prompt-like text
  await expect(page.getByText(/budget_exhausted/)).toBeVisible();  // the gate stays

  async function setLimits(inferenceDaily: string, inferenceMonthly: string, computeDaily: string, computeMonthly: string) {
    await page.getByLabel(/inference daily/i).fill(inferenceDaily);
    await page.getByLabel(/inference monthly/i).fill(inferenceMonthly);
    await page.getByLabel(/compute daily/i).fill(computeDaily);
    await page.getByLabel(/compute monthly/i).fill(computeMonthly);
    await page.getByRole('button', { name: /save limits/i }).click();
  }
  await setLimits('-1', '1', '1', '1');
  await expect(page.getByText(/inference_daily_micro_usd|out_of_range|invalid/i).first()).toBeVisible();  // truthful field error
  await setLimits('1', '10', '1', '10');
  await expect(page.getByText('10.000000').first()).toBeVisible();  // USD with six decimals
  await expect(page.getByRole('button', { name: /re-check and clear/i })).toHaveCount(0);
  await expect(page.getByText(/budget_exhausted/)).toHaveCount(0);  // gate cleared once all four limits are positive

  // simulated work settled and shown in usage; allow-listed budget.* audit appears, no body/token/secret_ref
  const ok = await work(page, instanceId, 'work_' + '2'.repeat(32), 'inference', { sim: { compute_minutes: 2 }, note: 'PAYLOAD-BODY-MUST-NOT-RENDER' });
  expect(ok.status()).toBe(200);
  await page.reload();
  await expect(page.getByText('0.010000').first()).toBeVisible();  // 2 compute minutes at 5000 micro-USD/minute
  await expect(page.getByRole('heading', { name: 'Usage', exact: true })).toBeVisible();
  await expect(page.getByText(/budget\.settled/)).toBeVisible();
  const detail = await page.content();
  for (const hidden of ['PAYLOAD-BODY-MUST-NOT-RENDER', 'secret_ref', 'access_token', 'refresh_token', 'fake-code']) {
    expect(detail).not.toContain(hidden);
  }

  // capability + attachment through the fake OAuth page
  await page.getByRole('checkbox', { name: /^gmail\.send$/i }).check();
  await page.getByRole('button', { name: /save capabilit/i }).click();
  await page.goto('/connections');
  await page.getByRole('button', { name: /connect gmail/i }).click();  // begin OAuth -> fake provider page -> callback
  await expect(page).toHaveURL(/\/connections\?oauth=connected/);
  await expect(page.getByText(/gmail/i).first()).toBeVisible();
  await page.goto(`/instances/${instanceId}`);
  await page.getByRole('button', { name: /attach/i }).first().click();
  await expect(page.getByText(/attached|active/i).first()).toBeVisible();

  // confirmation-required send: denied, confirmed once, executed once, replay denied with confirmation_used
  const send = { to: 'friend@example.com', body: 'hello' };
  const first = await work(page, instanceId, 'work_' + '3'.repeat(32), 'gmail.send', send);
  expect(first.status()).toBe(403);
  expect((await first.json()).reason).toBe('confirmation_required');
  await page.reload();
  await page.getByRole('button', { name: /^confirm/i }).click();
  await expect(page.getByText(/confirmed/i).first()).toBeVisible();
  const sent = await work(page, instanceId, 'work_' + '3'.repeat(32), 'gmail.send', send);
  expect(sent.status()).toBe(200);
  expect((await sent.json()).outcome).toBe('succeeded');
  const replay = await work(page, instanceId, 'work_' + '4'.repeat(32), 'gmail.send', send);  // same payload, new work_id
  expect(replay.status()).toBe(403);
  expect((await replay.json()).reason).toBe('confirmation_used');

  // revocation detaches and gates; revocation does not undo what already happened
  await page.goto('/connections');
  await expect(page.getByText(/does not undo actions already taken/i)).toBeVisible();
  await page.getByRole('button', { name: /revoke/i }).first().click();
  await expect(page.getByText(/revoked/i).first()).toBeVisible();
  await page.goto(`/instances/${instanceId}`);
  await expect(page.getByText(/connection_revoked/)).toBeVisible();

  // another tenant's isolation, with its own non-empty list
  const second = await browser.newContext({ baseURL: new URL(page.url()).origin });
  const other = await second.newPage();
  await signIn(other, 'e5-other@example.com');
  await expect(other.getByText('Same Helper')).toHaveCount(0);
  expect((await other.request.get(`/instances/${instanceId}`)).status()).toBe(404);
  await other.getByRole('link', { name: /Create with wizard/i }).click();
  await other.getByLabel(/^name/i).fill('Other Helper');
  await other.getByRole('button', { name: /create/i }).click();
  await other.goto('/workspace');
  await expect(other.getByText('Other Helper')).toHaveCount(1);
  await expect(other.getByText('Same Helper')).toHaveCount(0);
  await second.close();
});
