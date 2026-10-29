"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { chromium } = require("@playwright/test");

// Fixtures exercise the actual template, scripts, and CSS without starting work,
// paying for inference, or allowing report content to contact another website.
test("review inbox browses weeks of work, safely renders reports, and preserves scoped marks and costs", { timeout: 60000 }, async () => {
  const root = path.resolve(__dirname, "..");
  const render = spawnSync(path.join(root, ".venv/bin/python"), ["-c", "from aicl.work_review.pages import render_review; print(render_review(csrf='review-fixture-csrf',account_name='Fixture owner'))"], {
    cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, "backend") }, encoding: "utf8",
  });
  assert.equal(render.status, 0, render.stderr);
  const summary = { settled_micro_usd: 131450, held_micro_usd: 140000, estimated_micro_usd: 5000,
    components: [{ coverage: "recorded", amount_micro_usd: 131450 }],
    coverage_note: "Recorded usage, estimates, and reservations are accounted for separately." };
  const agents = [{ workspace_id: "workspace-a", name: "Morning digest" }, { workspace_id: "workspace-b", name: "Market watch" }];
  const records = Array.from({ length: 45 }, (_, index) => {
    const agent = agents[index % 2];
    const created = new Date(Date.UTC(2026, 9, 28 - index, 9)).toISOString();
    return { run_id: "run-" + index, version: 7, workspace_id: agent.workspace_id, agent_name: agent.name,
      workspace_url: "/agent-workspaces/" + agent.workspace_id, assistant_url: "/agent-workspaces/" + agent.workspace_id + "#workspace-assistant",
      title: index === 42 ? "Archive target" : "Daily report " + index, goal: "Summarize public developments for the owner.",
      status: index === 42 ? "blocked" : "completed", needs_attention: index === 42,
      created_at: created, updated_at: created, output_count: 2, seen: false, saved: index === 42,
      recorded_micro_usd: 131450, cost_summary: structuredClone(summary) };
  });
  const hostileMarkdown = ["# Verified daily brief", "", "**Coverage:** a *short* report with [Original source](https://www.example.org/news).", "",
    "1. First development.", "2. Second development.", "", "| Item | Date |", "| --- | --- |", "| News | Oct 28 |", "",
    "```html", "<img src=https://tracker.example/code>", "```", "",
    "<script>window.reviewInjected=true</script><iframe src=https://tracker.example/frame></iframe>", "",
    "![Invisible tracking image](https://tracker.example/pixel?id=private)", "",
    "[Script](javascript:alert(1)) [Encoded](java&#x73;cript:alert(1)) [Private](/api/private) [Local](http://127.0.0.1:4173/)",
  ].join("\n");
  function detail(item) {
    const audit = "/audit/jobs/" + encodeURIComponent("runtime:" + item.run_id);
    return { item: structuredClone(item), outputs: [
      { id: item.run_id + ":new", name: "daily_digest", latest: true, state: item.status === "blocked" ? "draft" : "completed", created_at: item.created_at, content: item.run_id === "run-0" ? hostileMarkdown : "# " + item.title + "\n\nSaved report for " + item.run_id + "." },
      { id: item.run_id + ":old", name: "daily_digest", latest: false, state: "draft", created_at: item.created_at, content: "# Earlier saved version\n\nPartial findings for " + item.run_id + "." },
    ], sources: [{ title: "Original source", url: "https://www.example.org/news", kind: "public_page", recorded_at: item.created_at },
      { title: "Unsafe source", url: "javascript:alert(1)", kind: "search_result", recorded_at: item.created_at }],
    activity: { schema_version: 1, run_id: item.run_id, summary: structuredClone(summary),
      totals: { model_decisions: 5, tool_calls: 13, web_search_calls: 2, input_tokens: 47095, output_tokens: 2726 }, steps: [
        { id: "step-1", kind: "decision", label: "Model decision", model: "fixture-model", state: "applied", created_at: item.created_at,
          evidence_url: audit + "#step-step-1", details_url: "/api/audit/runs/" + item.run_id + "/steps/step-1", cost_summary: { settled_micro_usd: 131450, components: [{ coverage: "recorded", amount_micro_usd: 131450 }] } },
        { id: "step-2", kind: "tool", label: "Pending research", state: "unknown", created_at: item.created_at,
          evidence_url: audit + "#step-step-2", details_url: "/api/audit/runs/" + item.run_id + "/steps/step-2", cost_summary: { settled_micro_usd: 0, held_micro_usd: 140000, components: [{ coverage: "not_metered", amount_micro_usd: null }] } },
      ] }, audit_url: audit, question: null, plan: [] };
  }
  function actionDetail(item, stepId) {
    return { schema_version: 1, run_id: item.run_id, step: detail(item).activity.steps.find(step => step.id === stepId),
      request: { status: "retained", label: "Saved model context", content_ref: "saved:context:1", content: { goal: "Write the daily digest", evidence: "<img src=https://tracker.example/request onerror=alert(1)>" }, note: "The exact provider HTTP envelope was not retained." },
      response: { status: stepId === "step-1" ? "retained" : "not_retained", label: "Saved adapter response", content: stepId === "step-1" ? { text: "<script>window.actionInjected=true</script>", result: "x".repeat(24000) + "END OF RETAINED RESULT" } : null, note: stepId === "step-1" ? "" : "This older response was not retained." },
      records: [{ label: "Search response 1", metadata: { status: "completed", round: 1, model: "research-fixture-model", response_id: "fixture-response" }, request: { status: "retained", content: { query: "public AI news" } }, response: { status: "retained", content: { results: [{ title: "Fixture news", url: "https://tracker.example/search" }] } } }],
      limitations: ["This saved context is adapter input, not the complete wire prompt."] };
  }
  const requests = [], marks = [];
  let failAction = false;
  let delayRun = null, releaseDetail = null, delayMark = null, releaseMark = null;
  function json(res, value, status = 200) { res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" }); res.end(JSON.stringify(value)); }
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1"); requests.push({ method: req.method, pathname: url.pathname, query: Object.fromEntries(url.searchParams) });
    if (url.pathname.startsWith("/static/")) {
      const file = path.join(root, "backend/aicl/web/static", path.basename(url.pathname));
      res.setHeader("Content-Type", file.endsWith(".css") ? "text/css" : "application/javascript");
      res.end(fs.existsSync(file) ? fs.readFileSync(file) : ""); return;
    }
    const actionMatch = url.pathname.match(/^\/api\/audit\/runs\/(run-\d+)\/steps\/(step-[12])$/);
    if (actionMatch) { if (failAction) { failAction = false; return json(res, { message: "Temporary problem" }, 503); } return json(res, actionDetail(records.find(item => item.run_id === actionMatch[1]), actionMatch[2])); }
    if (url.pathname === "/requests/summary") return json(res, { pending_count: 0 });
    if (url.pathname === "/api/work-review") {
      const p = url.searchParams;
      let filtered = records.filter(row => (!p.get("q") || [row.agent_name, row.title, row.goal].join(" ").toLowerCase().includes(p.get("q").toLowerCase())) &&
        (!p.get("workspace_id") || row.workspace_id === p.get("workspace_id")) &&
        (!p.get("from_date") || row.created_at.slice(0, 10) >= p.get("from_date")) && (!p.get("to_date") || row.created_at.slice(0, 10) <= p.get("to_date")));
      const counts = { all: filtered.length, unseen: filtered.filter(r => !r.seen).length, saved: filtered.filter(r => r.saved).length, needs_attention: filtered.filter(r => r.needs_attention).length };
      if (p.get("view") === "unseen") filtered = filtered.filter(row => !row.seen);
      if (p.get("view") === "saved") filtered = filtered.filter(row => row.saved);
      if (p.get("view") === "needs_attention") filtered = filtered.filter(row => row.needs_attention);
      const offset = Number(p.get("cursor") || 0), limit = Number(p.get("limit") || 25);
      return json(res, { items: filtered.slice(offset, offset + limit), next_cursor: offset + limit < filtered.length ? String(offset + limit) : null, counts, agents });
    }
    const match = url.pathname.match(/^\/api\/work-review\/(run-\d+)(\/marks)?$/);
    if (match) {
      const item = records.find(record => record.run_id === match[1]);
      if (match[2]) {
        let body = ""; for await (const chunk of req) body += chunk;
        const payload = JSON.parse(body); marks.push({ id: item.run_id, csrf: req.headers["x-csrf-token"], contentType: req.headers["content-type"], payload });
        if (req.method !== "POST" || req.headers["x-csrf-token"] !== "review-fixture-csrf" || payload.expected_version !== item.version) return json(res, { message: "Invalid mark" }, 409);
        const complete = () => {
          for (const key of ["seen", "saved"]) if (key in payload) item[key] = payload[key];
          return json(res, { run_id: item.run_id, version: item.version, seen: item.seen, saved: item.saved });
        };
        if (item.run_id === delayMark) { releaseMark = complete; return; }
        return complete();
      }
      if (item.run_id === delayRun) { releaseDetail = () => json(res, detail(item)); return; }
      return json(res, detail(item));
    }
    if (url.pathname === "/work") { res.setHeader("Content-Type", "text/html"); res.end(render.stdout); return; }
    json(res, { message: "Unexpected fixture route" }, 404);
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const origin = `http://127.0.0.1:${server.address().port}`, externalRequests = [], errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/*", route => { if (!route.request().url().startsWith(origin + "/")) { externalRequests.push(route.request().url()); return route.abort(); } return route.continue(); });
    await page.goto(origin + "/work");
    const rows = page.locator(".review-row"), reader = page.locator("[data-review-reader]");
    await reader.getByRole("heading", { name: "Verified daily brief", exact: true }).waitFor();
    assert.equal(await rows.count(), 20);
    assert.match(await page.locator("[data-review-counts]").textContent(), /45 unseen.*45 runs/);
    assert.equal(await reader.locator(".review-brief").getAttribute("open"), null);
    assert.equal(await reader.locator(".review-brief > summary").textContent(), "Original brief");
    assert.equal(marks.length, 0, "Opening work does not mark it seen or approve anything");
    assert.equal(await reader.locator(".review-article strong").textContent(), "Coverage:");
    assert.equal(await reader.locator(".review-article ol > li").count(), 2);
    assert.equal(await reader.locator(".review-article table th").count(), 2);
    assert.equal(await reader.locator(".review-article script,img,iframe,svg,object,embed,style,link").count(), 0);
    assert.equal(await page.evaluate(() => window.reviewInjected), undefined);
    const source = reader.getByRole("link", { name: "Original source", exact: true });
    assert.equal(await source.getAttribute("rel"), "noopener noreferrer");
    assert.equal(await source.getAttribute("referrerpolicy"), "no-referrer");
    assert.deepEqual(await reader.locator(".review-article a").evaluateAll(links => links.map(a => a.href)), ["https://www.example.org/news"]);
    assert.deepEqual(externalRequests, []);
    await page.getByRole("button", { name: "Load older work", exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll(".review-row").length === 40);
    await page.locator('[data-run-id="run-39"]').click();
    await reader.getByRole("heading", { name: "Daily report 39", level: 3 }).waitFor();
    const olderScroll = await page.locator(".review-list-pane").evaluate(pane => pane.scrollTop);
    assert.ok(olderScroll > 0, "The older selected row is beyond the initial list viewport");
    await reader.getByRole("button", { name: "Mark seen", exact: true }).click();
    await reader.getByRole("button", { name: "Mark unseen", exact: true }).waitFor();
    assert.equal(await rows.count(), 40, "Marking older work preserves every loaded page");
    assert.equal(await page.locator('[data-run-id="run-39"]').getAttribute("aria-current"), "true");
    assert.equal(await page.locator(".review-list-pane").evaluate(pane => pane.scrollTop), olderScroll, "Marking work preserves list scroll position");
    await page.getByRole("button", { name: "Load older work", exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll(".review-row").length === 45);
    assert.equal(await rows.evaluateAll(items => new Set(items.map(row => row.dataset.runId)).size), 45);
    assert.equal(await page.getByRole("button", { name: "Load older work", exact: true }).isVisible(), false);
    await page.locator('[data-run-id="run-42"]').click();
    await reader.getByRole("heading", { name: "Archive target", level: 3 }).waitFor();
    assert.match(await reader.textContent(), /Saved draft\. Reading or marking this seen does not approve it or continue the run/);
    assert.match(page.url(), /run=run-42/);

    // Filters reach records beyond the initially loaded page and survive refresh URLs.
    await page.getByRole("searchbox", { name: "Search work" }).fill("Archive target");
    await page.waitForFunction(() => document.querySelectorAll(".review-row").length === 1);
    assert.equal(await rows.first().getAttribute("data-run-id"), "run-42");
    assert.match(page.url(), /q=Archive\+target/);
    assert.match(await page.locator("[data-review-counts]").textContent(), /1 run$/);
    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll(".review-row").length === 20);
    await page.locator("#review-agent").selectOption("workspace-b");
    await page.waitForFunction(() => [...document.querySelectorAll(".review-row")].every(row => Number(row.dataset.runId.slice(4)) % 2 === 1));
    assert.match(page.url(), /workspace_id=workspace-b/);
    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await page.locator("#review-view").selectOption("needs_attention");
    await page.waitForFunction(() => document.querySelectorAll(".review-row").length === 1 && document.querySelector(".review-row").dataset.runId === "run-42");
    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await reader.getByRole("heading", { name: "Verified daily brief", exact: true }).waitFor();

    await page.getByLabel("Version", { exact: true }).selectOption("run-0:old");
    await reader.getByRole("heading", { name: "Earlier saved version", exact: true }).waitFor();
    assert.match(await reader.textContent(), /reading an earlier saved version/);
    assert.match(page.url(), /output=run-0%3Aold/);
    await page.reload();
    await reader.getByRole("heading", { name: "Earlier saved version", exact: true }).waitFor();
    await page.getByLabel("Version", { exact: true }).selectOption("run-0:new");
    await reader.getByRole("tab", { name: "Sources", exact: true }).click();
    assert.equal(await reader.locator(".review-source a").count(), 1);
    assert.deepEqual(externalRequests, []);
    await reader.getByRole("tab", { name: "Cost", exact: true }).click();
    assert.equal(await reader.locator(".review-cost-total").textContent(), "$0.13145");
    assert.match(await reader.textContent(), /Recorded charge\$0\.13145Reserved · not charged\$0\.14Runtime estimate · separate\$0\.005/);
    await reader.getByRole("tab", { name: "Activity", exact: true }).click();
    assert.equal(await reader.locator("tbody tr").count(), 2);
    assert.equal(await reader.locator("tbody tr").last().locator("td").last().textContent(), "Not recorded$0.14 reserved");
    const inspectAction = reader.getByRole("link", { name: "Model decision", exact: true });
    assert.equal(await inspectAction.getAttribute("href"), "/audit/jobs/runtime%3Arun-0#step-step-1", "The original audit is the no-script fallback");
    const beforeInspect = requests.length;
    await inspectAction.click();
    const actionPanel = page.getByRole("dialog", { name: "Model decision", exact: true });
    await actionPanel.getByText("Saved model context", { exact: true }).waitFor();
    assert.match(await actionPanel.textContent(), /END OF RETAINED RESULT/);
    assert.match(await actionPanel.textContent(), /exact provider HTTP envelope was not retained/);
    assert.equal(await actionPanel.locator("img,script,iframe,a[href^='https:']").count(), 0);
    assert.equal(await page.evaluate(() => window.actionInjected), undefined);
    assert.deepEqual(requests.slice(beforeInspect).filter(request => request.pathname !== "/requests/summary").map(request => [request.method, request.pathname]), [["GET", "/api/audit/runs/run-0/steps/step-1"]]);
    await actionPanel.locator(".action-detail-record > summary").click();
    assert.match(await actionPanel.locator(".action-detail-record").textContent(), /public AI news.*Fixture news/s);
    await actionPanel.getByText("Call metadata", { exact: true }).click();
    assert.match(await actionPanel.locator(".action-detail-record").textContent(), /research-fixture-model.*fixture-response/s);
    const actionDownloading = page.waitForEvent("download");
    await actionPanel.getByRole("button", { name: "Download action details", exact: true }).click();
    assert.deepEqual(JSON.parse(fs.readFileSync(await (await actionDownloading).path(), "utf8")), actionDetail(records[0], "step-1"));
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("dialog[open]").count(), 0);
    assert.equal(await inspectAction.evaluate(el => document.activeElement === el), true);
    failAction = true;
    await reader.getByRole("link", { name: "Pending research", exact: true }).click();
    const retryPanel = page.getByRole("dialog");
    await retryPanel.getByRole("alert").waitFor();
    await retryPanel.getByRole("button", { name: "Try again", exact: true }).click();
    await retryPanel.getByText("Not retained for this action.", { exact: true }).waitFor();
    await retryPanel.getByRole("button", { name: "Close", exact: true }).click();
    assert.deepEqual(externalRequests, []);
    const downloading = page.waitForEvent("download");
    await reader.getByRole("button", { name: "Download action log", exact: true }).click();
    const download = await downloading;
    assert.deepEqual(JSON.parse(fs.readFileSync(await download.path(), "utf8")), detail(records[0]).activity);
    await reader.getByRole("button", { name: "Mark seen", exact: true }).click();
    await reader.getByRole("button", { name: "Mark unseen", exact: true }).waitFor();
    await reader.getByRole("button", { name: "Save", exact: true }).click();
    await reader.getByRole("button", { name: "Saved", exact: true }).waitFor();
    assert.deepEqual(marks, [
      { id: "run-39", csrf: "review-fixture-csrf", contentType: "application/json", payload: { expected_version: 7, seen: true } },
      { id: "run-0", csrf: "review-fixture-csrf", contentType: "application/json", payload: { expected_version: 7, seen: true } },
      { id: "run-0", csrf: "review-fixture-csrf", contentType: "application/json", payload: { expected_version: 7, saved: true } },
    ]);

    // A changed mark removes only the now-ineligible row from a filtered list.
    await page.locator("#review-view").selectOption("saved");
    await page.waitForFunction(() => document.querySelectorAll(".review-row").length === 2);
    await reader.getByRole("button", { name: "Saved", exact: true }).click();
    await reader.getByRole("button", { name: "Save", exact: true }).waitFor();
    assert.equal(await rows.count(), 1);
    assert.equal(await rows.first().getAttribute("data-run-id"), "run-42");
    assert.equal(await reader.getByRole("heading", { name: "Verified daily brief", exact: true }).count(), 1, "The report stays readable when its row leaves the filter");
    await reader.getByRole("button", { name: "Save", exact: true }).click();
    await reader.getByRole("button", { name: "Saved", exact: true }).waitFor();
    assert.equal(await rows.count(), 2, "Undoing the mark restores the report to the current Saved view");
    assert.equal(await page.locator('[data-run-id="run-0"]').getAttribute("aria-current"), "true");
    await reader.getByRole("button", { name: "Saved", exact: true }).click();
    await reader.getByRole("button", { name: "Save", exact: true }).waitFor();
    assert.equal(await rows.count(), 1);
    await page.locator("#review-view").selectOption("unseen");
    await reader.getByRole("heading", { name: "Daily report 1", level: 3 }).waitFor();
    delayMark = "run-1";
    await reader.getByRole("button", { name: "Mark seen", exact: true }).click();
    await page.locator('[data-run-id="run-2"]').click();
    await reader.getByRole("heading", { name: "Daily report 2", level: 3 }).waitFor();
    assert.ok(releaseMark, "Mark request is pending while another report is selected");
    let pendingMarkResponse = page.waitForResponse(response => response.url().endsWith("/api/work-review/run-1/marks"));
    let finishMark = releaseMark; releaseMark = null; delayMark = null; finishMark(); await pendingMarkResponse;
    await page.waitForFunction(() => !document.querySelector('[data-run-id="run-1"]') && !document.querySelector(".review-reader-actions button").disabled);
    assert.equal(await rows.count(), 19);
    assert.equal(await reader.getByRole("heading", { name: "Daily report 2", level: 3 }).count(), 1);
    assert.equal(await reader.getByRole("button", { name: "Mark seen", exact: true }).count(), 1, "Another run's mark does not change the selected report");
    assert.match(await page.locator("[data-review-counts]").textContent(), /^42 unseen/);

    // A filter change while a POST is pending cannot restore its old selection/list.
    delayMark = "run-2";
    await reader.getByRole("button", { name: "Save", exact: true }).click();
    await page.locator("#review-view").selectOption("needs_attention");
    await reader.getByRole("heading", { name: "Archive target", level: 3 }).waitFor();
    assert.ok(releaseMark);
    pendingMarkResponse = page.waitForResponse(response => response.url().endsWith("/api/work-review/run-2/marks"));
    finishMark = releaseMark; releaseMark = null; delayMark = null; finishMark(); await pendingMarkResponse;
    await page.waitForFunction(() => !document.querySelector(".review-reader-actions button").disabled);
    assert.equal(await rows.count(), 1);
    assert.equal(await rows.first().getAttribute("data-run-id"), "run-42");
    assert.equal(await reader.getByRole("heading", { name: "Archive target", level: 3 }).count(), 1);
    assert.match(page.url(), /view=needs_attention.*run=run-42/);
    assert.deepEqual(marks.slice(3), [
      { id: "run-0", csrf: "review-fixture-csrf", contentType: "application/json", payload: { expected_version: 7, saved: false } },
      { id: "run-0", csrf: "review-fixture-csrf", contentType: "application/json", payload: { expected_version: 7, saved: true } },
      { id: "run-0", csrf: "review-fixture-csrf", contentType: "application/json", payload: { expected_version: 7, saved: false } },
      { id: "run-1", csrf: "review-fixture-csrf", contentType: "application/json", payload: { expected_version: 7, seen: true } },
      { id: "run-2", csrf: "review-fixture-csrf", contentType: "application/json", payload: { expected_version: 7, saved: true } },
    ]);
    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await reader.getByRole("heading", { name: "Verified daily brief", exact: true }).waitFor();

    // A newly selected Saved view fetched before the write must gain that result
    // after the receipt, even though there was no existing row to update.
    delayMark = "run-0";
    await reader.getByRole("button", { name: "Save", exact: true }).click();
    await page.locator("#review-view").selectOption("saved");
    await reader.getByRole("heading", { name: "Daily report 2", level: 3 }).waitFor();
    assert.equal(await rows.count(), 2);
    assert.equal(await page.locator('[data-run-id="run-0"]').count(), 0);
    assert.ok(releaseMark);
    pendingMarkResponse = page.waitForResponse(response => response.url().endsWith("/api/work-review/run-0/marks"));
    finishMark = releaseMark; releaseMark = null; delayMark = null; finishMark(); await pendingMarkResponse;
    await page.waitForFunction(() => document.querySelectorAll(".review-row").length === 3 && !document.querySelector(".review-reader-actions button").disabled);
    assert.equal(await page.locator('[data-run-id="run-0"]').count(), 1);
    assert.equal(await reader.getByRole("heading", { name: "Daily report 2", level: 3 }).count(), 1);
    assert.match(page.url(), /view=saved.*run=run-2/);
    assert.deepEqual(marks.at(-1), { id: "run-0", csrf: "review-fixture-csrf", contentType: "application/json", payload: { expected_version: 7, saved: true } });
    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await reader.getByRole("heading", { name: "Verified daily brief", exact: true }).waitFor();

    // Late detail responses must not replace the report selected more recently.
    delayRun = "run-1";
    await page.locator('[data-run-id="run-1"]').click();
    await page.locator('[data-run-id="run-2"]').click();
    await reader.getByRole("heading", { name: "Daily report 2", level: 3 }).waitFor();
    assert.ok(releaseDetail, "The older request must actually be pending");
    const oldResponse = page.waitForResponse(response => response.url().endsWith("/api/work-review/run-1"));
    const release = releaseDetail; releaseDetail = null; release(); await oldResponse;
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await reader.getByRole("heading", { name: "Daily report 2", level: 3 }).count(), 1);
    assert.equal(await reader.getByRole("heading", { name: "Daily report 1", level: 3 }).count(), 0);
    assert.match(page.url(), /run=run-2/);
    await page.getByRole("button", { name: "Agent assistant", exact: true }).click();
    const assistant = page.getByRole("complementary", { name: "Agent assistant", exact: true });
    assert.match(await assistant.textContent(), /does not receive this historical report automatically/);
    assert.equal(await assistant.getByRole("link", { name: "Open agent assistant", exact: true }).getAttribute("href"), "/agent-workspaces/workspace-a#workspace-assistant");
    assert.equal(await assistant.locator("form,input,textarea").count(), 0);
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await reader.getByRole("tab", { name: "Activity", exact: true }).click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.equal(await reader.locator(".review-table-wrap").evaluate(el => el.scrollWidth > el.clientWidth), true);
    await reader.getByRole("link", { name: "Model decision", exact: true }).click();
    await page.getByRole("dialog").getByText("Saved model context", { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.equal(await page.getByRole("dialog").evaluate(el => el.scrollWidth <= el.clientWidth), true);
    await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click();
    assert.deepEqual(errors, []);
    assert.deepEqual(externalRequests, []);
    assert.deepEqual(requests.filter(request => request.method === "POST").map(request => request.pathname), marks.map(mark => "/api/work-review/" + mark.id + "/marks"));
  } finally {
    if (releaseDetail) releaseDetail();
    if (releaseMark) releaseMark();
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
});
