"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");
const { chromium } = require("@playwright/test");

test("independent search and page levels bind approval, survive assistant edits, and preserve legacy limits", { timeout: 60000 }, async () => {
  const root = path.resolve(__dirname, "..");
  const state = { id: "release-fixture", version: 1, session_id: "session", instance_id: null, published: null, dirty: true,
    lifecycle: "draft", external_conflict: false,
    capabilities: [{ name: "web.search", title: "Public web search" }, { name: "web.read", title: "Read public websites" }],
    draft: { name: "Daily report", goal: "Daily public AI news", inputs: "PRIVATE-CANARY diagnostics stay here", deliverables: [], tools: ["web.read", "web.search"],
      web_access: { mode: "allowlist", domains: ["example.com"] }, cadence: "manual", timezone: "UTC", time_of_day: "09:00", limits: {} },
    execution: { can_start: false, run: null, schedule: { enabled: false }, readiness: { ready: false, balance_micro_usd: 0, blockers: [] }, messages: [] } };
  let recipient = "fixture-account", approvedDigest = null, releaseVersion = 0, available = true, legacy = false, legacyUnapproved = false, messages = [], posts = [], browserRequests = [];
  function payload() {
    const access = state.draft.web_access || { mode: "off", domains: [] };
    const search = state.draft.web_search || access;
    const enabled = access.mode !== "off" || search.mode !== "off";
    const digest = crypto.createHash("sha256").update(JSON.stringify({ goal: state.draft.goal, access, ...(state.draft.web_search == null ? {} : { search }), recipient })).digest("hex");
    state.public_research_release = { available, legacy, draft_digest: available && enabled ? digest : null, approved_digest: approvedDigest,
      approval_required: legacyUnapproved || enabled && digest !== approvedDigest, version: releaseVersion,
      availability_message: available ? "Web access is ready." : "Web access is unavailable. Reconnect the search service.",
      recipient_label: "Search queries and site rules go to the connected search service. Page requests go to sites within your access level." };
    return { state, messages, usage: null };
  }
  const server = http.createServer(async (req, res) => {
    if (req.url.startsWith("/static/")) {
      const file = path.join(root, "backend/aicl/web/static", path.basename(new URL(req.url, "http://127.0.0.1").pathname));
      res.setHeader("Content-Type", file.endsWith(".css") ? "text/css" : "application/javascript");
      res.end(fs.existsSync(file) ? fs.readFileSync(file) : ""); return;
    }
    if (req.url === "/api/agent-workspaces/release-fixture" && req.method === "GET") { res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify(payload())); return; }
    if (req.method === "POST") {
      let raw = ""; for await (const chunk of req) raw += chunk;
      const body = JSON.parse(raw); posts.push(body); res.setHeader("Content-Type", "application/json");
      assert.equal(body.expected_version, state.version);
      if (body.command === "update_draft") { assert.equal(Object.hasOwn(body.arguments.patch, "inference_enabled"), false); state.draft = { ...state.draft, ...body.arguments.patch }; if (state.draft.web_access) state.draft.tools = [...(state.draft.web_access.mode === "off" ? [] : ["web.read"]), ...((state.draft.web_search || state.draft.web_access).mode === "off" ? [] : ["web.search"])]; state.version++; state.dirty = true; }
      if (req.url.endsWith("/messages")) { state.draft.goal = "A changed public research goal"; state.draft.web_access = { mode: "all", domains: [] }; state.draft.web_search = { mode: "allowlist", domains: ["research.example"] }; state.version++; state.dirty = true; messages.push({ role: "assistant", text: "Proposed a goal and access level for review." }); }
      if (body.command === "apply") {
        if (state.draft.web_access.mode !== "off" || (state.draft.web_search || state.draft.web_access).mode !== "off") {
          assert.equal(available, true);
          if (payload().state.public_research_release.approval_required) {
            assert.equal(body.arguments.approved_public_research_digest, payload().state.public_research_release.draft_digest);
            approvedDigest = body.arguments.approved_public_research_digest; releaseVersion++;
          } else { assert.equal(body.arguments.approved_public_research_digest, undefined); }
        } else { assert.equal(body.arguments.approved_public_research_digest, undefined); approvedDigest = null; }
        legacy = false; legacyUnapproved = false; state.published = structuredClone(state.draft); state.version++; state.dirty = false;
      }
      res.end(JSON.stringify(payload())); return;
    }
    const rendered = spawnSync(path.join(root, ".venv/bin/python"), ["-c", "import json,sys; from aicl.agent_workspace.pages import render_workspace; d=json.load(sys.stdin); print(render_workspace(d['state'], csrf='fixture', account_name='Owner', messages=d['messages'], usage=None))"], { cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, "backend") }, input: JSON.stringify(payload()), encoding: "utf8" });
    if (rendered.status) throw new Error(rendered.stderr);
    res.setHeader("Content-Type", "text/html"); res.end(rendered.stdout);
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = []; page.on("pageerror", err => errors.push(err.message));
    page.on("request", request => browserRequests.push(request.url()));
    const origin = `http://127.0.0.1:${server.address().port}`;
    await page.goto(origin + "/agent-workspaces/release-fixture");
    assert.equal(await page.locator("[data-run-research]").isVisible(), false);
    const approval = page.getByRole("checkbox", { name: /Allow web research for this goal/ });
    const access = page.getByRole("radiogroup", { name: "Web access", exact: true });
    const search = page.getByRole("radiogroup", { name: "Web search", exact: true });
    const goal = page.getByLabel("Goal", { exact: true });
    const save = page.getByRole("button", { name: "Save draft", exact: true });
    const apply = page.getByRole("button", { name: "Apply settings", exact: true });
    assert.equal(await page.getByRole("link", { name: "Permissions", exact: true }).getAttribute("href"), "#workspace-tools");
    const unavailable = page.locator("[data-unavailable-capability]");
    assert.equal(await unavailable.count(), 8);
    assert.deepEqual(await unavailable.evaluateAll(inputs => [...new Set(inputs.map(input => input.dataset.unavailableCapability))]), ["gmail.read", "gmail.send", "reddit.read", "reddit.post"]);
    assert.equal(await unavailable.evaluateAll(inputs => inputs.every(input => input.disabled && input.checked === (input.value === "off"))), true);
    assert.equal(await page.locator("[data-permission-matrix]").getByText("Not yet available", { exact: true }).count(), 4);
    assert.equal(await page.locator('select[name="web_access_mode"], [name="inference_enabled"], [data-permission-row="inference"]').count(), 0);
    assert.equal(await page.getByRole("radiogroup", { name: "AI processing", exact: true }).count(), 0);
    assert.deepEqual(await access.getByRole("radio").evaluateAll(inputs => inputs.map(input => [input.value, input.labels[0].textContent.trim()])), [
      ["off", "Off"], ["allowlist", "Only selected sites"], ["blocklist", "All except selected sites"], ["all", "All public sites"]
    ]);
    const assertPermissionOrder = async () => {
      const groups = await page.locator('[data-permission-matrix] [role="radiogroup"]').evaluateAll(groups => groups.map(group => ({
        name: group.getAttribute('aria-label'),
        boxes: [...group.querySelectorAll('input[type="radio"]')].map(input => {
          const box = input.labels[0].getBoundingClientRect();
          return { left: box.left, right: box.right, top: box.top };
        })
      })));
      for (const group of groups) {
        for (let i = 1; i < group.boxes.length; i++) {
          assert.ok(group.boxes[i].left >= group.boxes[i - 1].right - 1, `${group.name} choices must progress left to right`);
          assert.ok(Math.abs(group.boxes[i].top - group.boxes[0].top) < 2, `${group.name} choices must remain in one row`);
        }
      }
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, 'Permission rows must fit the viewport');
    };
    await assertPermissionOrder();
    assert.equal(await search.locator("input:checked").inputValue(), "allowlist");
    assert.equal(await page.getByLabel("Allowed search sites", { exact: true }).inputValue(), "example.com");
    assert.equal(await search.getByRole("radio").count(), 4);
    const protection = page.locator(".workspace-search-protection");
    assert.equal(await protection.evaluate(element => element.open), false);
    await protection.getByText("How search is protected", { exact: true }).click();
    assert.match(await protection.textContent(), /Brave receives search queries and site rules over HTTPS/);
    assert.match(await protection.textContent(), /Results cannot change permissions/);
    assert.match(await protection.textContent(), /up to 90 days/);
    assert.equal(await protection.getByRole("link", { name: "Brave security" }).getAttribute("rel"), "noopener noreferrer");
    await protection.getByText("How search is protected", { exact: true }).click();
    // Private edits preserve the canonical representation of existing bundled grants.
    approvedDigest = payload().state.public_research_release.draft_digest;
    state.published = structuredClone(state.draft); state.dirty = false;
    await page.reload();
    const originalPrivateInputs = state.draft.inputs;
    await page.getByLabel("Agent name", { exact: true }).fill("Renamed daily report");
    await page.getByLabel("Context and inputs", { exact: true }).fill("PRIVATE-CANARY updated private context");
    await save.click();
    await page.waitForFunction(() => document.querySelector('#workspace-draft-form').getAttribute('aria-busy') === 'false');
    assert.equal(posts.at(-1).arguments.patch.web_search, null);
    assert.equal(state.draft.web_search, null);
    assert.equal(state.public_research_release.draft_digest, approvedDigest);
    assert.equal(state.public_research_release.approval_required, false);
    assert.equal(await approval.isVisible(), false);
    await apply.click();
    await page.waitForFunction(() => document.querySelector('[data-draft-status]').textContent === "Settings applied");
    assert.equal(posts.at(-1).command, "apply");
    assert.equal(posts.at(-1).arguments.approved_public_research_digest, undefined);
    assert.equal(state.published.web_search, null);
    // Changing pages alone freezes the previous inherited search policy explicitly.
    await access.locator('[value="all"]').check();
    await save.click();
    await page.waitForFunction(() => document.querySelector('#workspace-draft-form').getAttribute('aria-busy') === 'false');
    assert.deepEqual(posts.at(-1).arguments.patch.web_search, { mode: "allowlist", domains: ["example.com"] });
    assert.deepEqual(state.draft.web_search, { mode: "allowlist", domains: ["example.com"] });
    assert.equal(state.public_research_release.approval_required, true);
    assert.equal(await search.locator("input:checked").inputValue(), "allowlist");
    // Restore the initial fixture for the independent permission and approval scenarios.
    state.draft.name = "Daily report"; state.draft.inputs = originalPrivateInputs;
    state.draft.web_access = { mode: "allowlist", domains: ["example.com"] };
    delete state.draft.web_search; state.published = null; state.dirty = true;
    approvedDigest = null; state.version++; posts.length = 0;
    await page.reload();
    // Native radios retain arrow-key navigation and use the same saved draft contract.
    await access.locator('[value="allowlist"]').focus();
    await page.keyboard.press("ArrowRight");
    assert.equal(await access.locator('[value="blocklist"]').isChecked(), true);
    await page.keyboard.press("ArrowLeft");
    assert.equal(await access.locator('[value="allowlist"]').isChecked(), true);
    await save.click();
    await page.waitForFunction(() => document.querySelector('#workspace-draft-form').getAttribute('aria-busy') === 'false');
    assert.equal(await page.getByLabel("Allowed sites", { exact: true }).inputValue(), "example.com");
    assert.match(await page.locator("#workspace-web-domains-hint").textContent(), /subdomains/);
    assert.equal(await page.locator('[name="research_queries"], [name="research_source_urls"], [name="research_purpose"], [name="tools"]').count(), 0);
    assert.match(await page.locator("[data-web-disclosure]").textContent(), /Context, files, and conversation are excluded from web research/);
    await approval.check();
    await goal.fill("Recent public AI research");
    assert.equal(await approval.isChecked(), false);
    assert.equal(await approval.isDisabled(), true);
    await save.click();
    await page.waitForFunction(() => !document.querySelector('[data-research-approve]').disabled);
    await approval.check();
    await page.getByLabel("Talk to your assistant", { exact: true }).fill("Change the goal");
    await page.locator("#workspace-assistant-form").getByRole("button", { name: "Send ↑" }).click();
    await page.waitForFunction(() => document.querySelector('[name="goal"]').value === "A changed public research goal");
    assert.equal(await access.locator("input:checked").inputValue(), "all");
    assert.equal(await search.locator("input:checked").inputValue(), "allowlist");
    assert.equal(await page.getByLabel("Allowed search sites", { exact: true }).inputValue(), "research.example");
    assert.equal(await unavailable.evaluateAll(inputs => inputs.every(input => input.disabled && input.checked === (input.value === "off"))), true);
    assert.equal(await approval.isChecked(), false);
    assert.equal(await page.locator("[data-web-domains]").isVisible(), false);
    const beforeApply = posts.filter(item => item.command === "apply").length;
    await apply.click();
    await page.locator("[data-workspace-error]").filter({ hasText: "Review and approve web research" }).waitFor({ state: "visible" });
    assert.equal(posts.filter(item => item.command === "apply").length, beforeApply);
    assert.equal(approvedDigest, null);
    await access.locator('[value="blocklist"]').check();
    await page.getByLabel("Blocked sites", { exact: true }).fill("blocked.example\nother.example");
    await save.click();
    await page.waitForFunction(() => !document.querySelector('[data-research-approve]').disabled);
    await approval.check();
    await apply.click();
    await page.waitForFunction(() => document.querySelector('[data-research-status]').textContent.includes("Web research is approved"));
    assert.equal(releaseVersion, 1);
    assert.equal(state.published.inputs, "PRIVATE-CANARY diagnostics stay here");
    assert.deepEqual(state.published.web_access, { mode: "blocklist", domains: ["blocked.example", "other.example"] });
    assert.deepEqual(state.published.web_search, { mode: "allowlist", domains: ["research.example"] });
    assert.equal(posts.filter(item => item.command === "apply")[0].arguments.approved_public_research_digest, approvedDigest);
    assert.equal(await approval.isVisible(), false);
    // All-sites discards a hidden list rather than accidentally retaining its meaning.
    await access.locator('[value="all"]').check();
    await save.click();
    await page.waitForFunction(() => !document.querySelector('[data-research-approve]').disabled);
    assert.deepEqual(state.draft.web_access, { mode: "all", domains: [] });
    await approval.check();
    await apply.click();
    await page.waitForFunction(() => document.querySelector('[data-research-status]').textContent.includes("Web research is approved"));
    // Search-only and page-only policies use independent controls and derived tools.
    await access.locator('[value="off"]').check();
    await search.locator('[value="blocklist"]').check();
    await page.getByLabel("Blocked search sites", { exact: true }).fill("blocked-search.example");
    assert.equal(await page.locator("[data-web-disclosure]").isVisible(), true);
    await save.click();
    await page.waitForFunction(() => !document.querySelector('[data-research-approve]').disabled);
    await approval.check(); await apply.click();
    await page.waitForFunction(() => document.querySelector('[data-research-status]').textContent.includes("Web research is approved"));
    assert.deepEqual(state.published.web_access, { mode: "off", domains: [] });
    assert.deepEqual(state.published.web_search, { mode: "blocklist", domains: ["blocked-search.example"] });
    assert.deepEqual(state.published.tools, ["web.search"]);
    await access.locator('[value="all"]').check();
    await search.locator('[value="off"]').check();
    assert.equal(await page.locator("[data-search-domains]").isVisible(), false);
    assert.equal(await page.locator("[data-web-disclosure]").isVisible(), true);
    await save.click();
    await page.waitForFunction(() => !document.querySelector('[data-research-approve]').disabled);
    await approval.check(); await apply.click();
    await page.waitForFunction(() => document.querySelector('[data-research-status]').textContent.includes("Web research is approved"));
    assert.deepEqual(state.published.tools, ["web.read"]);
    assert.deepEqual(state.published.web_search, { mode: "off", domains: [] });
    // A changed, unavailable provider cannot authorize a changed research goal.
    available = false; recipient = "changed-provider-account"; state.version++;
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.locator("[data-research-availability]").filter({ hasText: "Reconnect the search service" }).waitFor({ state: "visible" });
    assert.equal(await page.locator("[data-research-approve]").isDisabled(), true);
    assert.equal(state.public_research_release.approval_required, true);
    const beforeChangedGoal = posts.filter(item => item.command === "apply").length;
    await goal.fill("A new goal requiring review");
    await apply.click();
    await page.locator("[data-workspace-error]").filter({ hasText: "Review and approve web research" }).waitFor({ state: "visible" });
    assert.equal(posts.filter(item => item.command === "apply").length, beforeChangedGoal);
    // Revoking web access does not require the unavailable service or another disclosure approval.
    await access.locator('[value="off"]').check();
    assert.equal(await page.locator("[data-web-disclosure]").isVisible(), false);
    assert.equal(await page.locator("[data-web-domains]").isVisible(), false);
    await apply.click();
    await page.waitForFunction(() => document.querySelector("[data-draft-status]").textContent === "Settings applied");
    assert.deepEqual(state.published.web_access, { mode: "off", domains: [] });
    assert.deepEqual(state.published.tools, []);
    // Old exact grants are shown as migration state, never inferred as broad access.
    legacy = true; available = true;
    delete state.draft.web_access; delete state.draft.web_search;
    state.draft.tools = ["web.search"];
    state.draft.public_research = { purpose: "Legacy research", queries: ["AI news"], source_urls: [] };
    await page.reload();
    assert.equal(await access.locator("input:checked").count(), 0);
    assert.equal(await page.locator("[data-legacy-web]").textContent(), "Previous approval — choose a level");
    assert.equal(await page.locator("[data-web-disclosure]").isVisible(), false);
    assert.equal(await page.locator("[data-research-legacy]").isVisible(), true);
    assert.match(await page.locator("[data-research-legacy]").textContent(), /limited to that approval/);
    await page.getByLabel("Agent name", { exact: true }).fill("Legacy report renamed");
    await save.click();
    await page.waitForFunction(() => !document.querySelector('#workspace-draft-form').getAttribute('aria-busy').includes('true'));
    assert.equal(state.draft.web_access, null);
    assert.equal(state.draft.web_search, null);
    assert.deepEqual(state.draft.tools, ["web.search"]);
    assert.deepEqual(state.draft.public_research.queries, ["AI news"]);
    assert.equal(await access.locator("input:checked").count(), 0);
    // A partial legacy migration cannot silently turn on search through bundled inheritance.
    const beforePartialMigration = posts.length;
    await access.locator('[value="all"]').check();
    await save.click();
    await page.locator("[data-workspace-error]").filter({ hasText: "Choose search and page access levels before saving these settings." }).waitFor({ state: "visible" });
    assert.equal(posts.length, beforePartialMigration);
    assert.equal(state.draft.web_access, null);
    assert.equal(state.draft.web_search, null);
    // Off is a real choice from both legacy placeholders, with no intermediate widening.
    await access.locator('[value="off"]').check();
    await search.locator('[value="off"]').check();
    await apply.click();
    await page.waitForFunction(() => document.querySelector("[data-draft-status]").textContent === "Settings applied");
    assert.deepEqual(state.published.web_access, { mode: "off", domains: [] });
    assert.deepEqual(state.published.tools, []);
    assert.equal(await page.locator("[data-research-legacy]").isVisible(), false);
    // An imported, unapproved tool selection must never ask for the removed query fields.
    delete state.draft.web_access; delete state.draft.web_search; state.draft.tools = ["web.search"]; legacyUnapproved = true;
    await page.reload();
    assert.equal(await access.locator("input:checked").count(), 0);
    assert.equal(await page.locator("[data-legacy-web]").textContent(), "Previous settings — choose a level");
    assert.equal(await page.locator("[data-research-legacy]").isVisible(), false);
    const beforeLegacyApply = posts.filter(item => item.command === "apply").length;
    await apply.click();
    await page.locator("[data-workspace-error]").filter({ hasText: "Choose search and page access levels before applying settings." }).waitFor({ state: "visible" });
    assert.equal(posts.filter(item => item.command === "apply").length, beforeLegacyApply);
    await access.locator('[value="off"]').check();
    await search.locator('[value="off"]').check();
    await apply.click();
    await page.waitForFunction(() => document.querySelector("[data-draft-status]").textContent === "Settings applied");
    assert.deepEqual(state.published.web_access, { mode: "off", domains: [] });
    await access.locator('[value="allowlist"]').check();
    assert.equal(await page.getByLabel("Allowed sites", { exact: true }).evaluate(el => el.required), true);
    assert.equal(await page.locator("#workspace-draft-form").evaluate(form => form.checkValidity()), false);
    await page.getByLabel("Allowed sites", { exact: true }).fill("example.com");
    assert.equal(await unavailable.evaluateAll(inputs => inputs.every(input => input.disabled && input.checked === (input.value === "off"))), true);
    assert.equal(browserRequests.every(url => url.startsWith(origin + "/")), true);
    assert.deepEqual(errors, []);
    fs.mkdirSync(path.join(root, ".ctx/workspace-ui"), { recursive: true });
    await page.locator("#workspace-tools").screenshot({ path: path.join(root, ".ctx/workspace-ui/permissions-matrix.png") });
    await page.setViewportSize({ width: 390, height: 844 });
    await assertPermissionOrder();
    await access.locator('[value="allowlist"]').focus();
    await page.keyboard.press("ArrowRight");
    assert.equal(await access.locator('[value="blocklist"]').isChecked(), true);
    assert.equal(await page.getByLabel("Blocked sites", { exact: true }).isVisible(), true);
    await page.keyboard.press("ArrowLeft");
    await page.locator("#workspace-tools").screenshot({ path: path.join(root, ".ctx/workspace-ui/permissions-matrix-mobile.png") });
    // Completed search is reported separately from a historical model reason.
    // Rendering progress never retries paid work or changes the saved reason.
    const historicalReason = "The saved evidence supplies dated headlines but not article-level links or enough verified detail for a credible story digest. No public search or page-read tool is currently available, and the owner requires a source link for each story. I cannot verify or fabricate those links.";
    state.execution.run = { id: "blocked-research-fixture", status: "blocked", objective: "Find recent, credible public AI news with source links and publication dates.",
      reason: historicalReason, plan: [], artifacts: [], can_resume: false,
      public_research: { status: "completed", successful_searches: 2, successful_page_reads: 1, unavailable_page_reads: 4, additional_web_requests_available: false } };
    const beforeProgress = posts.length;
    await page.reload();
    const researchProgress = page.locator("[data-run-research]");
    assert.equal(await researchProgress.textContent(), "Web research: 2 searches completed · 1 page read · 4 pages unavailable.");
    assert.equal(await researchProgress.isVisible(), true);
    assert.equal(await page.locator("[data-run-reason]").textContent(), historicalReason);
    await page.locator("#workspace-progress").screenshot({ path: path.join(root, ".ctx/workspace-ui/research-progress-mobile.png") });
    state.execution.run.public_research = { status: "completed", successful_searches: 1, successful_page_reads: 2, unavailable_page_reads: 1, additional_web_requests_available: false };
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.waitForFunction(() => document.querySelector("[data-run-research]").textContent === "Web research: 1 search completed · 2 pages read · 1 page unavailable.");
    state.execution.run.public_research.status = "running";
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await researchProgress.waitFor({ state: "hidden" });
    delete state.execution.run.public_research;
    await page.reload();
    assert.equal(await researchProgress.isVisible(), false);
    state.execution.run.public_research = { status: "completed", successful_searches: 2, successful_page_reads: 1, unavailable_page_reads: 4, additional_web_requests_available: false };
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await researchProgress.waitFor({ state: "visible" });
    await page.locator("#workspace-progress").screenshot({ path: path.join(root, ".ctx/workspace-ui/research-progress.png") });
    // A model formatting failure is understandable without hiding completed research.
    state.execution.run.reason = "invalid_decision";
    state.execution.run.public_research = { status: "completed", successful_searches: 2, successful_page_reads: 4, unavailable_page_reads: 1, additional_web_requests_available: false };
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.waitForFunction(() => document.querySelector("[data-run-reason]").textContent === "The assistant could not produce a valid reply. Your completed work is saved. Continue work to retry.");
    assert.equal(await researchProgress.textContent(), "Web research: 2 searches completed · 4 pages read · 1 page unavailable.");
    assert.equal(await researchProgress.isVisible(), true);
    assert.doesNotMatch(await page.locator("#workspace-progress").textContent(), /invalid[_ ]decision|refund/i);
    assert.equal(state.execution.run.reason, "invalid_decision");
    await page.locator("#workspace-progress").screenshot({ path: path.join(root, ".ctx/workspace-ui/invalid-reply-progress.png") });
    assert.equal(posts.length, beforeProgress);
    assert.equal(browserRequests.every(url => url.startsWith(origin + "/")), true);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
});
