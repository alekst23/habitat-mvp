(function () {
  "use strict";
  var root = document.querySelector("[data-agent-workspace]");
  if (!root) return;
  var initial = JSON.parse(document.getElementById("agent-workspace-data").textContent);
  var state = initial.state, localDirty = false, busy = false, conflict = null, pollTimer = null, operationEpoch = 0;
  var draftForm = document.getElementById("workspace-draft-form");
  var assistantForm = document.getElementById("workspace-assistant-form");
  var assistantInput = document.getElementById("workspace-message");
  var runForm = document.getElementById("workspace-run-message-form");
  var runInput = document.getElementById("workspace-run-message");
  var runMessageTarget = null, deliveryAttempt = null, managementMessages = initial.messages || [], renderedDraft = false;
  var approvedDisclosure = null, renderedResultRunId = null;
  var endpoint = "/api/agent-workspaces/" + encodeURIComponent(root.dataset.workspaceId);
  var limitKeys = ["inference_daily_micro_usd", "inference_monthly_micro_usd", "compute_daily_micro_usd", "compute_monthly_micro_usd"];
  var terminal = ["completed", "cancelled", "failed"];
  var statusLabels = { queued: "Ready to continue", running: "Working", waiting_owner: "Needs your input", blocked: "Blocked", paused: "Paused", completed: "Completed", failed: "Failed", cancelled: "Cancelled" };
  function $(selector) { return root.querySelector(selector); }
  function node(tag, className, text) { var el = document.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = text; return el; }
  function text(selector, value) { $(selector).textContent = value || ""; }
  function money(value) { return "$" + (Number(value || 0) / 1000000).toFixed(6).replace(/0{1,4}$/, ""); }
  function toolTitle(name) { return { "web.search": "Public web search", "web.read": "Read approved websites" }[name] || name; }
  function isWebTool(name) { return ["web.search", "web.read", "web_search"].includes(name); }
  function dedicatedPermission(name) { return name === "inference" || ["gmail.read", "gmail.send", "reddit.read", "reddit.post"].includes(name); }
  var webPolicies = [{ key: "web_search", prefix: "search" }, { key: "web_access", prefix: "web" }];
  function selectedWebAccess() { return webPolicies.some(function (policy) { return ["allowlist", "blocklist", "all"].includes(field(policy.key + "_mode").value); }); }
  function legacyWebDraft() { return state.draft.web_access == null && state.draft.web_search == null && ((state.public_research_release || {}).legacy || (state.draft.tools || []).some(isWebTool)); }
  function syncToolControls() {
    webPolicies.forEach(function (policy) {
      var mode = field(policy.key + "_mode").value, search = policy.key === "web_search";
      $("[data-" + policy.prefix + "-domains]").hidden = !["allowlist", "blocklist"].includes(mode);
      $("[data-legacy-" + policy.prefix + "]").hidden = mode !== "" || !legacyWebDraft();
      field(policy.key + "_domains").required = mode === "allowlist";
      text("[data-" + policy.prefix + "-domains-label]", (mode === "blocklist" ? "Blocked" : "Allowed") + (search ? " search sites" : " sites"));
      var hints = search ? { off: "Search is off.", allowlist: "Find results only from these sites.", blocklist: "Find results from public sites except those listed below.", all: "Find results from any public site." } : { off: "Page reading is off.", allowlist: "Read pages only from these sites.", blocklist: "Read public pages except on the sites listed below.", all: "Read pages from any public site." };
      hints[""] = (state.public_research_release || {}).legacy ? "Your previous permission stays in place until you choose levels and apply." : "Choose an access level before applying these settings.";
      text("[data-" + policy.prefix + "-access-hint]", hints[mode]);
    });
    $("[data-web-disclosure]").hidden = !selectedWebAccess();
  }
  function renderResearch() {
    var release = state.public_research_release || {}, checkbox = $("[data-research-approve]");
    var selected = selectedWebAccess();
    if (approvedDisclosure && (localDirty || approvedDisclosure.version !== state.version || approvedDisclosure.digest !== release.draft_digest)) approvedDisclosure = null;
    checkbox.checked = !!approvedDisclosure;
    checkbox.disabled = busy || localDirty || !release.available || !release.approval_required || !release.draft_digest;
    $("[data-research-approval]").hidden = !selected || !release.approval_required;
    $("[data-research-availability]").hidden = !selected || !!release.available;
    $("[data-research-legacy]").hidden = !release.legacy;
    text("[data-research-availability]", release.availability_message || "Web research is unavailable. Connect a search service before enabling it.");
    text("[data-research-recipient]", release.recipient_label || "");
    text("[data-research-status]", localDirty ? "Save the draft to review web research." : !selected ? "Web research is off." : !release.available ? "You can save these settings and approve web research when the service is available." : release.approval_required ? "Review the goal and both access levels, then approve and apply." : "Web research is approved for this goal. Future runs can use the same permission.");
  }
  function scopedUsage(value) { return value && value.scope === "workspace" && value.workspace_id === state.id ? value : null; }
  function requestId() { if (window.crypto && crypto.randomUUID) return crypto.randomUUID(); return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) { var value = Math.floor(Math.random() * 16); return (c === "x" ? value : (value & 3) | 8).toString(16); }); }
  function lines(value) { return value.split(/\r?\n/).map(function (v) { return v.trim(); }).filter(Boolean); }
  function error(message) { text("[data-workspace-error]", message); $("[data-workspace-error]").hidden = !message; }
  function notice(message) { text("[data-workspace-notice]", message); $("[data-workspace-notice]").hidden = !message; }
  function focusSection(section) { section = { outcome: "goal", work: "progress" }[section] || section; var target = document.getElementById("workspace-" + section); if (target) { target.scrollIntoView({ behavior: "smooth", block: "start" }); target.focus({ preventScroll: true }); } }
  function field(name) { return draftForm.elements.namedItem(name); }
  function serializeDraft() {
    var preserveLegacy = legacyWebDraft() && webPolicies.some(function (policy) { return field(policy.key + "_mode").value === ""; });
    var patch = { name: field("name").value.trim(), goal: field("goal").value.trim(), inputs: field("inputs").value,
      cadence: field("cadence").value, timezone: field("timezone").value.trim(), time_of_day: field("time_of_day").value || "09:00",
      tools: Array.from(draftForm.querySelectorAll('[data-tool-permission][value="allow"]:checked')).map(function (el) { return el.dataset.toolPermission; }).concat(preserveLegacy ? (state.draft.tools || []).filter(isWebTool) : []),
      limits: {}, deliverables: [] };
    webPolicies.forEach(function (policy) {
      var mode = field(policy.key + "_mode").value;
      patch[policy.key] = mode === "" && legacyWebDraft() ? null : { mode: mode, domains: ["allowlist", "blocklist"].includes(mode) ? lines(field(policy.key + "_domains").value) : [] };
    });
    // Keep an unchanged bundled grant in its original form so private edits do not
    // change its disclosure digest. A page change freezes the prior search scope.
    var priorAccess = state.draft.web_access;
    function samePolicy(left, right) { return !!left && !!right && left.mode === right.mode && JSON.stringify(left.domains || []) === JSON.stringify(right.domains || []); }
    if (state.draft.web_search == null && samePolicy(patch.web_access, priorAccess) && samePolicy(patch.web_search, priorAccess)) patch.web_search = null;
    limitKeys.forEach(function (key) { patch.limits[key] = Math.round(Number(field(key).value || 0) * 1000000); });
    draftForm.querySelectorAll("[data-deliverable]").forEach(function (row) { patch.deliverables.push({ key: row.dataset.key,
      name: row.querySelector("[data-deliverable-name]").value.trim(), description: row.querySelector("[data-deliverable-description]").value,
      criteria: lines(row.querySelector("[data-deliverable-criteria]").value) }); });
    return patch;
  }
  function addDeliverable(value) {
    var row = node("div", "workspace-deliverable"), key = value.key || "deliverable_" + requestId().replace(/-/g, "");
    row.dataset.deliverable = ""; row.dataset.key = key;
    [["name", "Name", "input"], ["description", "Description", "textarea"], ["criteria", "Completion criteria · one per line", "textarea"]].forEach(function (spec) {
      var wrap = node("div", "field"), label = node("label", "", spec[1]), input = node(spec[2]);
      input.id = "deliverable-" + key + "-" + spec[0]; label.htmlFor = input.id;
      input.setAttribute("data-deliverable-" + spec[0], ""); input.value = spec[0] === "criteria" ? (value.criteria || []).join("\n") : value[spec[0]] || "";
      if (spec[2] === "textarea") input.rows = spec[0] === "criteria" ? 3 : 2;
      if (spec[0] === "name") input.maxLength = 120; if (spec[0] === "description") input.maxLength = 2000;
      wrap.append(label, input); row.appendChild(wrap);
    });
    var remove = node("button", "ghost", "Remove deliverable"); remove.type = "button"; remove.dataset.removeDeliverable = ""; row.appendChild(remove);
    $("[data-deliverables]").appendChild(row); return row;
  }
  function renderDraft() {
    var draft = state.draft;
    ["name", "goal", "inputs", "cadence", "timezone", "time_of_day"].forEach(function (name) { field(name).value = draft[name] || (name === "time_of_day" ? "09:00" : ""); });
    webPolicies.forEach(function (policy) {
      var access = draft[policy.key] || (policy.key === "web_search" ? draft.web_access : null) || { mode: "off", domains: [] };
      var selectedMode = legacyWebDraft() ? "" : access.mode || "off";
      draftForm.querySelectorAll('[name="' + policy.key + '_mode"]').forEach(function (input) { input.checked = input.value === selectedMode; });
      $("[data-legacy-" + policy.prefix + "]").hidden = !legacyWebDraft();
      text("[data-legacy-" + policy.prefix + "]", ((state.public_research_release || {}).legacy ? "Previous approval" : "Previous settings") + " — choose a level");
      field(policy.key + "_domains").value = (access.domains || []).join("\n");
    });
    limitKeys.forEach(function (key) { field(key).value = String((draft.limits[key] || 0) / 1000000); });
    var capabilities = $("[data-capabilities]"); capabilities.replaceChildren();
    function toolRow(capability, unavailable) {
      var name = capability.name, title = capability.title || toolTitle(name), enabled = (draft.tools || []).includes(name);
      var row = node("div", "workspace-permission-row"), feature = node("div", "workspace-permission-feature"), choices = node("div", "workspace-permission-options");
      row.dataset.permissionRow = name;
      feature.append(node("strong", "", title), node("small", "", unavailable ? "Unavailable — turn off to remove" : capability.description || ""));
      choices.setAttribute("role", "radiogroup"); choices.setAttribute("aria-label", title);
      [["off", "Off"], ["allow", "Allow"]].forEach(function (choice) {
        var label = node("label", "workspace-permission-option"), input = node("input");
        input.type = "radio"; input.name = "tool-" + name; input.value = choice[0]; input.dataset.toolPermission = name;
        input.checked = choice[0] === (enabled ? "allow" : "off");
        if (unavailable && choice[0] === "allow") { input.dataset.unavailableOption = ""; input.disabled = true; }
        label.append(input, node("span", "", choice[1])); choices.appendChild(label);
      });
      row.append(feature, choices); capabilities.appendChild(row);
    }
    (state.capabilities || []).filter(function (capability) { return !isWebTool(capability.name) && !dedicatedPermission(capability.name); }).forEach(function (capability) { toolRow(capability, false); });
    (draft.tools || []).filter(function (name) { return !isWebTool(name) && !dedicatedPermission(name) && !(state.capabilities || []).some(function (cap) { return cap.name === name; }); }).forEach(function (name) { toolRow({ name: name }, true); });
    $("[data-other-capabilities]").hidden = !capabilities.children.length;
    $("[data-deliverables]").replaceChildren(); (draft.deliverables || []).forEach(addDeliverable);
    document.querySelector(".page-header h1").textContent = draft.name || "New agent";
    document.title = (draft.name || "New agent") + " - Habitat";
    syncToolControls();
    $("[data-time-field]").hidden = draft.cadence !== "daily";
  }
  function renderMessages(messages) {
    if (!Array.isArray(messages)) return;
    managementMessages = messages;
    var transcript = $("[data-transcript]"), list = $("[data-management-messages]");
    var atBottom = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 70;
    list.replaceChildren();
    messages.forEach(function (message) {
      if (!["assistant", "user"].includes(message.role) || !message.text) return;
      var item = node("li", "workspace-message " + (message.role === "user" ? "from-owner" : "from-assistant"));
      item.append(node("strong", "", message.role === "user" ? "You" : message.kind === "recovery" ? "Habitat status" : "Habitat"), node("div", "", message.text)); list.appendChild(item);
    });
    if (!list.children.length) { var welcome = node("li", "workspace-welcome"); welcome.append(node("h3", "", "What would you like to accomplish?"), node("p", "", "I can help shape the goal, deliverables, schedule, and spending limits. You can edit every setting yourself, too.")); list.appendChild(welcome); }
    if (atBottom) transcript.scrollTop = transcript.scrollHeight;
  }
  function blockerSection(reason) {
    if (/credit|fund|payment|setup/.test(reason)) return "funding";
    if (/budget|limit/.test(reason)) return "limits";
    if (/tool|domain|capability|grant|network/.test(reason)) return "tools";
    if (/schedule/.test(reason)) return "schedule";
    return "goal";
  }
  function renderExecution() {
    var execution = state.execution || {}, readiness = execution.readiness || {}, run = execution.run, schedule = execution.schedule || {};
    var dirty = localDirty || state.dirty || !state.published;
    var setup = scopedUsage(readiness.setup), balance = Number(readiness.balance_micro_usd || 0);
    text("[data-credit-before-setup]", money(readiness.credit_before_setup_micro_usd == null ? balance : readiness.credit_before_setup_micro_usd));
    text("[data-setup-pending]", setup ? money(setup.pending_micro_usd) : "Unavailable");
    text("[data-setup-paid]", setup ? money(setup.charged_micro_usd) : "Unavailable");
    text("[data-setup-held]", setup ? money(setup.held_micro_usd) : "");
    $("[data-setup-held-row]").hidden = !setup || !setup.held_micro_usd;
    text("[data-credit-balance]", money(Math.max(0, balance)));
    text("[data-setup-shortfall]", balance < 0 ? "Add " + money(-balance) + " in service credit to cover existing costs." : "");
    $("[data-setup-shortfall]").hidden = balance >= 0;
    text("[data-setup-status]", setup && setup.unknown ? "Some setup usage is still being confirmed." : setup && setup.busy ? "Setup is still in progress." : "");
    $("[data-setup-status]").hidden = !setup || !(setup.unknown || setup.busy);
    var required = readiness.required_micro_usd != null ? "The next work step needs up to " + money(readiness.required_micro_usd) + "." : "";
    if (required && setup && (setup.pending_micro_usd || setup.held_micro_usd) && readiness.activation_required_micro_usd != null) required += " Including setup and reserved setup credit, activation needs up to " + money(readiness.activation_required_micro_usd) + " in service credit.";
    text("[data-credit-required]", required);
    var blockers = $("[data-readiness-blockers]"); blockers.replaceChildren();
    (readiness.blockers || []).forEach(function (blocker) {
      var item = node("li", "", blocker.message || String(blocker.reason).replace(/_/g, " ")); var section = blockerSection(blocker.reason || "");
      if (section !== "funding") { var action = node("button", "ghost", section === "limits" ? "Review limits" : section === "tools" ? "Review permissions" : "Review settings"); action.type = "button"; action.dataset.section = section; item.appendChild(action); }
      blockers.appendChild(item);
    });
    text("[data-ready-message]", readiness.ready && !dirty ? "Ready to start work." : dirty ? "Review and apply your settings before starting work." : "Resolve the items above before starting or continuing work.");
    var lifecycle = state.lifecycle;
    $("[data-lifecycle-controls]").hidden = !state.instance_id || !lifecycle || lifecycle === "archived";
    text("[data-lifecycle-status]", lifecycle ? "Agent: " + lifecycle : "");
    var lifecycleButton = $('[data-command="lifecycle"]'); lifecycleButton.hidden = !lifecycle || lifecycle === "archived";
    lifecycleButton.textContent = lifecycle === "paused" ? "Resume agent" : lifecycle === "draft" ? "Activate agent" : "Pause agent";
    var order = readiness.funding_order_id;
    var payment = $("[data-continue-payment]"); payment.hidden = !order;
    if (order) payment.href = "/commerce/orders/" + encodeURIComponent(order);
    $("[data-fund-controls]").hidden = !!order;
    text("[data-funding-hint]", state.instance_id ? (order ? "Finish or check your existing payment before adding more funds." : "") : "Apply your settings to create the agent, then add funds here.");
    text("[data-schedule-status]", schedule.enabled ? "Enabled" : "Paused");
    text("[data-schedule-detail]", schedule.enabled ? (schedule.next_due ? "Next run: " + schedule.next_due : "The schedule is enabled.") : (state.draft.cadence === "manual" ? "This agent runs when you start it." : "Enable the schedule after applying settings and resolving readiness checks."));
    var scheduleButton = $('[data-command="schedule"]'); scheduleButton.textContent = schedule.enabled ? "Pause schedule" : "Enable schedule"; scheduleButton.hidden = state.draft.cadence === "manual" && !schedule.enabled;
    text("[data-run-status]", run ? statusLabels[run.status] || run.status : "Not started");
    text("[data-run-objective]", run ? run.objective : "");
    var researchRetry = !!(run && run.research_restart_required);
    var reason = researchRetry ? "public_research_failed" : run && run.local_read_recovery_available ? "local_read_recovery" : run && run.reason;
    var reasonMessages = {
      credit_insufficient: "Add service credit in Funding above, then continue this work.",
      local_read_recovery: "A saved-source read was interrupted. Continue work to recover this local read and use the research already saved.",
      public_research_failed: "Web research could not finish. Start a new run to try again; this run’s history and charges are kept.",
      platform_spend_ceiling: "The server’s API spending limit is reached. An operator must increase that limit before work can continue. Your research and drafts are saved.",
      no_progress: "Work stopped because the assistant was repeating actions without adding new evidence or output. Saved findings and results are preserved. Guide this run with the missing information or a revised direction before continuing.",
      sensitive_or_invalid_input: "Work stopped because the next model request contained content that could not be safely shared. Your results and action log are preserved.",
      invalid_decision: "The assistant could not produce a valid reply. Your completed work is saved. Continue work to retry."
    };
    text("[data-run-reason]", Object.prototype.hasOwnProperty.call(reasonMessages, reason) ? reasonMessages[reason] : String(reason || "").replace(/_/g, " "));
    $("[data-run-reason]").hidden = !reason;
    var research = run && run.public_research;
    var completedResearch = research && research.status === "completed" &&
      [research.successful_searches, research.successful_page_reads, research.unavailable_page_reads].every(function (count) { return Number.isSafeInteger(count) && count >= 0; });
    text("[data-run-research]", completedResearch ? "Web research: " + research.successful_searches + " search" + (research.successful_searches === 1 ? "" : "es") + " completed · " + research.successful_page_reads + " page" + (research.successful_page_reads === 1 ? "" : "s") + " read · " + research.unavailable_page_reads + " page" + (research.unavailable_page_reads === 1 ? "" : "s") + " unavailable." : "");
    $("[data-run-research]").hidden = !completedResearch;
    var plan = $("[data-run-plan]"); plan.replaceChildren();
    (run && run.plan || []).forEach(function (step) { var row = node("li"), heading = node("div"); heading.append(node("strong", "", step.title), node("small", "", String(step.state || "").replace(/_/g, " "))); row.appendChild(heading); if (step.summary) row.appendChild(node("p", "", step.summary)); plan.appendChild(row); });
    $("[data-plan-empty]").hidden = !!plan.children.length;
    var active = run && !terminal.includes(run.status);
    $('[data-command="start"]').hidden = !!active;
    $('[data-command="start"]').textContent = run ? "Start another run" : "Start work";
    $('[data-command="resume"]').hidden = !active || researchRetry || !(run.can_resume || run.can_advance || ["queued", "blocked", "paused"].includes(run.status));
    $('[data-command="resume"]').textContent = run && run.status === "paused" ? "Resume work" : "Continue work";
    $('[data-command="pause"]').hidden = !active || (run.can_pause === false || run.status === "paused");
    $('[data-command="cancel"]').hidden = !active || run.can_cancel === false;
    text("[data-run-start-hint]", active && (dirty || run.settings_changed || researchRetry) ? "" : dirty ? "Apply your current settings before starting work." : !readiness.ready ? "Review Funding and readiness above to prepare this agent." : "");
    var question = run && run.question;
    $("[data-run-question]").hidden = !question;
    text("[data-question-text]", question && (question.question || question.text || question.prompt));
    var options = $("[data-question-options]"); options.replaceChildren();
    (question && question.options || []).forEach(function (value) { var label = typeof value === "string" ? value : value.label || value.text || ""; if (!label) return; var option = node("button", "secondary", label); option.type = "button"; option.dataset.questionOption = label; options.appendChild(option); });
    $("[data-run-guide]").hidden = !active;
    runForm.querySelector('label').textContent = question ? "Answer the agent’s question" : "Message to the worker";
    if (!runInput.value.trim()) runMessageTarget = run ? { run_id: run.id, question_id: question && question.id } : null;
    var targetChanged = runMessageTarget && (runMessageTarget.run_id !== (run && run.id) || (runMessageTarget.question_id || null) !== (question && question.id || null));
    text("[data-run-message-hint]", targetChanged ? "The run or question changed while you were typing. Clear this message to answer the current question." : "This message goes to the current run. Use the assistant to change agent settings.");
    runForm.querySelector('button[type="submit"]').disabled = !!targetChanged || busy;
    var runMessages = $("[data-run-messages]"); runMessages.replaceChildren();
    (execution.messages || []).forEach(function (message) { if (!message.text) return; var item = node("li", "workspace-message"); item.append(node("strong", "", message.role === "user" ? "You" : "Worker"), node("div", "", message.text)); runMessages.appendChild(item); });
    var artifacts = $("[data-run-artifacts]");
    if (renderedResultRunId !== (run && run.id)) { artifacts.replaceChildren(); activityContainer().replaceChildren(); renderedResultRunId = run && run.id; }
    var openArtifactIds = new Set(Array.from(artifacts.querySelectorAll("details[open]")).map(function (el) { return el.dataset.artifactId; }));
    artifacts.replaceChildren();
    (run && run.artifacts || []).forEach(function (artifact, index) {
      var details = node("details", "workspace-artifact"), content = node("div", "workspace-artifact-content");
      details.dataset.artifactId = artifact.id || artifact.ref || artifact.name || String(index); details.open = openArtifactIds.has(details.dataset.artifactId);
      var body = artifact.content || artifact.text || artifact.body || "";
      if (window.HabitatMarkdown) content.append(window.HabitatMarkdown.render(body)); else content.textContent = body;
      details.append(node("summary", "", artifact.title || artifact.name || "Result"), content); artifacts.appendChild(details);
    });
    if (!artifacts.children.length) artifacts.appendChild(node("p", "muted", "Completed results and saved drafts will appear here."));
    renderActivity(run);
  }
  function activityContainer() {
    var container = $("[data-run-activity]");
    if (!container) { container = node("div"); container.dataset.runActivity = ""; $("[data-run-artifacts]").insertAdjacentElement("afterend", container); }
    return container;
  }
  function activityLink(path, runId, label) {
    // These routes come from the owner-scoped backend projection, never Markdown.
    var expected = "/audit/jobs/" + encodeURIComponent("runtime:" + runId);
    if (typeof path !== "string" || (path !== expected && !(path.startsWith(expected + "#step-") && /^[A-Za-z0-9_-]+$/.test(path.slice(expected.length + 6))))) return null;
    var link = node("a", "", label); link.href = path; return link;
  }
  function recordedAmount(summary, usage) {
    if (!summary || !Number.isSafeInteger(summary.settled_micro_usd)) return null;
    var recorded = (summary.components || []).some(function (component) { return ["recorded", "bundled"].includes(component.coverage) && component.amount_micro_usd != null; });
    return recorded || (usage && Number.isSafeInteger(usage.cost_micro_usd)) ? summary.settled_micro_usd : null;
  }
  function activityDate(value) {
    var date = new Date(value); return Number.isNaN(date.getTime()) ? "Time unavailable" : date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "UTC" }) + " UTC";
  }
  function renderActivity(run) {
    var container = activityContainer(), previous = container.querySelector("details"), open = !!(previous && previous.open);
    var log = run && run.activity_log;
    container.replaceChildren();
    if (!run) return;
    if (!log || log.schema_version !== 1 || log.run_id !== run.id || !Array.isArray(log.steps)) { container.append(node("p", "field-hint workspace-activity-unavailable", "Actions and costs are unavailable for this run.")); return; }
    var details = node("details", "workspace-activity"), summary = log.summary || {}, totals = log.totals || {};
    details.open = open; details.dataset.runId = run.id;
    var measuredZero = log.steps.some(function (step) { return step.usage && Number.isSafeInteger(step.usage.cost_micro_usd); });
    var heading = node("summary"), amount = recordedAmount(summary, measuredZero ? { cost_micro_usd: 0 } : null), recorded = amount == null ? "Not recorded" : money(amount);
    heading.append(node("span", "", "Actions and costs"), node("span", "workspace-activity-summary", recorded + " recorded · this run")); details.append(heading);
    var body = node("div", "workspace-activity-body"), metrics = node("dl", "workspace-activity-metrics");
    function metric(label, value) { var entry = node("div"); entry.append(node("dt", "", label), node("dd", "", value)); metrics.append(entry); }
    metric("Recorded charge · this run", recorded);
    if (summary.estimated_micro_usd > 0) metric("Runtime estimates", money(summary.estimated_micro_usd));
    if (summary.held_micro_usd > 0) metric("Reserved · not charged", money(summary.held_micro_usd));
    metric("Model decisions", String(totals.model_decisions == null ? "Unavailable" : totals.model_decisions));
    metric("Tool actions", String(totals.tool_calls == null ? "Unavailable" : totals.tool_calls));
    metric("Tokens · input / output", (totals.input_tokens == null ? "—" : Number(totals.input_tokens).toLocaleString()) + " / " + (totals.output_tokens == null ? "—" : Number(totals.output_tokens).toLocaleString()));
    metric("Web searches", String(totals.web_search_calls == null ? "Unavailable" : totals.web_search_calls));
    body.append(metrics, node("p", "field-hint", "This run only; setup and earlier runs are separate. " + (summary.coverage_note || "Only recorded charges are shown. Unmetered actions are not assumed free.")));
    var actions = node("div", "workspace-actions workspace-activity-actions"), download = node("button", "secondary", "Download log JSON"); download.type = "button";
    download.addEventListener("click", function () {
      var url = URL.createObjectURL(new Blob([JSON.stringify(log, null, 2) + "\n"], { type: "application/json" })), anchor = node("a");
      anchor.href = url; anchor.download = "habitat-work-" + String(log.run_id).replace(/[^A-Za-z0-9_-]/g, "_") + "-actions.json"; document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    });
    actions.append(download); var audit = activityLink(log.audit_url, run.id, "Open full audit"); if (audit) actions.append(audit); body.append(actions);
    var tableWrap = node("div", "workspace-activity-table"), table = node("table"), caption = node("caption", "", "Actions in execution order"), head = node("thead"), headings = node("tr"), rows = node("tbody");
    tableWrap.tabIndex = 0; tableWrap.setAttribute("role", "region"); tableWrap.setAttribute("aria-label", "Actions and costs table");
    ["#", "Action", "Time (UTC)", "State", "Recorded cost"].forEach(function (label) { var th = node("th", "", label); th.scope = "col"; headings.append(th); }); head.append(headings); table.append(caption, head, rows);
    log.steps.forEach(function (step) {
      var row = node("tr"), action = node("td"), title = activityLink(step.evidence_url, run.id, step.label || step.tool_name || step.kind || "Action"), usage = step.usage, cost = step.cost_summary, recordedCost = recordedAmount(cost, usage);
      if (title && step.details_url) { title.dataset.actionDetails = step.details_url; title.setAttribute("aria-haspopup", "dialog"); }
      row.dataset.stepId = step.id; action.append(title || node("span", "", step.label || step.tool_name || step.kind || "Action"));
      if (step.model) action.append(node("small", "", step.model));
      if (usage && (usage.input_tokens || usage.output_tokens)) action.append(node("small", "", Number(usage.input_tokens || 0).toLocaleString() + " in · " + Number(usage.output_tokens || 0).toLocaleString() + " out"));
      if (usage && usage.web_search_calls) action.append(node("small", "", usage.web_search_calls + " web search" + (usage.web_search_calls === 1 ? "" : "es")));
      var status = node("td", "", String(step.state || "Unknown").replace(/_/g, " "));
      if (step.error) status.append(node("small", "workspace-action-error", String(step.error).replace(/_/g, " ")));
      var charge = node("td", "workspace-activity-charge", recordedCost == null ? "Not recorded" : money(recordedCost));
      if (cost && cost.estimated_micro_usd > 0) charge.append(node("small", "", money(cost.estimated_micro_usd) + " estimated"));
      if (cost && cost.held_micro_usd > 0) charge.append(node("small", "", money(cost.held_micro_usd) + " reserved"));
      row.append(node("td", "", String(step.sequence)), action, node("td", "workspace-activity-time", activityDate(step.created_at)), status, charge); rows.append(row);
    });
    if (log.steps.length) { tableWrap.append(table); body.append(tableWrap); } else body.append(node("p", "field-hint", "No actions have been recorded for this run."));
    details.append(body); container.append(details);
  }
  function renderRunSettings() {
    var run = (state.execution || {}).run, active = run && !terminal.includes(run.status);
    var unapplied = localDirty || state.dirty || !state.published;
    var changed = !!(active && (unapplied || run.settings_changed));
    var researchRetry = !!(active && run.research_restart_required);
    $("[data-run-settings]").hidden = !changed && !researchRetry;
    var retryMessage = "Retry research starts a new run with your saved settings. This run’s history and charges are kept; new research can incur additional charges.";
    text("[data-run-settings-message]", researchRetry ? (unapplied ? "Save and apply your draft before retrying. " : "") + retryMessage : !changed ? "" : unapplied ? "Save and apply your draft to prepare updated settings. This run continues with its original settings." : "The updated settings are saved. This run still uses its original settings; restart it to use the changes.");
    var tools = run && Array.isArray(run.allowed_tools) ? run.allowed_tools.filter(function (name) { return name !== "artifact.read"; }) : null;
    text("[data-run-tools]", changed && tools ? "Current run tools: " + (tools.length ? tools.map(toolTitle).join(", ") : "provided context only") + "." : "");
    var restart = $('[data-command="restart"]');
    restart.textContent = researchRetry ? "Retry research" : "Restart with updated settings";
    restart.hidden = !(changed || researchRetry) || !["waiting_owner", "paused", "blocked"].includes(run.status);
    restart.disabled = busy || !!conflict || unapplied || !run || !run.can_restart;
    var blockers = $("[data-restart-blockers]"); blockers.replaceChildren();
    if (!restart.hidden) (run.restart_blockers || []).forEach(function (blocker) { blockers.appendChild(node("li", "", blocker.message || String(blocker.reason).replace(/_/g, " "))); });
  }
  function updateControls() {
    var execution = state.execution || {}, readiness = execution.readiness || {}, run = execution.run, schedule = execution.schedule || {};
    var unapplied = localDirty || state.dirty || !state.published;
    root.querySelectorAll("input,textarea,select,button").forEach(function (el) { el.disabled = busy || el.hasAttribute("data-unavailable-capability") || el.hasAttribute("data-unavailable-option"); });
    $('[data-command="start"]').disabled = busy || !!conflict || !!state.external_conflict || unapplied || !readiness.ready || execution.can_start === false;
    $('[data-command="resume"]').disabled = busy || !!conflict || !run || run.research_restart_required || !(run.can_resume || run.can_advance);
    $('[data-command="schedule"]').disabled = busy || !!conflict || (!schedule.enabled && (unapplied || !readiness.ready));
    $('[data-command="fund"]').disabled = busy || !state.instance_id || !!conflict;
    $('[data-command="apply"]').disabled = busy || !!conflict || !!state.external_conflict || (!localDirty && !state.dirty && !!state.published && !state.inference_grant_missing && !(state.public_research_release || {}).approval_required);
    $("[data-save-draft]").disabled = busy || !!conflict || !localDirty;
    $("[data-add-deliverable]").disabled = busy || draftForm.querySelectorAll("[data-deliverable]").length >= 6;
    text("[data-draft-status]", localDirty ? "Unsaved changes" : state.dirty ? "Unapplied changes" : state.published ? "Settings applied" : "Draft");
    text("[data-save-status]", localDirty ? "You have unsaved edits." : state.dirty || !state.published ? "Draft saved. Review and apply the settings above." : state.inference_grant_missing ? "Apply settings to restore agent processing." : "Your settings are applied.");
    var targetChanged = runMessageTarget && (runMessageTarget.run_id !== (run && run.id) || (runMessageTarget.question_id || null) !== (run && run.question && run.question.id || null));
    runForm.querySelector('button[type="submit"]').disabled = busy || !!targetChanged;
    assistantForm.querySelector('button[type="submit"]').disabled = busy || !!conflict;
    draftForm.setAttribute("aria-busy", String(busy)); assistantForm.setAttribute("aria-busy", String(busy));
    renderRunSettings(); renderResearch();
  }
  function render(payload, replaceDraft) {
    var hadLocalDirty = localDirty, draftChanged = JSON.stringify(state.draft) !== JSON.stringify(payload.state.draft), catalogChanged = JSON.stringify(state.capabilities) !== JSON.stringify(payload.state.capabilities);
    state = payload.state;
    if (replaceDraft) { localDirty = false; if (!renderedDraft || draftChanged || catalogChanged || hadLocalDirty) renderDraft(); renderedDraft = true; }
    if (payload.messages) renderMessages(payload.messages);
    var usage = scopedUsage(payload.usage);
    text("[data-assistant-usage]", usage ? "Setup cost: " + money(usage.spent_micro_usd) + " for this agent." + (usage.unknown ? " Some setup usage is still being confirmed." : usage.busy ? " Setup is still in progress." : "") : "Setup cost unavailable for this agent.");
    $("[data-external-conflict]").hidden = !state.external_conflict;
    renderExecution(); updateControls();
    if (payload.focus_section) focusSection(payload.focus_section);
  }
  function setConflict(payload) { conflict = payload; $("[data-workspace-conflict]").hidden = false; updateControls(); }
  async function getLatest() { var response = await fetch(endpoint, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } }); if (!response.ok) throw new Error("Couldn’t refresh this workspace. Your saved work is unchanged."); return response.json(); }
  async function send(path, body) {
    // A failed network response retains the exact request ID and body for an idempotent retry.
    var fingerprint = JSON.stringify({ path: path, command: body.command, arguments: body.arguments, text: body.text });
    if (!deliveryAttempt || deliveryAttempt.fingerprint !== fingerprint) deliveryAttempt = { fingerprint: fingerprint, request_id: requestId(), body: body };
    var response = await fetch(endpoint + path, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRF-Token": root.dataset.csrf, Accept: "application/json" }, body: JSON.stringify(Object.assign({ request_id: deliveryAttempt.request_id }, deliveryAttempt.body)) });
    var payload = await response.json();
    if (!response.ok) {
      deliveryAttempt = null;
      if (response.status === 409) { try { setConflict(payload.state ? payload : await getLatest()); } catch (_) { setConflict({}); } }
      throw new Error(payload.message || payload.error || "This action could not be completed.");
    }
    deliveryAttempt = null; return payload;
  }
  async function command(name, args) { return send("/commands", { command: name, expected_version: state.version, arguments: args || {} }); }
  async function saveDraft() {
    if (!localDirty) return;
    if (legacyWebDraft() && webPolicies.some(function (policy) { return field(policy.key + "_mode").value === ""; }) && webPolicies.some(function (policy) { return field(policy.key + "_mode").value !== ""; })) {
      focusSection("tools"); throw new Error("Choose search and page access levels before saving these settings.");
    }
    var payload = await command("update_draft", { patch: serializeDraft() }); render(payload, true);
  }
  async function perform(work) {
    if (busy) return;
    busy = true; operationEpoch += 1; error(""); notice(""); updateControls();
    try { await work(); } catch (failure) { error(failure.message || "Couldn’t complete this action. Your edits are still here; try again."); }
    finally { busy = false; updateControls(); }
  }
  async function dispatch(name) {
    if (["apply", "start", "schedule", "fund"].includes(name) && localDirty && !draftForm.reportValidity()) return;
    await perform(async function () {
      if (["apply", "start", "schedule", "fund"].includes(name)) await saveDraft();
      var args = {}, execution = state.execution || {}, run = execution.run;
      if (name === "apply" && webPolicies.some(function (policy) { return field(policy.key + "_mode").value === ""; }) && (state.public_research_release || {}).approval_required) { focusSection("tools"); throw new Error("Choose search and page access levels before applying settings."); }
      if (name === "apply" && selectedWebAccess() && (state.public_research_release || {}).approval_required) {
        if (!approvedDisclosure || approvedDisclosure.version !== state.version) { focusSection("tools"); throw new Error("Review and approve web research for this goal before applying settings."); }
        args.approved_public_research_digest = approvedDisclosure.digest;
      }
      if (["pause", "resume", "cancel"].includes(name)) args.run_id = run.id;
      if (name === "resume") args.expected_run_version = run.version;
      if (name === "resume" && run.status === "queued") name = "advance";
      if (name === "restart") args = { run_id: run.id, expected_run_version: run.version };
      if (name === "lifecycle") args.action = state.lifecycle === "paused" ? "resume" : state.lifecycle === "draft" ? "activate" : "pause";
      if (name === "schedule") args.enabled = !(execution.schedule || {}).enabled;
      if (name === "fund") args.amount_minor = Number(document.getElementById("workspace-topup").value);
      var payload = await command(name, args); render(payload, name === "reload" || !localDirty);
      if (payload.redirect_url && name === "fund") { var destination = new URL(payload.redirect_url, window.location.origin); if (destination.origin !== window.location.origin) throw new Error("Checkout returned an unexpected address."); window.location.assign(destination.href); return; }
      var recoveredBlocked = name === "resume" && run && run.local_read_recovery_available &&
        payload.state.execution.run && payload.state.execution.run.status === "blocked";
      notice(recoveredBlocked ? "The saved-source read is recovered. Review the blocker below before continuing." : { reload: "Loaded saved agent settings.", apply: "Settings applied. Review funding and readiness below.", pause: "Work paused.", resume: "Work continued.", advance: "Work continued.", restart: "Created a new run with your saved settings.", lifecycle: "Agent status updated.", cancel: "Work cancelled.", schedule: args.enabled ? "Schedule enabled." : "Schedule paused." }[name] || "");
      if (name === "apply") focusSection("funding");
    });
  }
  draftForm.addEventListener("input", function (event) { if (event.target.hasAttribute("data-research-approve")) return; localDirty = true; updateControls(); syncToolControls(); $("[data-time-field]").hidden = field("cadence").value !== "daily"; });
  draftForm.addEventListener("change", function (event) {
    if (event.target.hasAttribute("data-research-approve")) {
      var release = state.public_research_release || {};
      approvedDisclosure = event.target.checked && !localDirty && release.available && release.draft_digest ? { version: state.version, digest: release.draft_digest } : null;
      updateControls(); return;
    }
    localDirty = true; updateControls(); syncToolControls(); $("[data-time-field]").hidden = field("cadence").value !== "daily";
  });
  draftForm.addEventListener("submit", function (event) { event.preventDefault(); if (!draftForm.reportValidity()) return; perform(async function () { await saveDraft(); notice("Draft saved. Apply settings when you’re ready."); }); });
  assistantForm.addEventListener("submit", function (event) {
    event.preventDefault(); var message = assistantInput.value.trim(); if (!message || conflict || localDirty && !draftForm.reportValidity()) return;
    perform(async function () {
      await saveDraft(); text("[data-assistant-status]", "Updating your workspace…");
      try { var payload = await send("/messages", { text: message, expected_version: state.version }); render(payload, true); assistantInput.value = ""; $("[data-transcript]").scrollTop = $("[data-transcript]").scrollHeight; }
      finally { text("[data-assistant-status]", ""); }
    });
  });
  assistantInput.addEventListener("keydown", function (event) { if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing) { event.preventDefault(); assistantForm.requestSubmit(); } });
  runInput.addEventListener("input", function () { if (!runInput.value.trim()) { var run = (state.execution || {}).run; runMessageTarget = run ? { run_id: run.id, question_id: run.question && run.question.id } : null; } updateControls(); });
  runForm.addEventListener("submit", function (event) {
    event.preventDefault(); var message = runInput.value.trim(); if (!message || !runMessageTarget) return;
    perform(async function () { var args = { run_id: runMessageTarget.run_id, text: message }; if (runMessageTarget.question_id) args.question_id = runMessageTarget.question_id; var payload = await command("message_run", args); runInput.value = ""; render(payload, !localDirty); notice("Message sent to this run."); });
  });
  root.addEventListener("click", function (event) {
    var target = event.target.closest("button"); if (!target || target.disabled) return;
    if (target.dataset.command) dispatch(target.dataset.command);
    if (target.dataset.section) focusSection(target.dataset.section);
    if (target.hasAttribute("data-add-deliverable")) { var row = addDeliverable({}); localDirty = true; updateControls(); row.querySelector("input").focus(); }
    if (target.hasAttribute("data-remove-deliverable")) { target.closest("[data-deliverable]").remove(); localDirty = true; updateControls(); }
    if (target.hasAttribute("data-refresh")) refresh(true);
    if (target.hasAttribute("data-question-option")) { var run = state.execution.run; runMessageTarget = { run_id: run.id, question_id: run.question.id }; runInput.value = target.dataset.questionOption; $("[data-run-guide]").open = true; updateControls(); runInput.focus(); }
    if (target.hasAttribute("data-conflict-load")) perform(async function () { var latest = await getLatest(); conflict = null; $("[data-workspace-conflict]").hidden = true; render(latest, true); notice("Loaded the latest settings."); });
    if (target.hasAttribute("data-conflict-reapply")) perform(async function () { var draft = serializeDraft(), latest = await getLatest(); state = latest.state; var payload = await command("update_draft", { patch: draft }); conflict = null; $("[data-workspace-conflict]").hidden = true; render(payload, true); notice("Your edits have been saved on the latest workspace. Review and apply them when ready."); });
  });
  async function refresh(explicit) {
    if (busy || document.hidden && !explicit) return;
    var epoch = operationEpoch;
    try { var payload = await getLatest(); if (busy || operationEpoch !== epoch || payload.state.version < state.version) return; if (localDirty && payload.state.version !== state.version) setConflict(payload); else if (!conflict) render(payload, !localDirty); text("[data-poll-status]", ""); }
    catch (_) { text("[data-poll-status]", "Couldn’t refresh progress. Showing the last saved state; retrying shortly."); }
  }
  var toggle = document.getElementById("workspace-assistant-toggle"), panel = document.getElementById("workspace-assistant");
  function collapse(value) { panel.hidden = value; $(".workspace-layout").classList.toggle("assistant-collapsed", value); toggle.setAttribute("aria-expanded", String(!value)); toggle.textContent = value ? "Show assistant" : "Hide assistant"; try { localStorage.setItem("habitat.workspace.assistant.collapsed", String(value)); } catch (_) {} }
  toggle.addEventListener("click", function () { collapse(!panel.hidden); });
  try { collapse(localStorage.getItem("habitat.workspace.assistant.collapsed") === "true"); } catch (_) {}
  window.addEventListener("beforeunload", function (event) { if (localDirty) { event.preventDefault(); event.returnValue = ""; } });
  render(initial, true);
  pollTimer = window.setInterval(function () { refresh(false); }, 5000);
  window.addEventListener("pagehide", function () { clearInterval(pollTimer); });
  window.addEventListener("pageshow", function (event) { if (event.persisted) { refresh(true); clearInterval(pollTimer); pollTimer = window.setInterval(function () { refresh(false); }, 5000); } });

  // Optional browser-agent adapter. These tools reuse the same versioned commands as the UI.
  // Approval, spending, checkout and execution remain explicit owner controls.
  var modelContext = navigator.modelContext || document.modelContext;
  if (modelContext && typeof modelContext.registerTool === "function") {
    function toolResult(value) { return { content: [{ type: "text", text: JSON.stringify(value) }] }; }
    var tools = [
      { name: "habitat_read_workspace", description: "Read the visible agent configuration, readiness and progress. Includes any unsaved owner edits.", inputSchema: { type: "object", properties: {}, additionalProperties: false }, annotations: { readOnlyHint: true }, execute: async function () { return toolResult({ state: state, visible_draft: serializeDraft(), unsaved_owner_edits: localDirty }); } },
      { name: "habitat_update_draft", description: "Update the visible agent draft. Does not approve tools, limits, payment, scheduling or execution. The owner reviews and applies settings.", inputSchema: { type: "object", properties: { expected_version: { type: "integer" }, patch: { type: "object" } }, required: ["expected_version", "patch"], additionalProperties: false }, execute: async function (args) {
        if (busy || localDirty || conflict || args.expected_version !== state.version) return toolResult({ error: "workspace_changed", message: "Owner edits or another operation are in progress. Read the workspace again before changing it." });
        busy = true; operationEpoch += 1; updateControls();
        try { var payload = await command("update_draft", { patch: args.patch }); render(payload, true); notice("The assistant updated your draft. Review and apply the settings when ready."); return toolResult({ state: state }); }
        catch (failure) { error(failure.message); return toolResult({ error: "update_failed", message: failure.message }); }
        finally { busy = false; updateControls(); }
      } },
      { name: "habitat_show_section", description: "Bring a section of the agent workspace into view.", inputSchema: { type: "object", properties: { section: { type: "string", enum: ["goal", "deliverables", "tools", "schedule", "limits", "funding", "progress", "results"] } }, required: ["section"], additionalProperties: false }, annotations: { readOnlyHint: true }, execute: async function (args) { focusSection(args.section); return toolResult({ section: args.section }); } }
    ];
    tools.forEach(function (tool) { try { Promise.resolve(modelContext.registerTool(tool)).catch(function () {}); } catch (_) {} });
  }
}());
