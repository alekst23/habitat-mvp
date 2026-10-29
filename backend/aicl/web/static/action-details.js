/* Owner-only saved evidence viewer. Opening this panel never executes work. */
(function () {
  "use strict";
  var dialog, body, heading, opener, controller, generation = 0, savedPayload, currentURL;
  function node(tag, cls, text) { var result = document.createElement(tag); if (cls) result.className = cls; if (text != null) result.textContent = String(text); return result; }
  function allowedURL(value) {
    if (typeof value !== "string" || !/^\/api\/audit\/runs\/[A-Za-z0-9_-]+\/steps\/[A-Za-z0-9_-]+$/.test(value)) return null;
    return value;
  }
  function button(label, handler, cls) { var result = node("button", cls || "secondary", label); result.type = "button"; result.addEventListener("click", handler); return result; }
  function create() {
    if (dialog) return;
    dialog = node("dialog", "action-detail-dialog"); dialog.setAttribute("aria-labelledby", "action-detail-title");
    var top = node("header", "action-detail-header"), titles = node("div");
    titles.append(node("p", "kicker", "Saved action record")); heading = node("h2", "", "Action details"); heading.id = "action-detail-title"; titles.append(heading);
    top.append(titles, button("Close", function () { dialog.close(); }, "secondary action-detail-close"));
    body = node("div", "action-detail-body"); dialog.append(top, body); document.body.append(dialog);
    dialog.addEventListener("close", function () {
      generation += 1; if (controller) controller.abort(); savedPayload = null;
      var target = opener; opener = null;
      if (target && !target.isConnected) target = Array.from(document.querySelectorAll("[data-action-details]")).find(function (candidate) { return candidate.dataset.actionDetails === currentURL; });
      if (target && target.isConnected) target.focus();
    });
    dialog.addEventListener("click", function (event) { if (event.target === dialog) { var bounds = dialog.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close(); } });
  }
  function textValue(value) { return typeof value === "string" ? value : JSON.stringify(value, null, 2); }
  function valueBlock(parent, value) {
    if (value == null) { parent.append(node("p", "action-detail-muted", "Not recorded.")); return; }
    var pre = node("pre", "action-detail-content", textValue(value)); pre.tabIndex = 0; parent.append(pre);
  }
  function section(parent, title, data, open) {
    var details = node("details", "action-detail-section"); details.open = !!open;
    details.append(node("summary", "", title)); var content = node("div", "action-detail-section-body");
    if (data == null) content.append(node("p", "action-detail-muted", "Not recorded for this action."));
    else if (typeof data === "object" && !Array.isArray(data) && ("content" in data || ["retained", "not_retained"].includes(data.status))) {
      if (data.label) content.append(node("p", "action-detail-label", data.label));
      if (data.status === "not_retained") content.append(node("p", "action-detail-muted", "Not retained for this action."));
      if (data.note) content.append(node("p", "action-detail-note", data.note));
      if (data.availability && data.availability !== "recorded") content.append(node("p", "action-detail-muted", String(data.availability).replace(/_/g, " ")));
      if ("content" in data && data.content != null) valueBlock(content, data.content);
      else if (!(data.note || data.availability || data.status === "not_retained")) content.append(node("p", "action-detail-muted", "No saved content is available."));
      if (data.content_ref) content.append(node("p", "action-detail-reference", "Saved reference: " + data.content_ref));
    } else valueBlock(content, data);
    details.append(content); parent.append(details);
  }
  function money(value) { return Number.isSafeInteger(value) ? "$" + (value / 1000000).toFixed(6).replace(/0{1,4}$/, "") : "Not recorded"; }
  function metric(parent, label, value) { var group = node("div"); group.append(node("dt", "", label), node("dd", "", value == null ? "Not recorded" : value)); parent.append(group); }
  function download() {
    if (!savedPayload) return;
    var url = URL.createObjectURL(new Blob([JSON.stringify(savedPayload, null, 2) + "\n"], { type: "application/json" })), link = node("a");
    link.href = url; link.download = "habitat-action-" + String((savedPayload.step || {}).id || savedPayload.step_id || "details").replace(/[^A-Za-z0-9_-]/g, "_") + ".json";
    document.body.append(link); link.click(); link.remove(); setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }
  function render(payload) {
    savedPayload = payload; var step = payload.step || {}, usage = step.usage || {}, cost = step.cost_summary || {};
    heading.textContent = step.label || step.tool_name || "Action details"; body.replaceChildren();
    var summary = node("dl", "action-detail-metrics");
    metric(summary, "State", String(step.state || "Not recorded").replace(/_/g, " "));
    if (step.created_at) metric(summary, "Time", new Date(step.created_at).toLocaleString());
    var model = step.model || (step.receipt_metadata || {}).model; if (model) metric(summary, "Model", model);
    if (usage.input_tokens != null || usage.output_tokens != null) metric(summary, "Tokens · input / output", (usage.input_tokens == null ? "—" : Number(usage.input_tokens).toLocaleString()) + " / " + (usage.output_tokens == null ? "—" : Number(usage.output_tokens).toLocaleString()));
    var measured = (cost.components || []).some(function (part) { return ["recorded", "bundled"].includes(part.coverage) && part.amount_micro_usd != null; });
    metric(summary, "Recorded cost", money(measured || Number.isSafeInteger(usage.cost_micro_usd) ? cost.settled_micro_usd == null ? usage.cost_micro_usd : cost.settled_micro_usd : null));
    if (cost.held_micro_usd) metric(summary, "Reserved · not charged", money(cost.held_micro_usd));
    body.append(summary);
    if (step.error) body.append(node("p", "notice error", String(step.error).replace(/_/g, " ")));
    body.append(node("p", "action-detail-note", "These are saved records. Viewing them does not rerun the action, contact a provider, or approve its contents."));
    (payload.limitations || []).forEach(function (note) { body.append(node("p", "action-detail-muted", note)); });
    section(body, "What was requested", payload.request, true);
    section(body, "What came back", payload.response, true);
    var records = payload.records || [];
    if (records.length) {
      var group = node("section", "action-detail-records"); group.append(node("h3", "", "Calls and saved evidence"));
      records.forEach(function (record, index) {
        var entry = node("details", "action-detail-record"); entry.append(node("summary", "", record.label || record.kind || "Record " + (index + 1)));
        var content = node("div", "action-detail-section-body");
        if (record.note) content.append(node("p", "action-detail-note", record.note));
        if (record.request !== undefined || record.response !== undefined) { section(content, "Request", record.request, true); section(content, "Response", record.response, true); }
        else valueBlock(content, record.content === undefined ? record : record.content);
        if (record.metadata) section(content, "Call metadata", record.metadata, false);
        entry.append(content); group.append(entry);
      }); body.append(group);
    }
    var actions = node("div", "action-detail-actions"); actions.append(button("Download action details", download));
    section(body, "Complete saved record", payload, false); body.append(actions);
  }
  async function open(value, trigger) {
    var url = allowedURL(value); if (!url) return false;
    create(); if (trigger) opener = trigger; currentURL = url;
    if (controller) controller.abort(); controller = new AbortController(); var ticket = ++generation;
    heading.textContent = "Action details"; body.replaceChildren(node("p", "action-detail-loading", "Loading the saved request and result…")); body.setAttribute("aria-busy", "true"); savedPayload = null;
    if (!dialog.open) dialog.showModal();
    try {
      var response = await fetch(url, { method: "GET", credentials: "same-origin", cache: "no-store", redirect: "error", headers: { Accept: "application/json" }, signal: controller.signal });
      if (!response.ok) throw new Error(response.status === 404 ? "This saved action is unavailable." : response.status === 401 || response.status === 403 ? "Sign in as the owner to view this action." : "The saved action could not be loaded. Please try again.");
      if (!(response.headers.get("Content-Type") || "").includes("application/json")) throw new Error("The saved action could not be loaded. Please try again.");
      var payload = await response.json(), ids = url.split("/"); if (!payload || payload.schema_version !== 1 || payload.run_id !== ids[4] || !payload.step || payload.step.id !== ids[6]) throw new Error("The saved action could not be loaded. Please try again.");
      if (ticket === generation && dialog.open) render(payload);
    } catch (error) {
      if (ticket !== generation || !dialog.open || error.name === "AbortError") return true;
      var message = node("p", "notice error", error instanceof TypeError ? "The saved action could not be loaded. Check your connection and try again." : error.message); message.setAttribute("role", "alert");
      body.replaceChildren(message, button("Try again", function () { open(currentURL); }));
    } finally { if (ticket === generation) body.removeAttribute("aria-busy"); }
    return true;
  }
  document.addEventListener("click", function (event) {
    var trigger = event.target.closest && event.target.closest("[data-action-details]");
    if (!trigger || !allowedURL(trigger.dataset.actionDetails) || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); open(trigger.dataset.actionDetails, trigger);
  });
  window.HabitatActionDetails = Object.freeze({ open: open });
})();
