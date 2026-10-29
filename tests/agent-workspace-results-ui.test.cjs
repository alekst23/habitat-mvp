"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { chromium } = require("@playwright/test");

// Render model text and canonical accounting in a real browser, with local
// fixtures only. A result must never initiate a network request of its own.
test("work results render safe Markdown and retain a scoped, downloadable action and cost log", { timeout: 60000 }, async () => {
  const root = path.resolve(__dirname, "..");
  const recorded = (value, estimated = 0, held = 0) => ({ settled_micro_usd: value, estimated_micro_usd: estimated, total_micro_usd: value + estimated, held_micro_usd: held,
    components: [{ coverage: "recorded", amount_micro_usd: value, component: "model_and_tools" }], coverage_note: "Combined charges are counted once. Unmetered access is not assumed free." });
  const unmetered = { ...recorded(0), components: [{ coverage: "not_metered", amount_micro_usd: null }] };
  let log = { schema_version: 1, run_id: "run-1", created_at: "2026-10-28T21:00:00Z", updated_at: "2026-10-28T21:01:00Z", status: "completed", audit_url: "/audit/jobs/runtime%3Arun-1",
    summary: recorded(330892, 5000, 140000), totals: { model_decisions: 1, tool_calls: 3, input_tokens: 1234, output_tokens: 56, web_search_calls: 2 }, steps: [
      { id: "step-1", sequence: 1, kind: "decision", label: "Model decision", state: "applied", error: null, created_at: "2026-10-28T21:00:00Z", updated_at: "2026-10-28T21:00:10Z", model: "fixture-model", usage: { input_tokens: 1234, output_tokens: 56, web_search_calls: 0, compute_minutes: 0, cost_micro_usd: 330892 }, cost_summary: recorded(330892), details_url: "/api/audit/runs/run-1/steps/step-1", evidence_url: "/audit/jobs/runtime%3Arun-1#step-step-1" },
      { id: "step-2", sequence: 2, kind: "tool", tool_name: "artifact.read", label: "Read saved evidence", state: "applied", error: null, created_at: "2026-10-28T21:00:10Z", usage: { input_tokens: 0, output_tokens: 0, web_search_calls: 0, compute_minutes: 0, cost_micro_usd: 0 }, cost_summary: recorded(0), evidence_url: "/audit/jobs/runtime%3Arun-1#step-step-2" },
      { id: "step-3", sequence: 3, kind: "tool", tool_name: "fixture.unknown", label: "Unmetered local action", state: "applied", error: null, created_at: "2026-10-28T21:00:11Z", usage: null, cost_summary: unmetered, evidence_url: "/audit/jobs/runtime%3Arun-1#step-step-3" },
      { id: "step-4", sequence: 4, kind: "tool", tool_name: "public.research", label: "Public research", state: "received", error: "confirmation_pending", created_at: "2026-10-28T21:00:20Z", usage: { input_tokens: 0, output_tokens: 0, web_search_calls: 2, compute_minutes: 0, cost_micro_usd: null }, cost_summary: { ...unmetered, estimated_micro_usd: 5000, held_micro_usd: 140000 }, evidence_url: "/audit/jobs/runtime%3Arun-1#step-step-4" }
    ] };
  const markdown = ["# AI news digest", "", "**Coverage:** a *short* report with `code` and [Source](https://www.example.org/article_(today)).", "",
    "1. **First story** with context.", "", "2. Second story.", "   - Nested detail", "", "> A quoted limitation.", "",
    "| Story | Date |", "| --- | --- |", "| First | Oct 28 |", "", "```html", "<img src=https://bad.example/image onerror=alert(1)>", "```", "",
    "<script>window.injected = true</script><svg onload=alert(1)></svg><iframe src=https://bad.example/frame></iframe>", "",
    "![Tracking pixel](https://bad.example/image?secret=value)", "[![Nested image](https://bad.example/nested)](https://bad.example/outer)", "",
    "[Script](javascript:alert(1)) [Encoded](java&#x73;cript:alert(1)) [Data](data:text/html,test) [Relative](/api/danger) [Protocol relative](//bad.example/track)", "",
    "[Credentials](https://user:password@bad.example/) [Local](http://127.0.0.1:4173/) [Internal](https://thing.internal/) [Backslash](https://bad.example\\@www.example.org/)"
  ].join("\n");
  const draft = { name: "Digest", goal: "Summarize public news", inputs: "", deliverables: [], tools: [], network_domains: [], web_access: { mode: "off", domains: [] }, web_search: { mode: "off", domains: [] }, cadence: "manual", timezone: "UTC", time_of_day: "09:00", limits: {} };
  const state = { id: "results-fixture", version: 1, session_id: "fixture", instance_id: "instance-fixture", dirty: false, lifecycle: "active", capabilities: [], draft, published: structuredClone(draft),
    execution: { can_start: true, runtime_available: true, schedule: { enabled: false }, messages: [], readiness: { ready: true, balance_micro_usd: 2000000, required_micro_usd: 140000, blockers: [] },
      run: { id: "run-1", version: 1, status: "completed", objective: draft.goal, plan: [], artifacts: [{ name: "ai_digest", title: "AI digest", content: markdown }], activity_log: log } } };
  const payload = () => ({ state, messages: [], usage: null });
  let legacyTemplate = false, omitMarkdown = false;
  const server = http.createServer((req, res) => {
    if (req.url.startsWith("/static/")) { const file = path.join(root, "backend/aicl/web/static", path.basename(new URL(req.url, "http://127.0.0.1").pathname)); res.setHeader("Content-Type", file.endsWith(".css") ? "text/css" : "application/javascript"); res.end(fs.existsSync(file) ? fs.readFileSync(file) : ""); return; }
    if (req.url === "/api/audit/runs/run-1/steps/step-1") { res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify({ schema_version: 1, run_id: "run-1", step: log.steps[0], request: { status: "retained", label: "Saved model context", content: { goal: "Summarize public news" } }, response: { status: "retained", content: { text: "Saved decision output" } }, records: [], limitations: [] })); return; }
    if (req.url === "/api/agent-workspaces/results-fixture") { res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify(payload())); return; }
    const render = spawnSync(path.join(root, ".venv/bin/python"), ["-c", "import json,sys; from aicl.agent_workspace.pages import render_workspace; p=json.load(sys.stdin); print(render_workspace(p['state'],csrf='fixture',account_name='Fixture',messages=[],usage=None))"], { cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, "backend") }, input: JSON.stringify(payload()), encoding: "utf8" });
    if (render.status) { res.writeHead(500); res.end(render.stderr); return; }
    let html = render.stdout;
    if (legacyTemplate) html = html.replace('<div data-run-activity></div>', '');
    if (omitMarkdown) html = html.replace(/<script src="\/static\/workspace-markdown\.js[^\"]*" defer><\/script>/, '');
    res.setHeader("Content-Type", "text/html"); res.end(html);
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const origin = `http://127.0.0.1:${server.address().port}`, externalRequests = [], errors = [];
    page.on("pageerror", err => errors.push(err.message));
    await page.route("**/*", route => { if (!route.request().url().startsWith(origin + "/")) { externalRequests.push(route.request().url()); return route.abort(); } return route.continue(); });
    await page.goto(origin + "/agent-workspaces/results-fixture");
    const result = page.locator(".workspace-artifact");
    await result.locator("summary").click();
    const content = result.locator(".workspace-artifact-content");
    assert.equal(await content.getByRole("heading", { name: "AI news digest", level: 3 }).count(), 1);
    assert.equal(await content.locator("strong").first().textContent(), "Coverage:");
    assert.equal(await content.locator("em").textContent(), "short");
    assert.equal(await content.locator("ol > li").count(), 2);
    assert.equal(await content.locator("ol ul > li").textContent(), "Nested detail");
    assert.equal(await content.locator("blockquote").textContent(), "A quoted limitation.");
    assert.equal(await content.locator("table th").count(), 2);
    assert.match(await content.locator("pre code").textContent(), /<img src=/);
    const link = content.getByRole("link", { name: "Source", exact: true });
    assert.equal(await link.getAttribute("href"), "https://www.example.org/article_(today)");
    assert.equal(await link.getAttribute("rel"), "noopener noreferrer");
    assert.equal(await link.getAttribute("referrerpolicy"), "no-referrer");
    assert.equal(await link.getAttribute("target"), "_blank");
    assert.deepEqual(await content.locator("a").evaluateAll(els => els.map(el => [el.textContent, el.href])), [["Source", "https://www.example.org/article_(today)"]]);
    assert.equal(await content.locator("script,img,iframe,svg,object,embed,video,audio,source,style,link").count(), 0);
    assert.equal(await page.evaluate(() => window.injected), undefined);
    assert.deepEqual(externalRequests, []);
    const activity = page.locator(".workspace-activity");
    assert.match(await activity.locator("summary").textContent(), /\$0\.330892 recorded · this run/);
    await activity.locator("summary").click();
    assert.equal(await activity.locator("tbody tr").count(), 4);
    assert.equal(await activity.locator('[data-step-id="step-1"] td').last().textContent(), "$0.330892");
    assert.equal(await activity.locator('[data-step-id="step-2"] td').last().textContent(), "$0.00");
    assert.equal(await activity.locator('[data-step-id="step-3"] td').last().textContent(), "Not recorded");
    assert.match(await activity.locator('[data-step-id="step-4"] td').last().textContent(), /Not recorded.*\$0\.005 estimated.*\$0\.14 reserved/);
    assert.match(await activity.locator(".workspace-activity-metrics").textContent(), /Runtime estimates\$0\.005Reserved · not charged\$0\.14/);
    assert.equal(await activity.getByRole("link", { name: "Open full audit" }).getAttribute("href"), "/audit/jobs/runtime%3Arun-1");
    await activity.getByRole("link", { name: "Model decision", exact: true }).click();
    const actionPanel = page.getByRole("dialog", { name: "Model decision", exact: true });
    await actionPanel.getByText("Saved model context", { exact: true }).waitFor();
    assert.match(await actionPanel.textContent(), /Summarize public news.*Saved decision output/s);
    await actionPanel.getByRole("button", { name: "Close", exact: true }).click();
    const downloading = page.waitForEvent("download");
    await activity.getByRole("button", { name: "Download log JSON" }).click();
    const download = await downloading;
    assert.equal(download.suggestedFilename(), "habitat-work-run-1-actions.json");
    assert.deepEqual(JSON.parse(fs.readFileSync(await download.path(), "utf8")), log);
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.workspace-activity[open]') && document.querySelector('.workspace-artifact[open]'));
    assert.equal(await activity.locator("tbody tr").count(), 4, "Polling must not append duplicate costs or rows");
    assert.match(await activity.locator("summary").textContent(), /\$0\.330892 recorded/);
    // Path-shaped model content and unexpected backend link destinations cannot navigate the app.
    log.audit_url = "https://bad.example/audit"; log.steps[0].evidence_url = "/api/danger";
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.waitForFunction(() => !Array.from(document.querySelectorAll('.workspace-activity a')).some(a => a.textContent === 'Open full audit'));
    assert.equal(await activity.locator('[data-step-id="step-1"] a').count(), 0);
    log.audit_url = "/audit/jobs/runtime%3Arun-1"; log.steps[0].evidence_url = "/audit/jobs/runtime%3Arun-1#step-step-1";
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await activity.getByRole("link", { name: "Open full audit" }).waitFor();
    fs.mkdirSync(path.join(root, ".ctx/workspace-ui"), { recursive: true });
    await page.locator("#workspace-results").screenshot({ path: path.join(root, ".ctx/workspace-ui/markdown-and-actions.png") });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.equal(await activity.locator(".workspace-activity-table").evaluate(el => el.scrollWidth > el.clientWidth), true, "Only the table scrolls on narrow screens");
    // Canonical aggregate rows can omit zero amounts; measured local steps still
    // prove a zero recorded charge, whereas an entirely unmetered run does not.
    const fullLog = structuredClone(log);
    log.summary = unmetered; log.steps = [structuredClone(log.steps[1])];
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.workspace-activity > summary').textContent.includes('$0.00 recorded'));
    log.steps = [structuredClone(fullLog.steps[2])];
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.workspace-activity > summary').textContent.includes('Not recorded'));
    Object.assign(log, fullLog);
    // A different run's activity must never be shown or exported under this work.
    state.execution.run.id = "run-2";
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.locator(".workspace-activity-unavailable").waitFor();
    assert.equal(await page.getByRole("button", { name: "Download log JSON" }).count(), 0);
    assert.equal(await result.getAttribute("open"), null, "Result expansion does not leak between runs");
    state.execution.run.id = "run-1";
    // Cached old templates and a failed renderer load still show safely escaped results.
    legacyTemplate = true; omitMarkdown = true;
    await page.reload();
    assert.equal(await page.locator(".workspace-activity").count(), 1);
    assert.match(await page.locator(".workspace-artifact-content").textContent(), /^# AI news digest/);
    assert.equal(await page.locator(".workspace-artifact-content img").count(), 0);
    assert.deepEqual(errors, []);
    assert.deepEqual(externalRequests, []);
  } finally { if (browser) await browser.close(); await new Promise(resolve => server.close(resolve)); }
});
