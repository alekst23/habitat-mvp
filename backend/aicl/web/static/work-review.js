(function () {
  "use strict";
  var root = document.getElementById("work-review");
  if (!root) return;
  var $ = function (selector) { return root.querySelector(selector); };
  var form = $("#review-filters"), list = $("[data-review-list]"), reader = $("[data-review-reader]");
  var params = new URLSearchParams(location.search), rows = [], nextCursor = null, detail = null, tab = "report", outputId = params.get("output") || "";
  var selected = params.get("run") || "", listEpoch = 0, detailEpoch = 0, countsEpoch = 0, markRevision = 0, markReceipts = new Map(), searchTimer, marking = false, loadingList = false;
  ["q", "workspace_id", "view", "from_date", "to_date"].forEach(function (name) { if (params.has(name) && name !== "workspace_id") form.elements.namedItem(name).value = params.get(name); });
  if (!["all", "unseen", "needs_attention", "saved"].includes(form.elements.namedItem("view").value)) form.elements.namedItem("view").value = "all";
  function node(tag, className, text) { var el = document.createElement(tag); if (className) el.className = className; if (text != null) el.textContent = String(text); return el; }
  function button(text, action, className) { var el = node("button", className || "secondary small", text); el.type = "button"; el.addEventListener("click", action); return el; }
  function money(value) { return Number.isSafeInteger(value) ? (value < 0 ? "-$" : "$") + (Math.abs(value) / 1e6).toFixed(6).replace(/0{1,4}$/, "") : "Not recorded"; }
  function date(value, long) { var d = new Date(value); return isNaN(d.getTime()) ? "Date unavailable" : new Intl.DateTimeFormat(undefined, long ? { dateStyle: "medium", timeStyle: "short" } : { month: "short", day: "numeric", year: "numeric" }).format(d); }
  function error(message) { $("[data-review-error]").hidden = !message; $("[data-review-error]").textContent = message || ""; }
  function empty(title, text) { var box = node("div", "review-empty"); box.append(node("h2", "", title), node("p", "", text)); return box; }
  function endpoint(id) { return "/api/work-review/" + encodeURIComponent(id); }
  async function request(url, options) {
    var response = await fetch(url, Object.assign({ credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } }, options || {}));
    var data; try { data = await response.json(); } catch (_) { throw new Error("Could not load work. Refresh to try again."); }
    if (!response.ok) throw new Error(response.status === 401 ? "Your session ended. Sign in again to review your work." : data.message || "Could not load work. Refresh to try again.");
    return data;
  }
  function filters() {
    var result = new URLSearchParams();
    ["q", "workspace_id", "view", "from_date", "to_date"].forEach(function (key) { var value = form.elements.namedItem(key).value; if (value && !(key === "view" && value === "all")) result.set(key, value); });
    return result;
  }
  function updateURL() { var query = filters(); if (selected) query.set("run", selected); if (outputId) query.set("output", outputId); history.replaceState(null, "", "/work" + (query.size ? "?" + query.toString() : "")); }
  function localLink(path, label, kind, run) {
    if (typeof path !== "string") return null;
    var allowed = kind === "workspace" ? "/agent-workspaces/" + encodeURIComponent(run.workspace_id) : "/audit/jobs/" + encodeURIComponent("runtime:" + run.run_id);
    if (path !== allowed && !path.startsWith(allowed + "#")) return null;
    var link = node("a", "", label); link.href = path; return link;
  }
  function stateBadge(item) {
    var names = { completed: "Completed", blocked: "Blocked", waiting_owner: "Needs your input", paused: "Paused", failed: "Failed", cancelled: "Cancelled", queued: "Queued", running: "Working" };
    var partial = item.output_count > 0 && item.status !== "completed";
    return node("span", "status-badge " + (item.status === "completed" ? "active" : item.needs_attention ? "blocked" : "draft"), (partial ? "Saved draft · " : "") + (names[item.status] || item.status));
  }
  function renderCounts(counts) {
    counts = counts || {}; var count = counts.all || 0;
    $("[data-review-counts]").textContent = (counts.unseen || 0) + " unseen · " + (counts.needs_attention || 0) + " need attention · " + count + (count === 1 ? " run" : " runs");
  }
  function matchesMarkView(item) { var view = form.elements.namedItem("view").value; return (view !== "unseen" || !item.seen) && (view !== "saved" || item.saved); }
  function applyRecentMark(item, revision) {
    var receipt = markReceipts.get(item.run_id);
    // A list/detail request begun before a successful mark may return old flags.
    // Never apply an old seen receipt to a newer version of the work.
    if (receipt && receipt.revision > revision && item.version === receipt.result.version) Object.assign(item, receipt.result);
    return item;
  }
  async function refreshCounts() {
    var epoch = ++countsEpoch, query = filters(), key = query.toString(); query.set("limit", "1");
    var data = await request("/api/work-review?" + query);
    if (epoch === countsEpoch && key === filters().toString()) renderCounts(data.counts);
  }
  function renderList() {
    var pane = $(".review-list-pane"), scrollTop = pane.scrollTop;
    list.replaceChildren();
    rows.forEach(function (item) {
      var row = button("", function () { select(item.run_id, true); }, "review-row"); row.dataset.runId = item.run_id; row.setAttribute("aria-current", String(selected === item.run_id));
      var top = node("span", "review-row-top"), when = node("span", "", date(item.created_at));
      if (!item.seen) { var dot = node("span", "review-unseen"); dot.setAttribute("aria-label", "Unseen"); when.prepend(dot); }
      top.append(when, node("span", "", money(item.recorded_micro_usd)));
      row.append(top, node("strong", "", item.agent_name), node("span", "review-row-name", item.title || item.goal), stateBadge(item));
      if (item.saved) row.append(node("span", "review-row-name", "Saved"));
      list.append(row);
    });
    if (!rows.length) { var box = empty("No work in this view", "Try another filter, or open an agent to start work."); var agents = node("a", "button secondary small", "Open agents"); agents.href = "/workspace"; box.append(agents); list.append(box); }
    $("[data-review-more]").hidden = !nextCursor;
    $("[data-review-more]").disabled = loadingList;
    pane.scrollTop = scrollTop;
  }
  async function loadList(append) {
    var epoch = ++listEpoch, countEpoch = ++countsEpoch, revision = markRevision, query = filters(); query.set("limit", "20"); if (append && nextCursor) query.set("cursor", nextCursor);
    loadingList = true; $("[data-review-more]").disabled = true; error("");
    try {
      var data = await request("/api/work-review?" + query);
      if (epoch !== listEpoch) return;
      var known = new Set(append ? rows.map(function (r) { return r.run_id; }) : []);
      rows = (append ? rows : []).concat(data.items.map(function (r) { return applyRecentMark(r, revision); }).filter(function (r) { return !known.has(r.run_id) && matchesMarkView(r); })); nextCursor = data.next_cursor;
      var agent = $("#review-agent"), previous = agent.value; agent.replaceChildren(node("option", "", "All agents")); agent.firstChild.value = "";
      (data.agents || []).forEach(function (a) { var option = node("option", "", a.name); option.value = a.workspace_id; agent.append(option); }); agent.value = previous;
      if (countEpoch === countsEpoch && revision === markRevision) renderCounts(data.counts);
      $("[data-clear-filters]").hidden = filters().size === 0;
      renderList(); updateURL();
      if (!selected && rows.length) await select(rows[0].run_id, false);
      else if (!selected) { detail = null; reader.replaceChildren(empty("Your work, kept together", "Completed reports, partial drafts, and run history will appear here.")); reader.setAttribute("aria-busy", "false"); renderAssistant(); }
    } catch (e) { if (epoch === listEpoch) { error(e.message); reader.setAttribute("aria-busy", "false"); } }
    finally { if (epoch === listEpoch) { loadingList = false; $("[data-review-more]").disabled = false; } }
  }
  async function select(id, scroll) {
    var epoch = ++detailEpoch, revision = markRevision; selected = id; detail = null; outputId = id === params.get("run") ? outputId : ""; tab = "report";
    reader.replaceChildren(empty("Loading saved work…", "Reading the report and its recorded activity.")); reader.setAttribute("aria-busy", "true"); renderList(); renderAssistant(); updateURL();
    try {
      var value = await request(endpoint(id)); if (epoch !== detailEpoch) return;
      if (!value.item || value.item.run_id !== selected) throw new Error("The returned work does not match your selection.");
      applyRecentMark(value.item, revision);
      detail = value; renderReader(); renderAssistant();
      if (scroll && window.matchMedia("(max-width: 650px)").matches) reader.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) { if (epoch === detailEpoch) { reader.replaceChildren(empty("Could not open this work", e.message)); error(e.message); } }
    finally { if (epoch === detailEpoch) reader.setAttribute("aria-busy", "false"); }
  }
  function chosenOutput() { var outputs = detail.outputs || []; return outputs.find(function (o) { return o.id === outputId; }) || outputs.find(function (o) { return o.latest; }) || outputs[0]; }
  function renderReader() {
    if (!detail) return; var item = detail.item; reader.replaceChildren();
    var top = node("div", "review-reader-top"), actions = node("div", "review-reader-actions");
    var save = button(item.saved ? "Saved" : "Save", function () { mark({ saved: !item.saved }); }); save.setAttribute("aria-pressed", String(item.saved)); save.disabled = marking;
    var seen = button(item.seen ? "Mark unseen" : "Mark seen", function () { mark({ seen: !item.seen }); }); seen.disabled = marking;
    actions.append(save, seen); top.append(stateBadge(item), actions);
    reader.append(top, node("p", "kicker", item.agent_name + " · " + date(item.created_at, true)), node("h2", "review-reader-title", item.title || item.agent_name));
    if (item.goal) { var brief = node("details", "review-brief"); brief.append(node("summary", "", "Original brief"), node("p", "review-reader-objective", item.goal)); reader.append(brief); }
    var tabs = node("div", "review-tabs"); tabs.setAttribute("role", "tablist"); tabs.setAttribute("aria-label", "Work details");
    var content = node("div"); content.id = "review-detail-content"; content.setAttribute("role", "tabpanel");
    ["report", "sources", "activity", "cost"].forEach(function (name) {
      var b = button(name[0].toUpperCase() + name.slice(1), function () { tab = name; renderReader(); $("#review-tab-" + name).focus(); }, "review-tab");
      b.id = "review-tab-" + name; b.setAttribute("role", "tab"); b.setAttribute("aria-selected", String(tab === name)); b.setAttribute("aria-controls", content.id); b.tabIndex = tab === name ? 0 : -1;
      b.addEventListener("keydown", function (event) { var names = ["report", "sources", "activity", "cost"], index = names.indexOf(name); if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) { event.preventDefault(); tab = event.key === "Home" ? names[0] : event.key === "End" ? names[3] : names[(index + (event.key === "ArrowRight" ? 1 : 3)) % 4]; renderReader(); $("#review-tab-" + tab).focus(); } }); tabs.append(b);
    });
    content.setAttribute("aria-labelledby", "review-tab-" + tab);
    if (tab === "report") report(content); else if (tab === "sources") sources(content); else if (tab === "activity") activity(content); else costs(content);
    reader.append(tabs, content);
    var footer = node("div", "review-provenance"); footer.append(node("span", "", date(item.created_at, true) + " run"), node("span", "", money(item.recorded_micro_usd) + (item.recorded_micro_usd == null ? "" : " recorded")));
    var audit = localLink(detail.audit_url, "Full run history", "audit", item), workspace = localLink(item.workspace_url + "#workspace-progress", "Open agent workspace", "workspace", item);
    if (audit) footer.append(audit); if (workspace) footer.append(workspace); reader.append(footer); updateURL();
  }
  function report(container) {
    var item = detail.item, outputs = detail.outputs || [], output = chosenOutput();
    if (!output) { container.append(empty("No result saved yet", item.status === "completed" ? "This run completed without a saved report. Its activity and costs are still available." : "This run has no saved report. Review its activity, or open the agent workspace to continue.")); return; }
    outputId = output.id;
    var groups = Array.from(new Set(outputs.map(function (o) { return o.name; }))), versions = outputs.filter(function (o) { return o.name === output.name; });
    if (groups.length > 1 || versions.length > 1) {
      var selectors = node("div", "review-output-select");
      if (groups.length > 1) { var field = node("label", "", "Result"), selectOutput = node("select"); selectOutput.setAttribute("aria-label", "Result"); groups.forEach(function (name) { var option = node("option", "", name.replace(/_/g, " ")); option.value = name; option.selected = name === output.name; selectOutput.append(option); }); selectOutput.addEventListener("change", function () { var matching = outputs.filter(function (o) { return o.name === selectOutput.value; }); outputId = (matching.find(function (o) { return o.latest; }) || matching[0]).id; renderReader(); }); field.append(selectOutput); selectors.append(field); }
      if (versions.length > 1) { var versionField = node("label", "", "Version"), selectVersion = node("select"); selectVersion.setAttribute("aria-label", "Version"); versions.forEach(function (v, index) { var option = node("option", "", (v.latest ? "Latest · " : "Earlier · ") + date(v.created_at, true)); option.value = v.id; option.selected = v.id === output.id; selectVersion.append(option); }); selectVersion.addEventListener("change", function () { outputId = selectVersion.value; renderReader(); }); versionField.append(selectVersion); selectors.append(versionField); }
      container.append(selectors);
    }
    if (!output.latest) container.append(node("p", "notice info", "You are reading an earlier saved version. The latest result is available in the version menu."));
    if (output.state !== "completed" && output.state !== "delivered" && output.state !== "accepted") container.append(node("p", "notice info", "Saved draft. Reading or marking this seen does not approve it or continue the run."));
    var article = node("div", "review-article"), body = typeof output.content === "string" ? output.content : typeof output.body === "string" ? output.body : "";
    if (window.HabitatMarkdown) article.append(window.HabitatMarkdown.render(body)); else article.append(node("pre", "", body));
    container.append(article);
  }
  function sources(container) {
    container.append(node("p", "review-cost-note", "Saved source references for this run. Opening this tab makes no requests to those websites."));
    var entries = detail.sources || [];
    if (!entries.length) { container.append(empty("No separate source records", "Source links may be included in the report. The full run history retains its original evidence.")); return; }
    entries.forEach(function (source) {
      var row = node("div", "review-source"), title = String(source.title || source.url || "Source"), link = null;
      try {
        var url = new URL(source.url);
        if (url.protocol === "https:" && !url.username && !url.password && (!url.port || url.port === "443") && !/[\s\\]/.test(source.url) && url.hostname.includes(".") && !/^[\d.]+$/.test(url.hostname) && !/(^|\.)(localhost|local|internal|test|invalid)$/.test(url.hostname)) {
          link = node("a", "", title); link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer"; link.referrerPolicy = "no-referrer";
        }
      } catch (_) { /* Untrusted source metadata stays plain text. */ }
      row.append(link || node("strong", "", title));
      row.append(node("small", "", (source.kind === "search_result" ? "Search discovery" : "Saved page reference") + (source.unavailable ? " · Unavailable" : "") + " · " + date(source.recorded_at, true))); container.append(row);
    });
  }
  function recorded(summary, usage) {
    if (summary && Number.isSafeInteger(summary.settled_micro_usd) && (summary.settled_micro_usd > 0 || (summary.components || []).some(function (c) { return c.coverage === "recorded" && Number.isSafeInteger(c.amount_micro_usd); }))) return summary.settled_micro_usd;
    return usage && Number.isSafeInteger(usage.cost_micro_usd) ? usage.cost_micro_usd : null;
  }
  function metric(parent, label, value) { var group = node("div"); group.append(node("dt", "", label), node("dd", "", value == null ? "Unavailable" : value)); parent.append(group); }
  function logActions(container) {
    var log = detail.activity; if (!log || log.run_id !== selected) return;
    var actions = node("div", "review-log-actions");
    actions.append(button("Download action log", function () { var url = URL.createObjectURL(new Blob([JSON.stringify(log, null, 2) + "\n"], { type: "application/json" })), link = node("a"); link.href = url; link.download = "habitat-work-" + selected.replace(/[^A-Za-z0-9_-]/g, "_") + ".json"; document.body.append(link); link.click(); link.remove(); setTimeout(function () { URL.revokeObjectURL(url); }, 1000); }));
    var audit = localLink(detail.audit_url, "Open full audit", "audit", detail.item); if (audit) actions.append(audit); container.append(actions);
  }
  function activity(container) {
    var log = detail.activity;
    if (!log || log.run_id !== selected) { container.append(empty("Activity unavailable", "The saved report is still available.")); return; }
    var totals = log.totals || {}, metrics = node("dl", "review-metrics");
    metric(metrics, "Model decisions", totals.model_decisions); metric(metrics, "Tool actions", totals.tool_calls); metric(metrics, "Web searches", totals.web_search_calls); container.append(metrics);
    container.append(node("p", "review-cost-note", "Original actions and recovery steps stay in this run. Model decisions count the writing worker; tool actions may contain additional research calls."));
    if (detail.question && detail.question.text) container.append(node("p", "notice info", detail.question.text));
    if (detail.item.reason) container.append(node("p", "notice info", String(detail.item.reason).replace(/_/g, " ")));
    var wrap = node("div", "review-table-wrap"), table = node("table"), header = node("tr"), head = node("thead"), body = node("tbody");
    table.append(node("caption", "", "Actions in execution order · times shown in your local timezone"));
    ["Action", "Time", "State", "Recorded cost"].forEach(function (name) { var th = node("th", "", name); th.scope = "col"; header.append(th); }); head.append(header); table.append(head, body);
    (log.steps || []).forEach(function (step) {
      var row = node("tr"), action = node("td"), link = localLink(step.evidence_url, step.label || step.tool_name || step.kind, "audit", detail.item);
      if (link && step.details_url) { link.dataset.actionDetails = step.details_url; link.setAttribute("aria-haspopup", "dialog"); }
      action.append(link || node("span", "", step.label || step.tool_name || step.kind)); if (step.model) action.append(node("small", "", step.model));
      var state = node("td", "", String(step.state || "Unknown").replace(/_/g, " ")); if (step.error) state.append(node("small", "", step.error));
      var cost = node("td", "", money(recorded(step.cost_summary, step.usage))); if (step.cost_summary && step.cost_summary.held_micro_usd) cost.append(node("small", "", money(step.cost_summary.held_micro_usd) + " reserved"));
      row.append(action, node("td", "", date(step.created_at, true)), state, cost); body.append(row);
    });
    if (log.steps && log.steps.length) { wrap.append(table); container.append(wrap); } else container.append(node("p", "review-cost-note", "No actions have been recorded yet.")); logActions(container);
  }
  function costs(container) {
    var item = detail.item, summary = item.cost_summary || {}, totals = (detail.activity || {}).totals || {};
    container.append(node("div", "review-cost-total", money(item.recorded_micro_usd)), node("p", "review-cost-note", "Recorded for this run. Setup and other runs are separate."));
    function charge(label, value) { var row = node("div", "review-cost-row"); row.append(node("span", "", label), node("span", "", value)); container.append(row); }
    charge("Recorded charge", money(item.recorded_micro_usd)); charge("Reserved · not charged", money(summary.held_micro_usd || 0));
    if (summary.estimated_micro_usd) charge("Runtime estimate · separate", money(summary.estimated_micro_usd));
    charge("Model decisions", totals.model_decisions == null ? "Unavailable" : totals.model_decisions); charge("Tool actions", totals.tool_calls == null ? "Unavailable" : totals.tool_calls);
    charge("Tokens · input / output", totals.input_tokens == null ? "Unavailable" : Number(totals.input_tokens).toLocaleString() + " / " + Number(totals.output_tokens || 0).toLocaleString());
    container.append(node("p", "review-cost-note", summary.coverage_note || "Only recorded usage is charged here. Missing metering is not assumed to be free."));
    logActions(container);
  }
  function renderAssistant() {
    var container = $("[data-review-assistant]"); container.replaceChildren();
    if (!detail) { container.append(node("p", "", "Select a run to open its agent’s assistant.")); return; }
    var item = detail.item, context = node("div", "review-assistant-context"); context.append(node("strong", "", item.agent_name), node("small", "", "Selected work: " + item.title)); container.append(context);
    container.append(node("p", "", "The agent assistant helps change future goals, instructions, and settings in the agent workspace."), node("p", "field-hint", "It does not receive this historical report automatically. Review this report’s sources, activity, and costs here."));
    var link = localLink(item.assistant_url, "Open agent assistant", "workspace", item); if (link) { link.className = "button secondary"; container.append(link); }
  }
  async function mark(change) {
    if (marking || !detail) return; var id = selected, epoch = detailEpoch, version = detail.item.version, filterKey = filters().toString(), previousItem = Object.assign({}, detail.item); marking = true; renderReader(); error("");
    try {
      var result = await request(endpoint(id) + "/marks", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": root.dataset.csrf, Accept: "application/json" }, body: JSON.stringify(Object.assign({ expected_version: version }, change)) });
      if (result.run_id !== id) throw new Error("The saved mark did not match this run.");
      markReceipts.set(id, { revision: ++markRevision, result: result });
      if (detail && detail.item.run_id === id && detail.item.version === result.version) Object.assign(detail.item, result);
      rows.forEach(function (row) { if (row.run_id === id && row.version === result.version) Object.assign(row, result); });
      rows = rows.filter(matchesMarkView);
      var restoredToView = !matchesMarkView(previousItem) && matchesMarkView(Object.assign({}, previousItem, result)) && !rows.some(function (row) { return row.run_id === id; });
      if (filterKey !== filters().toString() || restoredToView) {
        // The new view may have loaded before this write and omitted a run that
        // now belongs there, or the owner undid a mark that removed this row.
        // Reload that view; loadList invalidates any earlier list response.
        await loadList(false);
      } else {
        renderList();
        // Normal marks refresh only totals, preserving older pages and cursor.
        await refreshCounts();
      }
    } catch (e) { if (epoch === detailEpoch) error(e.message); }
    finally { marking = false; if (detail) renderReader(); }
  }
  function resetSelection() { selected = ""; outputId = ""; detail = null; ++detailEpoch; reader.replaceChildren(empty("Loading work…", "Applying your filters.")); reader.setAttribute("aria-busy", "true"); renderAssistant(); loadList(false); }
  form.addEventListener("submit", function (event) { event.preventDefault(); clearTimeout(searchTimer); if (selected) select(selected, false); loadList(false); });
  form.querySelectorAll("select,input[type=date]").forEach(function (field) { field.addEventListener("change", resetSelection); });
  $("#review-search").addEventListener("input", function () { clearTimeout(searchTimer); searchTimer = setTimeout(resetSelection, 250); });
  $("[data-review-more]").addEventListener("click", function () { if (!loadingList && nextCursor) loadList(true); });
  $("[data-clear-filters]").addEventListener("click", function () { form.reset(); params.delete("workspace_id"); resetSelection(); });
  var toggle = document.getElementById("review-assistant-toggle");
  function assistant(open) { $("#review-assistant").hidden = !open; $(".review-layout").classList.toggle("assistant-open", open); toggle.setAttribute("aria-expanded", String(open)); toggle.textContent = open ? "Hide assistant" : "Agent assistant"; }
  toggle.addEventListener("click", function () { assistant($("#review-assistant").hidden); }); $("[data-close-assistant]").addEventListener("click", function () { assistant(false); toggle.focus(); });
  if (params.get("workspace_id")) { var initial = node("option", "", "Selected agent"); initial.value = params.get("workspace_id"); $("#review-agent").append(initial); $("#review-agent").value = initial.value; }
  loadList(false); if (selected) select(selected, false);
}());
