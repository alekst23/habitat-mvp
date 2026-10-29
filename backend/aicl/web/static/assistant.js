(function () {
  "use strict";
  var root = document.querySelector("[data-owner-assistant]");
  if (!root) return;
  var message = document.getElementById("assistant-message");
  var messageForm = root.querySelector('[data-assistant-submit="message"]');
  var runPanel = root.querySelector("[data-assistant-run]");
  var currentRun = null;
  var terminalStates = ["completed", "cancelled", "failed"];
  var statusLabels = { queued: "Ready to continue", running: "Working", waiting_owner: "Needs your input",
    blocked: "Blocked", paused: "Paused", completed: "Completed", failed: "Failed", cancelled: "Cancelled" };
  var actionLabels = { advance: "Continue work", pause: "Pause work", resume: "Resume work", cancel: "Cancel work" };
  var requestLabels = { start: "Starting work…", advance: "Continuing work…", pause: "Pausing work…",
    resume: "Resuming work…", cancel: "Cancelling work…", confirm: "Applying your confirmed proposal…", funding: "Opening payment checkout…" };
  function isTerminal() {
    return runPanel && terminalStates.indexOf(runPanel.dataset.runStatus) !== -1;
  }
  function node(tag, className, text) {
    var element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function hiddenField(form, name, value) {
    var input = node("input");
    input.type = "hidden"; input.name = name; input.value = value;
    form.appendChild(input);
    return input;
  }
  root.querySelectorAll("[data-assistant-example]").forEach(function (button) {
    button.addEventListener("click", function () {
      message.value = button.dataset.assistantExample;
      message.focus();
      message.setSelectionRange(message.value.length, message.value.length);
    });
  });
  root.addEventListener("click", function (event) {
    var option = event.target.closest("[data-assistant-option]");
    if (option) {
      if (currentRun) syncComposer(currentRun, true);
      message.value = option.dataset.assistantOption;
      message.focus();
    }
    if (event.target.closest("[data-assistant-revise]")) message.focus();
  });
  message.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing) {
      event.preventDefault();
      messageForm.requestSubmit();
    }
  });
  root.addEventListener("submit", function (event) {
    var form = event.target.closest("[data-assistant-submit]");
    if (!form) return;
    if (root.dataset.submitting === "true" || (form === messageForm && isTerminal())) { event.preventDefault(); return; }
    root.dataset.submitting = "true";
    form.setAttribute("aria-busy", "true");
    root.querySelectorAll('[data-assistant-submit] button[type="submit"]').forEach(function (button) { button.disabled = true; });
    // Keep successful form fields enabled so ordinary browser submission works.
    message.readOnly = true;
    var status = form.querySelector("[data-assistant-request-status]");
    if (status) status.textContent = form.dataset.assistantSubmit === "message" ?
      (runPanel ? "Sending to this run…" : "Working on your message…") : requestLabels[form.dataset.assistantSubmit];
  });
  window.addEventListener("pageshow", function () {
    delete root.dataset.submitting;
    message.readOnly = !!isTerminal();
    root.querySelectorAll("[data-assistant-submit]").forEach(function (form) {
      form.removeAttribute("aria-busy");
      form.querySelectorAll('button[type="submit"]').forEach(function (button) { button.disabled = form === messageForm && !!isTerminal(); });
      var status = form.querySelector("[data-assistant-request-status]");
      if (status) status.textContent = "";
    });
    syncStartReadiness();
  });
  var agent = document.getElementById("assistant-run-agent");
  function syncStartReadiness() {
    if (!agent) return;
    var ready = false;
    root.querySelectorAll("[data-candidate-readiness]").forEach(function (panel) {
      panel.hidden = panel.dataset.candidateReadiness !== agent.value;
      if (!panel.hidden) ready = panel.dataset.ready === "true";
    });
    root.querySelector("[data-start-work]").disabled = !ready;
  }
  if (agent) agent.addEventListener("change", function () {
    var consent = root.querySelector("[data-runtime-web-read]");
    consent.checked = false;
    consent.disabled = agent.options[agent.selectedIndex].dataset.webRead !== "true";
    syncStartReadiness();
  });
  function money(value) {
    return "$" + (Math.max(0, value) / 1000000).toFixed(6).replace(/0{1,4}$/, "");
  }
  function renderReadiness(run) {
    var container = runPanel.querySelector("[data-run-readiness]");
    container.replaceChildren();
    var readiness = run.readiness;
    if (!readiness || ["blocked", "paused"].indexOf(run.status) === -1 ||
        !/^[0-9a-f-]{36}$/i.test(run.instance_id || "")) return;
    var panel = node("div", "assistant-funding");
    panel.appendChild(node("h3", "", readiness.ready ? "Ready for the next step" : "Before work can continue"));
    panel.appendChild(node("p", "", "Available service credit: " + money(readiness.balance_micro_usd)));
    if (readiness.required_micro_usd !== null) panel.appendChild(node("p", "field-hint",
      "The next step requires up to " + money(readiness.required_micro_usd) + " in available credit. Total cost depends on the work."));
    var blockers = readiness.blockers || [];
    if (blockers.length) {
      var list = node("ul");
      blockers.forEach(function (blocker) { list.appendChild(node("li", "", blocker.message)); });
      panel.appendChild(list);
    }
    var needsCredit = blockers.some(function (blocker) { return blocker.reason === "credit_insufficient"; });
    if (needsCredit && /^[0-9a-f-]{36}$/i.test(readiness.funding_order_id || "")) {
      panel.appendChild(node("p", "", "Finish or check your existing payment before adding more funds."));
      var paymentLink = node("a", "button primary assistant-confirm-button", "Continue payment");
      paymentLink.href = "/commerce/orders/" + encodeURIComponent(readiness.funding_order_id);
      panel.appendChild(paymentLink);
    } else if (needsCredit) {
      var form = node("form");
      form.method = "post"; form.action = "/chat/funding"; form.dataset.assistantSubmit = "funding";
      hiddenField(form, "csrf_token", messageForm.querySelector('[name="csrf_token"]').value);
      hiddenField(form, "chat_session_id", root.dataset.sessionId);
      hiddenField(form, "instance_id", run.instance_id);
      hiddenField(form, "request_id", messageForm.querySelector('[name="request_id"]').value);
      var label = node("label", "", "Add service credit"), select = node("select");
      select.name = "amount_minor"; select.id = "assistant-run-topup"; label.htmlFor = select.id;
      [500, 1000, 2000].forEach(function (amount) {
        var option = node("option", "", "$" + (amount / 100).toFixed(2));
        option.value = String(amount); select.appendChild(option);
      });
      form.appendChild(label); form.appendChild(select);
      var button = node("button", "primary assistant-confirm-button", "Add funds with PayPal");
      button.type = "submit"; form.appendChild(button);
      form.appendChild(node("p", "field-hint", "Review and authorize payment in checkout, then return here to start or resume this work."));
      var status = node("p", "assistant-request-status field-hint");
      status.dataset.assistantRequestStatus = ""; status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite"); form.appendChild(status);
      panel.appendChild(form);
    }
    if (blockers.some(function (blocker) { return blocker.reason !== "credit_insufficient"; })) {
      var link = node("a", "", "Review spending limits and controls");
      link.href = "/instances/" + encodeURIComponent(run.instance_id) + "#budgets";
      panel.appendChild(link);
    }
    container.appendChild(panel);
  }
  function syncComposer(run, force) {
    var questionInput = messageForm.querySelector('[name="question_id"]');
    var question = run.question;
    var terminal = terminalStates.indexOf(run.status) !== -1;
    var terminalNote = root.querySelector("[data-assistant-terminal]");
    terminalNote.hidden = !terminal;
    terminalNote.textContent = run.status === "completed" ? "This work is complete. Start a new conversation for another task." :
      "This run has ended. Start a new conversation for another task.";
    messageForm.hidden = terminal && !message.value.trim();
    message.readOnly = terminal;
    messageForm.querySelector('button[type="submit"]').disabled = terminal;
    // A newly arriving question must not retarget a response already being typed.
    if (!force && message.value.trim()) {
      if (questionInput.value !== (question ? question.id : "")) {
        document.getElementById("assistant-composer-hint").textContent = "The question changed. Clear this draft to answer the current question.";
      }
      return;
    }
    questionInput.value = question ? question.id : "";
    questionInput.disabled = !question;
    messageForm.querySelector('label[for="assistant-message"]').textContent = question ? "Answer the agent’s question" : "Guide this work";
    document.getElementById("assistant-composer-hint").textContent = "Your message goes directly to this run. Its permissions and spending limits still apply.";
  }
  message.addEventListener("input", function () {
    if (currentRun && !message.value.trim()) syncComposer(currentRun);
  });
  function renderMessages(messages) {
    if (!Array.isArray(messages)) return;
    var transcript = root.querySelector("[data-assistant-transcript]");
    var list = transcript.querySelector(".assistant-messages");
    var followLatest = !list || transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 48;
    var existing = new Set(Array.from(transcript.querySelectorAll("[data-runtime-event-id]")).map(function (item) {
      return item.dataset.runtimeEventId;
    }));
    messages.forEach(function (entry) {
      if (!entry || typeof entry.id !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(entry.id) ||
          existing.has(entry.id) || ["user", "assistant"].indexOf(entry.role) === -1 || typeof entry.text !== "string") return;
      if (!list) {
        var welcome = transcript.querySelector(".assistant-welcome");
        if (welcome) welcome.remove();
        list = node("ol", "assistant-messages");
        list.setAttribute("aria-label", "Conversation");
        transcript.insertBefore(list, transcript.querySelector("#assistant-latest"));
      }
      var item = node("li", "assistant-message " + (entry.role === "user" ? "from-owner" : "from-assistant"));
      item.dataset.runtimeEventId = entry.id;
      item.appendChild(node("p", "assistant-message-label", entry.role === "user" ? "You" : "Habitat"));
      item.appendChild(node("div", "assistant-message-text", entry.text));
      list.appendChild(item);
      existing.add(entry.id);
    });
    if (followLatest) transcript.scrollTop = transcript.scrollHeight;
  }
  function renderRun(run) {
    if (!run || run.id !== runPanel.dataset.runId || !Object.prototype.hasOwnProperty.call(statusLabels, run.status)) return;
    currentRun = run;
    runPanel.dataset.runStatus = run.status;
    runPanel.dataset.runVersion = String(run.version);
    runPanel.querySelector("[data-run-status-label]").textContent = statusLabels[run.status];
    runPanel.querySelector("[data-run-objective]").textContent = run.objective;
    var reason = runPanel.querySelector("[data-run-reason]");
    reason.hidden = !run.reason;
    reason.textContent = run.reason === "credit_insufficient" ?
      (run.readiness && run.readiness.ready ? "Service credit is available. You can resume this work." :
        "This work needs more service credit. Add funds below, then resume.") : String(run.reason || "").replace(/_/g, " ");
    renderReadiness(run);
    var plan = runPanel.querySelector("[data-run-plan]");
    plan.replaceChildren();
    run.plan.forEach(function (item) {
      var row = node("li"), heading = node("div");
      heading.appendChild(node("span", "assistant-plan-title", item.title));
      heading.appendChild(node("span", "assistant-plan-state", String(item.state).replace(/_/g, " ")));
      row.appendChild(heading);
      if (item.summary) row.appendChild(node("p", "", item.summary));
      plan.appendChild(row);
    });
    runPanel.querySelector("[data-run-empty-plan]").hidden = !!run.plan.length;
    var artifacts = runPanel.querySelector("[data-run-artifacts]");
    var openNames = Array.from(artifacts.querySelectorAll("details[open] summary")).map(function (summary) { return summary.firstChild.textContent; });
    artifacts.replaceChildren();
    run.artifacts.forEach(function (artifact) {
      var detail = node("details", "assistant-run-artifact"), summary = node("summary", "", artifact.name);
      summary.appendChild(node("span", "", "Version " + artifact.version + " · " + (artifact.completed ? "Completed" : "Draft")));
      detail.appendChild(summary);
      detail.appendChild(node("div", "assistant-artifact-content", artifact.content));
      detail.open = artifact.completed || openNames.indexOf(artifact.name) !== -1;
      artifacts.appendChild(detail);
    });
    runPanel.querySelector("[data-run-empty-artifacts]").hidden = !!run.artifacts.length;
    var question = runPanel.querySelector("[data-run-question]"), options = runPanel.querySelector("[data-run-options]");
    question.hidden = !run.question;
    runPanel.querySelector("[data-run-question-text]").textContent = run.question ? run.question.text : "";
    options.replaceChildren();
    if (run.question) run.question.options.forEach(function (text) {
      var option = node("button", "secondary", text);
      option.type = "button"; option.dataset.assistantOption = text;
      options.appendChild(option);
    });
    var controls = runPanel.querySelector("[data-run-controls]");
    controls.replaceChildren();
    ["advance", "pause", "resume", "cancel"].forEach(function (action) {
      if (!run["can_" + action]) return;
      var form = node("form");
      form.method = "post"; form.action = "/chat/runs/" + encodeURIComponent(run.id) + "/" + action;
      form.dataset.assistantSubmit = action;
      hiddenField(form, "csrf_token", messageForm.querySelector('[name="csrf_token"]').value);
      hiddenField(form, "chat_session_id", root.dataset.sessionId);
      var button = node("button", action === "resume" || action === "advance" ? "primary" : "secondary", actionLabels[action]);
      button.type = "submit"; form.appendChild(button);
      var status = node("p", "assistant-request-status field-hint");
      status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
      status.dataset.assistantRequestStatus = ""; form.appendChild(status);
      controls.appendChild(form);
    });
    syncComposer(run);
  }
  async function pollRun() {
    if (!runPanel || ["queued", "running"].indexOf(runPanel.dataset.runStatus) === -1) return;
    if (document.hidden || root.dataset.submitting === "true") { window.setTimeout(pollRun, 3000); return; }
    var status = runPanel.querySelector("[data-run-refresh-status]");
    try {
      var response = await fetch("/chat/runs/status?session_id=" + encodeURIComponent(root.dataset.sessionId), {
        headers: { "Accept": "application/json" }, credentials: "same-origin", cache: "no-store"
      });
      if (!response.ok) throw new Error("Status unavailable");
      var result = await response.json();
      if (root.dataset.submitting === "true") return;
      if (!result.runtime_run) { status.textContent = "Refresh the page to see current work."; return; }
      renderMessages(result.runtime_messages);
      if (String(result.runtime_run.version) !== runPanel.dataset.runVersion || result.runtime_run.status !== runPanel.dataset.runStatus) {
        renderRun(result.runtime_run);
      }
      status.textContent = "";
      window.setTimeout(pollRun, 2000);
    } catch (_) {
      status.textContent = "Couldn’t refresh progress. Retrying…";
      window.setTimeout(pollRun, 10000);
    }
  }
  if (runPanel) window.setTimeout(pollRun, 2000);
  var transcript = root.querySelector("[data-assistant-transcript]");
  if (transcript.querySelector(".assistant-messages")) transcript.scrollTop = transcript.scrollHeight;
})();
