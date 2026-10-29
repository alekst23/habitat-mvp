"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { chromium } = require("@playwright/test");

// Real browser with deterministic local fixture endpoints; no model or payment provider calls.
test("one workspace keeps owner and assistant edits aligned, gates funding, and preserves conflicts", { timeout: 60000 }, async () => {
  const root = path.resolve(__dirname, "..");
  let state = { id: "test-workspace", version: 1, session_id: "test-session", instance_id: "test-instance", dirty: false,
    lifecycle: "active", capabilities: [{ name: "web.search", title: "Public web search", description: "Discover public sources from a query without supplied URLs." }, { name: "web.read", description: "Read full pages on approved websites." }, { name: "fixture.inspect", title: "Inspect fixture", description: "An executable local fixture tool." }],
    draft: { name: "AI report", goal: "Summarize recent AI news", inputs: "", deliverables: [{ key: "report", name: "Report", description: "A concise report", criteria: ["Cite sources"] }],
      tools: ["web.read", "web.search"], network_domains: ["example.com"], web_access: { mode: "allowlist", domains: ["example.com"] }, cadence: "daily", timezone: "America/New_York", time_of_day: "09:00",
      limits: { inference_daily_micro_usd: 1000000, inference_monthly_micro_usd: 10000000, compute_daily_micro_usd: 1000000, compute_monthly_micro_usd: 10000000 } },
    execution: { can_start: false, runtime_available: true, run: null, schedule: { enabled: false }, messages: [],
      readiness: { ready: false, balance_micro_usd: 0, required_micro_usd: 100000, blockers: [{ reason: "credit_insufficient", message: "Add service credit to start work." }] } } };
  state.published = structuredClone(state.draft);
  let messages = [], requests = [], pageErrors = [], generatedTurns = 0, restartedRuns = 0;
  const acceptedTurns = new Map(), acceptedRestarts = new Map();
  let grossCredit = 0;
  let usage = { scope: "workspace", workspace_id: state.id, raw_spent_micro_usd: 2000, spent_micro_usd: 2000,
    pending_micro_usd: 2000, charged_micro_usd: 0, waived_micro_usd: 0, held_micro_usd: 0, unknown: false, busy: false };
  const payload = () => {
    const readiness = state.execution.readiness;
    readiness.setup = usage;
    readiness.credit_before_setup_micro_usd = grossCredit;
    readiness.balance_micro_usd = grossCredit - (usage.pending_micro_usd || 0) - (usage.held_micro_usd || 0);
    readiness.activation_required_micro_usd = readiness.required_micro_usd + (usage.pending_micro_usd || 0) + (usage.held_micro_usd || 0);
    const run = state.execution.run;
    if (run) {
      run.settings_changed = JSON.stringify(run.allowed_tools) !== JSON.stringify(state.published.tools);
      run.restart_readiness = readiness;
      run.can_restart = ["waiting_owner", "paused", "blocked"].includes(run.status) && !state.dirty && readiness.ready;
      run.restart_blockers = state.dirty ? [{ reason: "unapplied_settings", message: "Apply your draft settings before restarting." }] : [...readiness.blockers];
    }
    return { state, messages, usage };
  };
  function html() {
    const result = spawnSync(path.join(root, ".venv/bin/python"), ["-c", "import json,sys; from aicl.agent_workspace.pages import render_workspace; p=json.load(sys.stdin); print(render_workspace(p['state'], csrf='fixture-csrf', account_name='Fixture Owner', messages=p['messages'], usage=p['usage']))"], { cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, "backend") }, input: JSON.stringify(payload()), encoding: "utf8" });
    if (result.status) throw new Error(result.stderr); return result.stdout;
  }
  const server = http.createServer(async (req, res) => {
    if (req.url.startsWith("/static/")) { const file = path.join(root, "backend/aicl/web/static", path.basename(new URL(req.url, "http://127.0.0.1").pathname)); res.setHeader("Content-Type", file.endsWith(".css") ? "text/css" : "application/javascript"); res.end(fs.existsSync(file) ? fs.readFileSync(file) : ""); return; }
    if (req.url === "/api/agent-workspaces/test-workspace" && req.method === "GET") { res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify(payload())); return; }
    if (req.url.startsWith("/api/agent-workspaces/test-workspace/") && req.method === "POST") {
      let raw = ""; for await (const chunk of req) raw += chunk;
      const body = JSON.parse(raw); requests.push(body); assert.equal(req.headers["x-csrf-token"], "fixture-csrf"); res.setHeader("Content-Type", "application/json");
      const isMessage = req.url.endsWith("/messages");
      if (isMessage && acceptedTurns.has(body.request_id)) { res.end(JSON.stringify({ ...payload(), turn: { ...acceptedTurns.get(body.request_id), replayed: true } })); return; }
      if (body.command === "restart" && acceptedRestarts.has(body.request_id)) { assert.deepEqual(body, acceptedRestarts.get(body.request_id)); res.end(JSON.stringify(payload())); return; }
      if (isMessage && body.text === "Reject this input") { res.statusCode = 400; res.end(JSON.stringify({ error: "validation_failed", message: "This message was not accepted." })); return; }
      if (body.expected_version !== state.version) { res.statusCode = 409; res.end(JSON.stringify({ error: "conflict", message: "Workspace changed." })); return; }
      if (isMessage) {
        generatedTurns += 1;
        usage.raw_spent_micro_usd += 1000; usage.spent_micro_usd += 1000; usage.pending_micro_usd += 1000;
        assert.equal(state.draft.goal, "A weekly AI report for our team");
        state.draft.time_of_day = "10:00"; state.version += 1; state.dirty = true;
        const recovery = body.text === "Save before reply failure" || body.text === "Save before connection loss";
        if (recovery) state.draft.inputs = "Saved: " + body.text;
        messages.push({ role: "user", text: body.text }, recovery ? { role: "assistant", kind: "recovery", failure_reason: "reply_unavailable", text: "Your draft changes were saved, but the assistant could not finish its reply. Review the settings before applying them." } : { role: "assistant", text: "Updated to 10 a.m. <img src=x onerror='window.injected=true'>" });
        const turn = { accepted: true, status: recovery ? "failed" : "completed", request_id: body.request_id };
        acceptedTurns.set(body.request_id, turn);
        res.end(JSON.stringify({ ...payload(), turn })); return;
      }
      if (body.command === "update_draft") { assert.equal(Object.hasOwn(body.arguments.patch, "inference_enabled"), false); state.draft = { ...state.draft, ...body.arguments.patch }; state.draft.tools = [...state.draft.tools.filter(name => !["web.read", "web.search"].includes(name)), ...(state.draft.web_access.mode === "off" ? [] : ["web.read"]), ...((state.draft.web_search || state.draft.web_access).mode === "off" ? [] : ["web.search"])]; state.draft.network_domains = [...state.draft.web_access.domains]; state.version += 1; state.dirty = true; }
      if (body.command === "apply") { state.inference_grant_missing = false; state.published = structuredClone(state.draft); state.dirty = false; state.version += 1; }
      if (body.command === "start") { grossCredit -= usage.pending_micro_usd; usage.charged_micro_usd += usage.pending_micro_usd; usage.pending_micro_usd = 0; state.execution.run = { id: "run-1", version: 1, status: "queued", objective: state.draft.goal, plan: [], artifacts: [], question: null, allowed_tools: [...state.published.tools], can_advance: true, can_pause: true, can_cancel: true }; state.execution.can_start = false; }
      if (body.command === "advance") { state.execution.run.status = "running"; state.execution.run.can_advance = false; }
      if (body.command === "resume") {
        assert.equal(body.arguments.expected_run_version, state.execution.run.version);
        assert.equal(state.execution.run.local_read_recovery_available, true);
        state.execution.run = { ...state.execution.run, status: "blocked", reason: "platform_spend_ceiling",
          version: state.execution.run.version + 1, local_read_recovery_available: false, can_resume: false, can_advance: false };
        state.execution.readiness.ready = false;
        state.execution.readiness.blockers = [{ reason: "platform_spend_ceiling", message: "The server's API spending limit is reached." }];
      }
      if (body.command === "restart") {
        const previous = state.execution.run;
        assert.equal(body.arguments.run_id, previous.id);
        assert.equal(body.arguments.expected_run_version, previous.version);
        assert.equal(previous.can_restart, true);
        state.execution.history = [{ ...structuredClone(previous), status: "cancelled" }];
        state.execution.run = { id: "replacement-run", version: 1, status: "queued", objective: state.published.goal, plan: [], artifacts: [], question: null, allowed_tools: [...state.published.tools], can_advance: true, can_pause: true, can_cancel: true };
        state.version += 1; restartedRuns += 1;
        acceptedRestarts.set(body.request_id, structuredClone(body));
      }
      res.end(JSON.stringify({ ...payload(), ...(body.command === "fund" ? { redirect_url: "/commerce/orders/fixture-order" } : {}) })); return;
    }
    if (req.url === "/commerce/orders/fixture-order") { res.end("<h1>Mock checkout</h1>"); return; }
    res.setHeader("Content-Type", "text/html"); res.end(html());
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on("pageerror", err => pageErrors.push(err.message));
    await page.addInitScript(() => { window.workspaceTools = []; Object.defineProperty(navigator, "modelContext", { value: { registerTool: tool => window.workspaceTools.push(tool) } }); });
    const url = `http://127.0.0.1:${server.address().port}/agent-workspaces/test-workspace`;
    await page.goto(url);
    assert.match(await page.locator('script[src*="agent-workspace.js"]').getAttribute("src"), /^\/static\/agent-workspace\.js\?v=[0-9a-f]{16}$/);
    assert.match(await page.locator('link[href*="agent-workspace.css"]').getAttribute("href"), /^\/static\/agent-workspace\.css\?v=[0-9a-f]{16}$/);
    const desktopLayout = await page.evaluate(() => {
      const main = document.querySelector('.workspace-main').getBoundingClientRect();
      const assistant = document.querySelector('#workspace-assistant').getBoundingClientRect();
      return { mainRight: main.right, assistantLeft: assistant.left, mainTop: main.top, assistantTop: assistant.top,
        settingsInForm: ['cadence', 'timezone', 'inference_daily_micro_usd'].every(name =>
          document.querySelector(`[name="${name}"]`).form?.id === 'workspace-draft-form') };
    });
    fs.mkdirSync(path.join(root, '.ctx/workspace-ui'), { recursive: true });
    await page.screenshot({ path: path.join(root, '.ctx/workspace-ui/desktop-layout.png') });
    assert.ok(desktopLayout.assistantLeft >= desktopLayout.mainRight, 'Desktop chat must stay beside the settings');
    assert.ok(Math.abs(desktopLayout.assistantTop - desktopLayout.mainTop) < 2, 'Desktop chat starts at the top of the workspace');
    assert.equal(desktopLayout.settingsInForm, true, 'Settings after public research must remain in the draft form');
    assert.equal(await page.locator("[data-assistant-usage]").textContent(), "Setup cost: $0.002 for this agent.");
    assert.equal(await page.locator("[data-setup-pending]").textContent(), "$0.002");
    assert.equal(await page.locator("[data-credit-balance]").textContent(), "$0.00");
    assert.match(await page.locator("[data-setup-shortfall]").textContent(), /\$0\.002/);
    assert.equal(await page.getByRole("button", { name: /reset/i }).count(), 0);
    // Old global operator allowance or another workspace's usage must never become this agent's cost.
    const scopedUsage = usage;
    usage = { ...scopedUsage, held_micro_usd: 3000, unknown: true };
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.waitForFunction(() => document.querySelector("[data-setup-held]").textContent === "$0.003");
    assert.equal(await page.locator("[data-assistant-usage]").textContent(), "Setup cost: $0.002 for this agent. Some setup usage is still being confirmed.");
    assert.match(await page.locator("[data-setup-shortfall]").textContent(), /\$0\.005/);
    usage = { spent_micro_usd: 987654, cap_micro_usd: 1000000 };
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.waitForFunction(() => document.querySelector("[data-assistant-usage]").textContent === "Setup cost unavailable for this agent.");
    assert.doesNotMatch(await page.locator("[data-assistant-usage]").textContent(), /allowance|limit|0\.987654/);
    usage = { ...scopedUsage, workspace_id: "a-different-agent" };
    await page.reload();
    assert.equal(await page.locator("[data-assistant-usage]").textContent(), "Setup cost unavailable for this agent.");
    usage = { ...scopedUsage, waived_micro_usd: 2000, spent_micro_usd: 0, pending_micro_usd: 0 };
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.waitForFunction(() => document.querySelector("[data-assistant-usage]").textContent === "Setup cost: $0.00 for this agent.");
    assert.equal(await page.locator("[data-setup-pending]").textContent(), "$0.00");
    assert.equal(await page.getByRole("button", { name: "Start work", exact: true }).isDisabled(), true);
    assert.equal(await page.getByRole("button", { name: "Add funds with PayPal" }).isEnabled(), true);
    const access = page.getByRole("radiogroup", { name: "Web access", exact: true });
    const search = page.getByRole("radiogroup", { name: "Web search", exact: true });
    const domains = page.getByLabel("Allowed sites", { exact: true });
    assert.equal(await access.locator("input:checked").inputValue(), "allowlist");
    assert.equal(await domains.inputValue(), "example.com");
    await access.locator('[value="off"]').check();
    assert.equal(await page.locator("[data-web-domains]").isVisible(), false);
    await access.locator('[value="blocklist"]').check();
    assert.equal(await page.getByLabel("Blocked sites", { exact: true }).inputValue(), "example.com");
    await access.locator('[value="all"]').check();
    assert.equal(await page.locator("[data-web-domains]").isVisible(), false);
    assert.equal(await page.locator('[data-tool-permission="fixture.inspect"]').count(), 2);
    const inspectPermission = page.getByRole("radiogroup", { name: "Inspect fixture", exact: true });
    assert.equal(await inspectPermission.getByRole("radio", { name: "Allow", exact: true }).isEnabled(), true);
    await inspectPermission.getByRole("radio", { name: "Allow", exact: true }).check();
    assert.equal(await page.locator('[name="inference_enabled"], [data-permission-row="inference"]').count(), 0);
    const visibleDraft = await page.evaluate(async () => JSON.parse((await window.workspaceTools.find(tool => tool.name === "habitat_read_workspace").execute()).content[0].text).visible_draft);
    assert.equal(Object.hasOwn(visibleDraft, "inference_enabled"), false);
    assert.deepEqual(visibleDraft.web_access, { mode: "all", domains: [] });
    assert.deepEqual(visibleDraft.web_search, { mode: "allowlist", domains: ["example.com"] });
    assert.equal(await search.locator("input:checked").inputValue(), "allowlist");
    assert.ok(visibleDraft.tools.includes("fixture.inspect"));
    assert.equal(await page.getByLabel("Context and inputs").inputValue(), "");
    await page.getByLabel("Agent name", { exact: true }).fill("");
    await page.getByRole("button", { name: "Save draft", exact: true }).click();
    await page.waitForFunction(() => document.querySelector("[data-draft-status]").textContent === "Unapplied changes");
    assert.equal(state.draft.name, "");
    assert.ok(state.draft.tools.includes("fixture.inspect"));
    assert.equal(await inspectPermission.getByRole("radio", { name: "Allow", exact: true }).isChecked(), true);
    await inspectPermission.getByRole("radio", { name: "Off", exact: true }).check();
    await page.getByLabel("Agent name", { exact: true }).fill("AI report");
    await page.getByLabel("Goal", { exact: true }).fill("A weekly AI report for our team");
    await page.getByLabel("Talk to your assistant", { exact: true }).fill("Move it to 10 a.m.");
    await page.locator("#workspace-assistant-form").getByRole("button", { name: "Send ↑" }).click();
    await page.waitForFunction(() => document.getElementById("workspace-time").value === "10:00");
    assert.equal(requests[0].command, "update_draft");
    assert.equal(requests.find(request => request.text).text, "Move it to 10 a.m.");
    assert.equal(await page.getByLabel("Goal", { exact: true }).inputValue(), "A weekly AI report for our team");
    assert.equal(await page.evaluate(() => window.injected), undefined);
    await page.getByRole("button", { name: "Apply settings", exact: true }).click();
    await page.waitForFunction(() => document.querySelector("[data-draft-status]").textContent === "Settings applied");
    assert.deepEqual(state.published.tools, ["web.read", "web.search"]);
    assert.deepEqual(state.published.web_access, { mode: "all", domains: [] });
    assert.deepEqual(state.published.web_search, { mode: "allowlist", domains: ["example.com"] });
    assert.deepEqual(state.published.network_domains, []);
    assert.equal(state.execution.run, null);
    assert.equal(await page.getByRole("button", { name: "Start work", exact: true }).isDisabled(), true);
    await page.getByRole("button", { name: "Add funds with PayPal" }).click();
    await page.waitForURL("**/commerce/orders/fixture-order");
    assert.equal(requests.at(-1).arguments.amount_minor, 500);
    grossCredit = 5000000;
    state.execution.readiness = { ready: true, balance_micro_usd: 5000000, required_micro_usd: 100000, blockers: [] }; state.execution.can_start = true;
    await page.goto(url);
    assert.equal(await page.locator("[data-credit-before-setup]").textContent(), "$5.00");
    assert.equal(await page.locator("[data-setup-pending]").textContent(), "$0.001");
    assert.equal(await page.locator("[data-credit-balance]").textContent(), "$4.999");
    await page.getByRole("button", { name: "Start work", exact: true }).click();
    await page.waitForFunction(() => document.querySelector("[data-run-status]").textContent === "Ready to continue");
    assert.equal(await page.locator("[data-setup-pending]").textContent(), "$0.00");
    assert.equal(await page.locator("[data-setup-paid]").textContent(), "$0.001");
    assert.equal(await page.locator("[data-credit-before-setup]").textContent(), "$4.999");
    assert.equal(await page.locator("[data-credit-balance]").textContent(), "$4.999");
    await page.getByLabel("Context and inputs").fill("Keep this pending edit");
    assert.equal(await page.getByRole("button", { name: "Continue work", exact: true }).isEnabled(), true);
    await page.getByRole("button", { name: "Continue work", exact: true }).click();
    await page.waitForFunction(() => document.querySelector("[data-run-status]").textContent === "Working");
    assert.equal(requests.at(-1).command, "advance");
    assert.equal(await page.getByLabel("Context and inputs").inputValue(), "Keep this pending edit");
    state.version += 1; state.draft.inputs = "Another tab changed this";
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.locator("[data-workspace-conflict]").waitFor({ state: "visible" });
    assert.equal(await page.getByLabel("Context and inputs").inputValue(), "Keep this pending edit");
    await page.getByRole("button", { name: "Reapply my edits", exact: true }).click();
    await page.locator("[data-workspace-conflict]").waitFor({ state: "hidden" });
    assert.equal(state.draft.inputs, "Keep this pending edit");
    assert.equal(await page.locator("#workspace-assistant-form").isVisible(), true);
    assert.deepEqual(await page.evaluate(() => window.workspaceTools.map(tool => tool.name)), ["habitat_read_workspace", "habitat_update_draft", "habitat_show_section"]);
    await page.getByRole("button", { name: "Hide assistant", exact: true }).click();
    await page.reload();
    assert.equal(await page.locator("#workspace-assistant").isVisible(), false);
    await page.getByRole("button", { name: "Show assistant", exact: true }).click();
    // Accepted tool changes and a failed final reply are one finished turn, not a retry prompt.
    const composer = page.getByLabel("Talk to your assistant", { exact: true });
    const sendMessage = page.locator("#workspace-assistant-form").getByRole("button", { name: "Send ↑" });
    const turnsBeforeRecovery = generatedTurns;
    await composer.fill("Save before reply failure");
    await sendMessage.click();
    await page.waitForFunction(() => document.getElementById("workspace-message").value === "");
    assert.equal(await page.getByLabel("Context and inputs").inputValue(), "Saved: Save before reply failure");
    assert.equal(await page.locator("[data-management-messages] .workspace-message").filter({ hasText: "Habitat status" }).count(), 1);
    assert.equal(await page.locator("[data-workspace-error]").isVisible(), false);
    assert.equal(generatedTurns, turnsBeforeRecovery + 1);
    await page.reload();
    assert.equal(await page.locator("[data-management-messages] .workspace-message").filter({ hasText: "Habitat status" }).count(), 1);
    await composer.fill("Reject this input");
    await sendMessage.click();
    await page.locator("[data-workspace-error]").filter({ hasText: "This message was not accepted." }).waitFor({ state: "visible" });
    assert.equal(await composer.inputValue(), "Reject this input");
    assert.equal(messages.filter(message => message.text === "Reject this input").length, 0);
    assert.equal(generatedTurns, turnsBeforeRecovery + 1);
    // Drop the response after the fixture server commits, without letting Chromium retry a closed socket.
    let responseDropped = false;
    await page.route("**/api/agent-workspaces/test-workspace/messages", async route => {
      if (route.request().postDataJSON().text === "Save before connection loss" && !responseDropped) {
        responseDropped = true;
        await route.fetch();
        await route.abort("internetdisconnected");
      } else await route.continue();
    });
    // An explicit retry reuses the original ID and version.
    await composer.fill("Save before connection loss");
    await sendMessage.click();
    await page.waitForFunction(() => !document.querySelector("[data-workspace-error]").hidden && document.querySelector("#workspace-assistant-form button").disabled === false);
    const lostRequest = requests.at(-1);
    assert.equal(await composer.inputValue(), "Save before connection loss");
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.waitForFunction(() => document.getElementById("workspace-inputs").value === "Saved: Save before connection loss");
    const costBeforeReplay = await page.locator("[data-assistant-usage]").textContent();
    await sendMessage.click();
    await page.waitForFunction(() => document.getElementById("workspace-message").value === "");
    assert.equal(await page.locator("[data-assistant-usage]").textContent(), costBeforeReplay);
    const replayRequest = requests.at(-1);
    assert.equal(replayRequest.request_id, lostRequest.request_id);
    assert.equal(replayRequest.expected_version, lostRequest.expected_version);
    assert.equal(generatedTurns, turnsBeforeRecovery + 2);
    assert.equal(messages.filter(message => message.role === "user" && message.text === "Save before connection loss").length, 1);
    assert.equal(await page.locator("[data-workspace-error]").isVisible(), false);
    // The waiting worker keeps its original tools; applying search prepares a separate run.
    state.execution.run = { id: "waiting-run", version: 7, status: "waiting_owner", objective: state.published.goal, allowed_tools: [], plan: [], artifacts: [], can_cancel: true,
      question: { id: "sources-question", question: "Which sources should I summarize?", options: ["Enable public web search"] } };
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    const restart = page.getByRole("button", { name: "Restart with updated settings", exact: true });
    await restart.waitFor({ state: "visible" });
    assert.equal(await restart.isDisabled(), true);
    assert.match(await page.locator("[data-run-settings-message]").textContent(), /Save and apply/);
    const requestsBeforeSuggestion = requests.length;
    await page.getByRole("button", { name: "Enable public web search", exact: true }).click();
    assert.equal(await page.getByLabel("Answer the agent’s question", { exact: true }).inputValue(), "Enable public web search");
    assert.equal(requests.length, requestsBeforeSuggestion);
    assert.deepEqual(state.execution.run.allowed_tools, []);
    await page.getByRole("button", { name: "Apply settings", exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('[data-command="restart"]').disabled);
    assert.equal(state.execution.run.id, "waiting-run");
    assert.deepEqual(state.execution.run.allowed_tools, []);
    assert.equal(restartedRuns, 0);
    assert.match(await page.locator("[data-run-settings-message]").textContent(), /still uses its original settings/);
    fs.mkdirSync(path.join(root, ".ctx/workspace-ui"), { recursive: true });
    await page.locator("#workspace-tools").screenshot({ path: path.join(root, ".ctx/workspace-ui/search-tools.png") });
    await page.locator("#workspace-progress").screenshot({ path: path.join(root, ".ctx/workspace-ui/restart.png") });
    // A lost restart response retries the same saved request, even after replacement changed the version.
    let restartResponseDropped = false;
    await page.route("**/api/agent-workspaces/test-workspace/commands", async route => {
      if (route.request().postDataJSON().command === "restart" && !restartResponseDropped) {
        restartResponseDropped = true; await route.fetch(); await route.abort("internetdisconnected");
      } else await route.continue();
    });
    await restart.click();
    await page.waitForFunction(() => !document.querySelector("[data-workspace-error]").hidden && !document.querySelector('[data-command="restart"]').disabled);
    const originalRestartRequest = requests.at(-1);
    await restart.click();
    await page.waitForFunction(() => document.querySelector("[data-run-status]").textContent === "Ready to continue");
    assert.deepEqual(requests.at(-1), originalRestartRequest);
    assert.equal(originalRestartRequest.arguments.expected_run_version, 7);
    assert.equal(restartedRuns, 1);
    assert.equal(state.execution.run.id, "replacement-run");
    assert.deepEqual(state.execution.run.allowed_tools, ["web.read", "web.search"]);
    assert.deepEqual(state.execution.history[0].allowed_tools, []);
    assert.equal(state.execution.history[0].status, "cancelled");
    assert.equal(await restart.isVisible(), false);
    assert.equal(await page.locator("[data-workspace-error]").isVisible(), false);
    // An existing agent can repair its internal processing grant without a permission toggle or draft edit.
    state.inference_grant_missing = true;
    const repairDraft = structuredClone(state.draft);
    const updatesBeforeRepair = requests.filter(request => request.command === "update_draft").length;
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.waitForFunction(() => document.querySelector("[data-save-status]").textContent === "Apply settings to restore agent processing.");
    const repairApply = page.getByRole("button", { name: "Apply settings", exact: true });
    assert.equal(await repairApply.isEnabled(), true);
    assert.equal(state.dirty, false);
    assert.deepEqual(state.draft, state.published);
    await repairApply.click();
    await page.waitForFunction(() => document.querySelector("[data-save-status]").textContent === "Your settings are applied.");
    assert.equal(requests.at(-1).command, "apply");
    assert.equal(requests.filter(request => request.command === "update_draft").length, updatesBeforeRepair);
    assert.equal(state.inference_grant_missing, false);
    assert.deepEqual(state.draft, repairDraft);
    assert.equal(await repairApply.isDisabled(), true);
    assert.equal(await page.locator('[name="inference_enabled"], [data-permission-row="inference"]').count(), 0);
    // A settled research failure needs an explicit new run, even with unchanged settings.
    state.execution.run = { id: "failed-research-run", version: 9, status: "blocked", reason: "public_research_failed",
      research_restart_required: true, objective: state.published.goal, allowed_tools: [...state.published.tools],
      plan: [], artifacts: [], can_resume: false, can_advance: false, can_cancel: true };
    const beforeResearchRetry = requests.length;
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    const researchRetry = page.getByRole("button", { name: "Retry research", exact: true });
    await researchRetry.waitFor({ state: "visible" });
    assert.equal(await researchRetry.isEnabled(), true);
    assert.equal(await page.getByRole("button", { name: "Continue work", exact: true }).isVisible(), false);
    assert.equal(requests.length, beforeResearchRetry, "Displaying recovery cannot perform an automatic retry");
    assert.match(await page.locator("[data-run-reason]").textContent(), /Web research could not finish/);
    assert.doesNotMatch(await page.locator("#workspace-progress").textContent(), /public_research_failed/);
    assert.match(await page.locator("[data-run-settings-message]").textContent(), /new run.*history and charges.*additional charges/);
    state.execution.readiness.ready = false;
    state.execution.readiness.blockers = [{ reason: "credit_insufficient", message: "Add service credit to start work." }];
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.waitForFunction(() => document.querySelector('[data-command="restart"]').disabled);
    assert.match(await page.locator("[data-restart-blockers]").textContent(), /Add service credit/);
    state.execution.readiness.ready = true;
    state.execution.readiness.blockers = [];
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('[data-command="restart"]').disabled);
    assert.equal(requests.length, beforeResearchRetry);
    await page.locator("#workspace-progress").screenshot({ path: path.join(root, ".ctx/workspace-ui/research-retry.png") });
    await researchRetry.click();
    await page.waitForFunction(() => document.querySelector("[data-run-status]").textContent === "Ready to continue");
    assert.equal(requests.length, beforeResearchRetry + 1);
    assert.equal(requests.at(-1).command, "restart");
    assert.equal(requests.at(-1).arguments.run_id, "failed-research-run");
    assert.equal(requests.at(-1).arguments.expected_run_version, 9);
    assert.equal(restartedRuns, 2);
    assert.equal(state.execution.history[0].id, "failed-research-run");
    assert.equal(state.execution.history[0].status, "cancelled");
    assert.equal(await researchRetry.isVisible(), false);
    // Continue recovers only a server-verified local read, with the viewed run version.
    state.execution.run = { id: "local-read-run", version: 14, status: "blocked", reason: "unknown_outcome",
      local_read_recovery_available: true, objective: state.published.goal, allowed_tools: [...state.published.tools],
      plan: [], artifacts: [], can_resume: true, can_advance: false, can_cancel: true };
    state.execution.readiness.ready = false;
    state.execution.readiness.blockers = [{ reason: "reconciliation_pending", message: "Resolve the earlier operation." }];
    const beforeLocalRecovery = requests.length;
    await page.getByRole("button", { name: "Refresh progress", exact: true }).click();
    const continueLocal = page.getByRole("button", { name: "Continue work", exact: true });
    await page.waitForFunction(() => document.querySelector("[data-run-reason]").textContent.includes("saved-source read"));
    assert.equal(await continueLocal.isEnabled(), true);
    assert.equal(requests.length, beforeLocalRecovery);
    await continueLocal.click();
    await page.waitForFunction(() => document.querySelector("[data-run-reason]").textContent.includes("server’s API spending limit"));
    assert.equal(await continueLocal.isDisabled(), true);
    assert.match(await page.locator("[data-workspace-notice]").textContent(), /saved-source read is recovered.*blocker/);
    assert.equal(requests.length, beforeLocalRecovery + 1);
    assert.equal(requests.at(-1).command, "resume");
    assert.equal(requests.at(-1).arguments.run_id, "local-read-run");
    assert.equal(requests.at(-1).arguments.expected_run_version, 14);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => window.scrollTo(0, 0));
    const mobileMain = await page.locator('.workspace-main').boundingBox();
    const mobileAssistant = await page.locator('#workspace-assistant').boundingBox();
    assert.ok(mobileAssistant.y + mobileAssistant.height <= mobileMain.y, 'Mobile chat must appear above settings');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    fs.mkdirSync(path.join(root, ".ctx/workspace-ui"), { recursive: true });
    await page.screenshot({ path: path.join(root, ".ctx/workspace-ui/mobile.png"), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('#workspace-results').scrollIntoViewIfNeeded();
    const stickyAssistant = await page.locator('#workspace-assistant').boundingBox();
    assert.ok(stickyAssistant.y >= 0 && stickyAssistant.y < 40, 'Desktop chat stays visible while scrolling settings');
    await page.screenshot({ path: path.join(root, ".ctx/workspace-ui/desktop.png"), fullPage: true });
    await page.locator("#workspace-funding").screenshot({ path: path.join(root, ".ctx/workspace-ui/funding.png") });
    assert.deepEqual(pageErrors, []);
  } finally { if (browser) await browser.close(); await new Promise(resolve => server.close(resolve)); }
});
