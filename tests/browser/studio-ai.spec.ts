import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Script only the provider replies. The served Studio bundle, its native AI
// harness, client-side schema tool and Habitat transport all run unchanged.
test('native Studio assistant reads the real schema through the bounded proxy contract', async ({ page }) => {
  const finalText = 'Scripted model inspected the four Habitat data tables. No approvals or payments were changed.';
  const callId = 'scripted-schema-call';
  const requests: any[] = [];
  const mutations: string[] = [];
  const errors: string[] = [];
  let providerBytes: number[] = [];
  await page.setViewportSize({ width: 1440, height: 1000 });
  expect((await page.request.post('/__test__/seed-session', { data: { fixture: 'owner-b' } })).status()).toBe(200);
  const beforeState = await (await page.request.get('/audit/studio/state')).json();
  const beforeData = await (await page.request.get('/audit/studio/data')).json();
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (!['GET', 'HEAD'].includes(request.method()) && path !== '/audit/studio/ai') mutations.push(`${request.method()} ${path}`);
  });
  await page.route(url => url.pathname === '/audit/studio', async route => {
    const response = await route.fetch();
    const html = await response.text();
    expect(html).toContain('data-ai-enabled="false"');
    // Enable only the native client harness. The real server stays AI-disabled,
    // so a missed scripted route cannot make a billable provider request.
    await route.fulfill({ response, body: html.replace('data-ai-enabled="false"', 'data-ai-enabled="true"') });
  });
  await page.route(url => url.pathname === '/audit/studio/ai', async route => {
    const request = route.request();
    expect(request.method()).toBe('POST');
    expect(request.headers()['x-csrf-token']).toBeTruthy();
    requests.push(request.postDataJSON());
    const output = requests.length === 1 ? [{
      id: 'scripted-tool-item', kind: 'output', type: 'function_call', status: 'completed',
      callId, name: 'view_schema', arguments: '{}',
    }] : [{
      id: 'scripted-answer', kind: 'output', type: 'message', role: 'assistant', status: 'completed',
      content: [{ type: 'text', text: finalText, annotations: [] }],
    }];
    await route.fulfill({ json: { id: `scripted-response-${requests.length}`, createdAt: 1, status: 'completed', output } });
  });

  try {
    await page.goto('/audit/studio');
    await expect(page.locator('#operations-status')).toContainText('Updated');
    await page.getByRole('button', { name: 'AI Assistant', exact: true }).click();
    await expect(page.getByPlaceholder('Ask the AI Assistant...')).toBeVisible();
    await expect(page.getByText('Find work needing attention', { exact: true })).toBeVisible();
    await page.getByText('Explain this spending', { exact: true }).click();
    await expect(page.getByText(finalText, { exact: true })).toBeVisible();
    expect(requests).toHaveLength(2);
    expect(new Set(requests.map(item => item.request_id)).size).toBe(2);
    for (const envelope of requests) {
      expect(envelope.request_id).toMatch(/^[0-9a-f]{8}-[0-9a-f-]{27}$/);
      expect(Buffer.byteLength(JSON.stringify(envelope))).toBeLessThan(48_000);
    }
    expect(requests[0].request.tools).toEqual(expect.arrayContaining([expect.objectContaining({ name: 'view_schema' })]));
    expect(requests[0].request.input).toEqual(expect.arrayContaining([
      expect.objectContaining({ role: 'user', content: expect.arrayContaining([expect.objectContaining({ text: expect.stringContaining('Explain spending and its provenance') })]) }),
    ]));
    const history = requests[1].request.input;
    expect(history).toEqual(expect.arrayContaining([expect.objectContaining({ type: 'function_call', callId, name: 'view_schema' })]));
    const result = history.find((item: any) => item.type === 'function_call_output' && item.callId === callId);
    expect(result).toBeDefined();
    for (const field of ['costs.amount_usd', 'jobs.review_status', 'attention.evidence_url', 'agents.accepted_count']) {
      expect(result.output).toContain(field);
    }

    // Exercise the real server mapping offline, including its fixed policy and
    // provider envelope overhead. This never dispatches or reserves model usage.
    providerBytes = JSON.parse(execFileSync('python', ['-c', [
      'import json, sys',
      'from aicl.studio.ai import provider_request',
      'requests = json.load(sys.stdin)',
      'print(json.dumps([len(json.dumps(provider_request(item["request"]), ensure_ascii=False, separators=(",", ":")).encode()) for item in requests]))',
    ].join('\n')], { input: JSON.stringify(requests), encoding: 'utf8', env: { ...process.env, PYTHONPATH: resolve('backend') } }));
    expect(providerBytes).toHaveLength(2);
    providerBytes.forEach(size => expect(size).toBeLessThanOrEqual(48_000));

    expect(await (await page.request.get('/audit/studio/state')).json()).toEqual(beforeState);
    const afterData = await (await page.request.get('/audit/studio/data')).json();
    const { as_of: beforeTimestamp, ...beforeRecords } = beforeData;
    const { as_of: afterTimestamp, ...afterRecords } = afterData;
    expect(afterRecords).toEqual(beforeRecords);
    expect(mutations).toEqual([]);
    expect(errors).toEqual([]);
  } finally {
    mkdirSync('.ctx', { recursive: true });
    // No auth headers/cookies are written; these are fixture schema requests.
    writeFileSync('.ctx/studio-ai-requests.json', JSON.stringify({ source: 'scripted-browser', requests, provider_bytes: providerBytes }, null, 2));
  }
});
