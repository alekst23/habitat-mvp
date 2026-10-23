"""Autoescaped owner pages for instance controls and simulated connections (E11-5)."""

from __future__ import annotations

from jinja2 import DictLoader, Environment

from aicl.commerce.pages import TEMPLATES as COMMERCE_TEMPLATES, credit, license_label, money, readiness_destination, result_text, run_label
from aicl.web.pages import TEMPLATES as BASE_TEMPLATES

NOTICES = {"saved": "Saved.", "cleared": "Gate cleared.", "revoked": "Connection revoked.",
           "connected": "Connected.", "denied": "The connection was not authorized."}

CAPABILITY_COPY = {
    "inference": "Allow model requests within your inference and compute limits.",
    "gmail.read": "Read through an attached Gmail connection.",
    "gmail.send": "Send through an attached Gmail connection. Each action needs your confirmation.",
    "reddit.read": "Read through an attached Reddit connection.",
    "reddit.post": "Post through an attached Reddit connection. Each action needs your confirmation.",
    "network.fetch": "Fetch from permitted HTTPS domains in the network allow-list.",
}

TEMPLATES = {
    "instance": """{% extends "base" %}{% set page_key = "instance" %}
{% block eyebrow %}{% if commerce %}YOUR AGENT WORKSPACE{% else %}AGENT CONTROL ROOM{% endif %}{% endblock %}
{% block subtitle %}{% if commerce %}Set funding and boundaries for scheduled work. Respond in Requests and review completed work in Audit.{% else %}Set the boundaries. Review the activity. Stay in control.{% endif %}{% endblock %}
{% block header_actions %}{% if commerce %}<a class="button primary" href="/instances/{{ d.snapshot.id }}/workflow">Goals &amp; schedule</a><a class="button secondary" href="/audit?instance_id={{ d.snapshot.id }}">Audit</a>{% endif %}<a class="button secondary" href="/workspace">Back to workspace</a>{% endblock %}
{% block body %}
{% set request_instance_id = d.snapshot.id %}{% include "requests/attention" %}
{% if commerce %}{% include "commerce/style" %}{% endif %}
<div id="instance-state">
{% if notice %}<div class="notice success" role="status">{{ notice }}</div>{% endif %}
{% if error %}<div class="notice error" role="alert"><strong>{{ error.error }}{% if error.reason %}: {{ error.reason }}{% endif %}</strong>
<p>{{ error.message }}</p>{% if error.current_version %}<p>Current version: {{ error.current_version }}. Reload and retry.</p>{% endif %}
{% if error.field_errors %}<ul>{% for e in error.field_errors %}<li>{{ e.field }}: {{ e.code }}</li>{% endfor %}</ul>{% endif %}</div>{% endif %}
{% if not commerce %}<div class="stat-grid" aria-label="Agent controls overview">
  <div class="stat-card"><span class="stat-label">Current status</span><span class="stat-value"><span class="status-badge {{ d.snapshot.status }}">{{ d.snapshot.status }}</span></span><span class="stat-note">Lifecycle: {{ d.snapshot.lifecycle }}</span></div>
  <div class="stat-card"><span class="stat-label">Inference · daily available</span><span class="stat-value">${{ usd(d.budget.windows.inference.day.available) }}</span><span class="stat-note">Of ${{ usd(d.budget.windows.inference.day.limit) }} daily limit</span></div>
  <div class="stat-card"><span class="stat-label">Compute · daily available</span><span class="stat-value">${{ usd(d.budget.windows.compute.day.available) }}</span><span class="stat-note">Of ${{ usd(d.budget.windows.compute.day.limit) }} daily limit</span></div>
  <div class="stat-card"><span class="stat-label">Enabled capabilities</span><span class="stat-value">{{ d.snapshot.capabilities.values()|select|list|length }} <small>/ {{ d.snapshot.capabilities|length }}</small></span><span class="stat-note">Only the permissions you choose</span></div>
</div>
{% endif %}
<nav class="button-row section-anchor" aria-label="Agent sections">{% if commerce %}<a class="button ghost" href="/instances/{{ d.snapshot.id }}/workflow">Goals &amp; schedule</a><a class="button ghost" href="#overview">Setup</a><a class="button ghost" href="#funding">Funding</a>{% else %}<a class="button ghost" href="#overview">Overview</a>{% endif %}<a class="button ghost" href="#budgets">Budget</a><a class="button ghost" href="#capabilities">Capabilities</a><a class="button ghost" href="#activity">Activity</a></nav>
{% if commerce %}
<section class="card" id="setup"><div class="card-body"><p class="kicker">SET UP &amp; FUND</p><h2>Boundaries for scheduled work</h2><p>Set your agent’s service credit, spending limits and capabilities here. Then return to its goals and schedule to enable work.</p><a class="button secondary" href="/instances/{{ d.snapshot.id }}/workflow">Review goals &amp; schedule →</a></div></section>
<div class="section-heading controls-heading"><div><span class="kicker">AGENT SETTINGS</span><h2>Boundaries &amp; activity</h2></div><p class="muted">Review the controls that apply to every task.</p></div>
<div class="stat-grid" aria-label="Agent controls overview">
  <div class="stat-card"><span class="stat-label">Current status</span><span class="stat-value"><span class="status-badge {{ d.snapshot.status }}">{{ d.snapshot.status }}</span></span><span class="stat-note">Lifecycle: {{ d.snapshot.lifecycle }}</span></div>
  <div class="stat-card"><span class="stat-label">Inference · daily available</span><span class="stat-value">${{ usd(d.budget.windows.inference.day.available) }}</span><span class="stat-note">Of ${{ usd(d.budget.windows.inference.day.limit) }} daily limit</span></div>
  <div class="stat-card"><span class="stat-label">Compute · daily available</span><span class="stat-value">${{ usd(d.budget.windows.compute.day.available) }}</span><span class="stat-note">Of ${{ usd(d.budget.windows.compute.day.limit) }} daily limit</span></div>
  <div class="stat-card"><span class="stat-label">Enabled capabilities</span><span class="stat-value">{{ d.snapshot.capabilities.values()|select|list|length }} <small>/ {{ d.snapshot.capabilities|length }}</small></span><span class="stat-note">Only the permissions you choose</span></div>
</div>
{% endif %}
<div class="detail-grid" id="overview">
  <div class="main-column">
    <section class="card"><div class="card-header"><div><span class="kicker">YOUR AGENT</span><h2>Purpose &amp; controls</h2></div><span class="status-badge {{ d.snapshot.status }}">{{ d.snapshot.status }}</span></div>
    <div class="card-body"><h3>Saved agent instructions</h3>{% if commerce %}<p class="field-hint">These describe the agent’s purpose and boundaries. Goals, deliverables and completion criteria are configured on its Goals &amp; schedule page.</p>{% endif %}{% if d.snapshot.instructions %}<p style="white-space: pre-wrap">{{ d.snapshot.instructions }}</p>{% else %}<p class="muted">No instructions have been added to this agent.</p>{% endif %}
    {% if d.snapshot.gated_reason %}<div class="notice error" role="status"><strong>Work is gated</strong><p>Gated: <code>{{ d.snapshot.gated_reason }}</code></p><p>{{ gate_guidance }}</p></div>
    {% elif d.snapshot.status == "gated" %}<div class="notice info" role="status"><strong>Work is gated while an outstanding request is reconciled.</strong><p>Its reservation remains held until the outcome is known.</p></div>{% endif %}
    {% if d.snapshot.lifecycle == "draft" %}<p class="muted">This agent is a draft. Set its budgets and permissions, then activate it when you are ready.</p>
    {% elif d.snapshot.lifecycle == "paused" %}<p class="muted">You paused this agent. Resume it to allow new work, subject to its budgets and permissions.</p>
    {% elif d.snapshot.lifecycle == "archived" %}<p class="muted">This agent is archived. It cannot run again; its history remains available.</p>
    {% else %}<p class="muted">This agent is active. Every request must still pass its budget, capability and connection checks.</p>{% endif %}
    {% if actions %}<form method="post" action="/instances/{{ d.snapshot.id }}/lifecycle" class="button-row">{{ hidden }}
    {% for action, label in actions %}<button class="{% if action == 'archive' %}danger{% elif action == 'pause' %}secondary{% else %}primary{% endif %}" type="submit" name="action" value="{{ action }}">{{ label }}</button>{% endfor %}</form>
    <p class="field-hint">Pause is reversible. Archive permanently stops this agent.</p>{% endif %}
    {% if d.snapshot.gated_reason %}<div class="panel"><form method="post" action="/instances/{{ d.snapshot.id }}/resolve-gate">{{ hidden }}<button class="secondary" type="submit">Re-check and clear</button></form><p class="field-hint">Saving the relevant control re-checks this gate automatically. Use this check only if the gate remains after you fix the cause.</p></div>{% endif %}
    </div></section>
  </div>
  <div class="side-column">
    {% if execution_mode|default('local') != 'render' %}
    {% if commerce %}<details class="card control-diagnostics" id="diagnostics"><summary><span><span class="kicker">DIAGNOSTICS</span><strong>Control test</strong></span><span class="muted">Optional</span></summary><div class="card-body">{% else %}<section class="card"><div class="card-header"><div><span class="kicker">TRY YOUR CONTROLS</span><h2>Control test</h2></div></div><div class="card-body">{% endif %}
    <p class="muted">Check permissions and budget limits with a fixed compute estimate. Inference tokens are zero in this test.</p>
    <p id="work-readiness" class="notice info">{{ work_guidance }}</p>
    <form id="work-form" data-instance="{{ d.snapshot.id }}" data-csrf="{{ csrf }}" class="form-grid"><div class="field"><label for="work-capability">Capability</label>
    <select id="work-capability" name="capability"{% if work_disabled %} disabled{% endif %}>{% for c, on in d.snapshot.capabilities.items() if on %}<option value="{{ c }}" data-guidance="{{ capability_guidance.get(c, '') }}">{{ c }}</option>{% else %}<option value="">No enabled capabilities</option>{% endfor %}</select></div>
    <p class="field-hint" id="capability-hint"></p>
    <div class="field" id="work-destination-field" hidden><label for="work-destination">HTTPS destination</label><input id="work-destination" name="destination_url" type="url" placeholder="https://example.com/resource" disabled></div>
    <div class="field"><label for="work-minutes">Compute minutes</label><input id="work-minutes" name="compute_minutes" type="text" inputmode="numeric" value="1" aria-describedby="work-hint"></div>
    <p class="field-hint" id="work-hint">Use a whole number of minutes. All four limits must permit the test. Only enabled capabilities are listed.</p><button class="primary" type="submit"{% if work_disabled %} disabled{% endif %}>Run control test</button></form>
    <div id="work-result" class="work-result" tabindex="-1" role="status" aria-live="polite" aria-atomic="true"></div>
    </div>{% if commerce %}</details>{% else %}</section>{% endif %}
    {% endif %}
    <section class="card section-anchor" id="tool-confirmations"><div class="card-header"><div><span class="kicker">TOOL APPROVAL</span><h2>Tool confirmations</h2></div><span class="status-badge draft">{{ d.pending_actions|length }} pending</span></div><div class="card-body">
    {% if commerce and commerce.attention_count %}<p class="field-hint"><a href="/requests?instance_id={{ d.snapshot.id }}">Review agent requests.</a></p>{% endif %}
    {% for p in d.pending_actions %}<div class="pending panel" data-pending="{{ p.id }}" data-csrf="{{ csrf }}"><h3>{{ p.capability }}</h3><div class="preview-grid">{% for k, v in p.preview.items() %}<p><span class="muted">{{ k }}</span><br>{{ v }}</p>{% endfor %}</div>
    <p class="field-hint">Confirmation permits this specific action once. Submit the same request again to execute it.</p><button type="button" class="confirm primary">Confirm</button><p role="status" aria-live="polite"></p></div>
    {% else %}<div class="empty-state"><p>No tool confirmations are waiting.</p><p class="muted">Actions that send or post require your approval before they can proceed.</p></div>{% endfor %}
    </div></section>
  </div>
</div>
<section class="card section-anchor" id="budgets"><div class="card-header"><div><span class="kicker">SPENDING BOUNDARIES</span><h2>Budget</h2></div><span class="status-badge draft">USD control limits</span></div><div class="card-body">
{% if commerce %}{% with feedback_section='budgets' %}{% include "commerce/feedback" %}{% endwith %}{% endif %}
<p class="muted">Daily and monthly limits apply together. Held amounts cover work whose outcome is still pending; settled amounts reflect recorded usage. These limits are not a cash balance.</p>
<div class="table-wrap"><table class="data-table"><caption class="field-hint">Current budget windows · all amounts in USD</caption><thead><tr><th scope="col">Category</th><th scope="col">Window</th><th scope="col">Limit</th><th scope="col">Settled</th><th scope="col">Held</th><th scope="col">Available</th></tr></thead><tbody>
{% for cat, windows in d.budget.windows.items() %}{% for w, a in windows.items() %}<tr><th scope="row">{{ cat }}</th><td>{{ 'Daily' if w == 'day' else 'Monthly' }}</td><td>{{ usd(a.limit) }}</td><td>{{ usd(a.settled) }}</td><td>{{ usd(a.held) }}</td><td><strong>{{ usd(a.available) }}</strong></td></tr>{% endfor %}{% endfor %}
</tbody></table></div>
<form method="post" action="/instances/{{ d.snapshot.id }}/limits">{{ hidden }}<h3>Adjust your limits</h3><p class="field-hint">A zero limit blocks work. Set all four limits explicitly before running your agent.</p><div class="limit-grid">
{% for name, label in limit_fields %}<div class="field"><label for="{{ name }}">{{ label }}</label><input id="{{ name }}" name="{{ name }}" type="text" inputmode="decimal" value="{{ limit_values[name] }}" aria-describedby="budget-units"></div>{% endfor %}
</div><p id="budget-units" class="field-hint">USD · up to six decimal places. Saving also re-checks a budget gate automatically.</p><button class="primary" type="submit">Save limits</button></form>
{% if commerce %}{% with detail=d, d=commerce, request_id=commerce_request_id %}{% include "commerce/budget" %}{% endwith %}{% endif %}
</div></section>
{% if commerce %}{% with detail=d, d=commerce, request_id=commerce_request_id %}
{% include "commerce/funding" %}
{% endwith %}{% endif %}
<div class="detail-grid section-anchor" id="capabilities">
  <div class="main-column">
    <section class="card"><div class="card-header"><div><span class="kicker">PERMISSIONS</span><h2>Capabilities</h2></div></div><div class="card-body"><p class="muted">Choose what this agent may request. Connected tools also need an attachment, and outbound writes require your confirmation.</p>
    <form method="post" action="/instances/{{ d.snapshot.id }}/capabilities">{{ hidden }}<div class="capability-grid">
    {% for c, on in d.snapshot.capabilities.items() %}<label class="capability-option"><input type="checkbox" name="capabilities" value="{{ c }}" aria-label="{{ c }}"{% if on %} checked{% endif %}><span class="capability-copy"><span class="capability-title">{{ c }}</span><span class="capability-description">{{ capability_copy.get(c, '') }}</span></span></label>{% endfor %}
    </div><button class="primary" type="submit">Save capabilities</button></form></div></section>
    <section class="card"><div class="card-header"><div><span class="kicker">TOOL ACCESS</span><h2>Attachments</h2></div><a class="button ghost" href="/connections">Connections</a></div><div class="card-body">
    <p class="muted">Attach an owner connection to each enabled tool capability. A connection can be shared across your agents.</p>
    {% for row in attach_rows %}<div class="attachment-row"><h3>{{ row.capability }}</h3>
    {% if row.attached %}<p>{{ row.attached.connection_display_name }} <span class="status-badge {{ row.attached.connection_status }}">{{ row.attached.connection_status }}</span></p>
    <form method="post" action="/instances/{{ d.snapshot.id }}/attachments/detach">{{ hidden }}<input type="hidden" name="capability" value="{{ row.capability }}"><button class="secondary" type="submit">Detach</button></form>
    {% elif row.options %}<form class="inline-form" method="post" action="/instances/{{ d.snapshot.id }}/attachments">{{ hidden }}<input type="hidden" name="capability" value="{{ row.capability }}"><div class="field">
    <label for="conn-{{ row.capability }}">Connection for {{ row.capability }}</label><select id="conn-{{ row.capability }}" name="connection_id">{% for c in row.options %}<option value="{{ c.id }}">{{ c.display_name }}</option>{% endfor %}</select></div><button class="secondary" type="submit">Attach</button></form>
    {% else %}<p class="muted">Not attached; no active connection is available. Open Connections to add one, then return here to attach it.</p>{% endif %}</div>
    {% else %}<div class="empty-state"><p>Enable a connection-backed capability to attach a connection.</p><p class="muted">Gmail and Reddit tools use owner-managed connections.</p></div>{% endfor %}</div></section>
  </div>
  <div class="side-column">
    <section class="card"><div class="card-header"><div><span class="kicker">NETWORK BOUNDARY</span><h2>Network domains</h2></div></div><div class="card-body"><p class="muted">Add exact HTTPS hostnames for <code>network.fetch</code>. Other destinations stay blocked. Wildcards and private addresses are not permitted.</p>
    {% if d.snapshot.network_domains %}<ul class="domain-list">{% for h in d.snapshot.network_domains %}<li><code>{{ h }}</code><form method="post" action="/instances/{{ d.snapshot.id }}/domains/remove">{{ hidden }}<input type="hidden" name="host" value="{{ h }}"><button class="ghost" type="submit">Remove domain</button></form></li>{% endfor %}</ul>
    {% else %}<p class="muted">No owner domains.</p>{% endif %}
    <form class="form-grid" method="post" action="/instances/{{ d.snapshot.id }}/domains">{{ hidden }}<div class="field"><label for="domain-host">Network.fetch domain</label><input id="domain-host" name="host" type="text" placeholder="public-host.org" autocomplete="off" autocapitalize="none"></div><button class="secondary" type="submit">Add domain</button></form></div></section>
  </div>
</div>
<div class="section-anchor" id="activity"><div class="section-heading"><div><span class="kicker">A RECORD OF WHAT HAPPENED</span><h2>Activity</h2></div><p class="muted">Usage and control decisions, without request bodies or credentials.</p></div>
<section class="card"><div class="card-header"><h3>Usage</h3></div><div class="card-body">
{% if d.usage_history %}<div class="table-wrap"><table class="data-table"><thead><tr><th scope="col">Recorded</th><th scope="col">Inference (USD)</th><th scope="col">Compute (USD)</th><th scope="col">Compute minutes</th></tr></thead><tbody>
{% for u in d.usage_history %}<tr><td><time datetime="{{ u.recorded_at.isoformat() }}">{{ u.recorded_at.strftime('%b %d, %Y · %H:%M UTC') }}</time></td><td>{{ usd(u.inference_micro_usd) }}</td><td>{{ usd(u.compute_micro_usd) }}</td><td>{{ u.compute_minutes }}</td></tr>{% endfor %}</tbody></table></div>
{% else %}<div class="empty-state"><p>No usage yet.</p><p class="muted">Completed work will appear here with its recorded cost and compute time.</p></div>{% endif %}</div></section>
<section class="card"><div class="card-header"><h3>Audit history</h3><span class="status-badge draft">Control events</span></div><div class="card-body">
{% if d.audit %}<ol class="activity-list">{% for e in d.audit %}<li class="activity-item"><span class="activity-icon" aria-hidden="true">·</span><div><code>{{ e.event_type }}</code><p class="muted">{{ e.outcome }} · {{ e.actor_kind }}{% if e.occurred_at %} · <time datetime="{{ e.occurred_at.isoformat() }}">{{ e.occurred_at.strftime('%b %d, %Y · %H:%M UTC') }}</time>{% endif %}</p></div></li>{% endfor %}</ol>{% else %}<p class="muted">No events.</p>{% endif %}</div></section></div>
</div>
<script>
(function () {
  function reloadLink(box, message) {
    var link = document.createElement("a");
    link.href = window.location.pathname + "#activity";
    link.className = "button secondary";
    link.addEventListener("click", function (ev) {
      ev.preventDefault();
      window.history.replaceState(null, "", link.href);
      window.location.reload();
    });
    link.textContent = message;
    var row = document.createElement("div");
    row.className = "button-row";
    row.appendChild(link);
    box.appendChild(row);
  }
  function bindControls() {
  {% if commerce %}{% include "commerce/script" %}{% endif %}
  document.querySelectorAll('#instance-state form[method="post"]').forEach(function (control) {
    control.addEventListener("input", function () { control.dataset.dirty = "true"; });
    control.addEventListener("change", function () { control.dataset.dirty = "true"; });
  });
  var form = document.getElementById("work-form");
  function capabilityHint() {
    var option = form.elements.capability.selectedOptions[0];
    document.getElementById("capability-hint").textContent = option ? option.dataset.guidance || "" : "";
    var network = form.elements.capability.value === "network.fetch";
    document.getElementById("work-destination-field").hidden = !network;
    form.elements.destination_url.disabled = !network;
    form.elements.destination_url.required = network;
  }
  if (form) { capabilityHint(); form.elements.capability.addEventListener("change", capabilityHint); }
  if (form) form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var button = form.querySelector("button[type=submit]");
    if (button.disabled) return;
    var result = document.getElementById("work-result");
    var raw = form.elements.compute_minutes.value.trim();
    var minutes = Number(raw);
    if (!raw || !Number.isSafeInteger(minutes) || minutes < 0) {
      result.className = "work-result notice error";
      result.textContent = "Enter a non-negative whole number of compute minutes.";
      form.elements.compute_minutes.focus();
      return;
    }
    var id = "work_" + Array.from(crypto.getRandomValues(new Uint8Array(16))).map(function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
    button.disabled = true;
    button.textContent = "Checking controls…";
    form.setAttribute("aria-busy", "true");
    result.className = "work-result notice info";
    result.textContent = "Checking permissions and budget…";
    var request = {work_id: id, capability: form.elements.capability.value, payload: {sim: {compute_minutes: minutes}},
      estimate: {inference_input_tokens: 0, inference_output_tokens: 0, compute_minutes: minutes}};
    if (request.capability === "network.fetch") request.destination_url = form.elements.destination_url.value.trim();
    Array.from(form.querySelectorAll("input, select")).forEach(function (input) { input.disabled = true; });
    fetch("/instances/" + form.dataset.instance + "/work-requests", {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": form.dataset.csrf},
      body: JSON.stringify(request)})
      .then(function (r) { return r.json().then(function (j) { return {ok: r.ok, data: j}; }); })
      .then(function (response) {
        var value = response.data.outcome || response.data.reason || response.data.error || "unknown";
        var known = (response.ok && ["succeeded", "failed"].includes(value)) ||
          (!response.ok && response.data.error === "denied" && typeof response.data.reason === "string");
        var message = "Result: " + value + ".";
        if (response.data.message) message += " " + response.data.message;
        var style = "work-result notice " + (response.ok && value === "succeeded" ? "success" : "info");
        result.className = style;
        result.textContent = message;
        if (!known) {
          result.appendChild(document.createTextNode(value === "unknown" ?
            " The outcome is still being reconciled; its budget reservation remains held." :
            " Check current activity before submitting again."));
          reloadLink(result, "Review current activity");
          return;
        }
        // Read the same authenticated projection as a normal page visit. Never replay the POST.
        return fetch(window.location.pathname, {credentials: "same-origin", cache: "no-store"})
          .then(function (r) {
            if (!r.ok || r.redirected) throw new Error("State refresh unavailable");
            return r.text();
          }).then(function (html) {
            var documentState = new DOMParser().parseFromString(html, "text/html");
            var fresh = documentState.getElementById("instance-state");
            var freshForm = fresh && fresh.querySelector("#work-form");
            if (!freshForm || freshForm.dataset.instance !== form.dataset.instance) throw new Error("Missing instance state");
            // Keep unsaved owner edits and their original version checks; a work result must not overwrite them.
            function formKey(control) {
              var capability = control.querySelector('input[type="hidden"][name="capability"]');
              return control.getAttribute("action") + "|" + (capability ? capability.value : "");
            }
            document.querySelectorAll('#instance-state form[data-dirty="true"]').forEach(function (dirty) {
              var target = Array.from(fresh.querySelectorAll('form[method="post"]')).find(function (candidate) {
                return formKey(candidate) === formKey(dirty);
              });
              if (target) target.replaceWith(dirty);
            });
            // Keep an explicitly opened diagnostic panel open so its result remains visible.
            var diagnostic = document.getElementById("diagnostics");
            var freshDiagnostic = fresh.querySelector("#diagnostics");
            if (diagnostic && freshDiagnostic) freshDiagnostic.open = diagnostic.open;
            document.getElementById("instance-state").replaceWith(fresh);
            if (Array.from(freshForm.elements.capability.options).some(function (o) { return o.value === request.capability; })) {
              freshForm.elements.capability.value = request.capability;
            }
            freshForm.elements.compute_minutes.value = raw;
            freshForm.elements.destination_url.value = request.destination_url || "";
            bindControls();
            var refreshedResult = document.getElementById("work-result");
            refreshedResult.className = style;
            refreshedResult.textContent = message + " Status, budgets, confirmations and activity are up to date.";
            refreshedResult.focus({preventScroll: true});
          }).catch(function () {
            result.className = style;
            result.textContent = message + " The page could not refresh. Review current activity before submitting again.";
            reloadLink(result, "Review current activity");
          });
      })
      .catch(function () {
        result.className = "work-result notice error";
        result.textContent = "The request result could not be verified. It may have been processed. Check activity before submitting again.";
        reloadLink(result, "Review current activity");
      })
      .finally(function () {
        button.textContent = "Run control test";
        form.removeAttribute("aria-busy");
      });
  });
  document.querySelectorAll(".pending").forEach(function (box) {
    var button = box.querySelector(".confirm");
    button.addEventListener("click", function () {
      if (button.disabled) return;
      var result = box.querySelector("[role=status]");
      button.disabled = true;
      button.textContent = "Confirming…";
      box.setAttribute("aria-busy", "true");
      result.textContent = "Saving your confirmation…";
      fetch("/pending-actions/" + box.dataset.pending + "/confirm", {method: "POST", credentials: "same-origin",
        headers: {"X-CSRF-Token": box.dataset.csrf}}).then(function (r) {
        if (r.ok) {
          result.textContent = "Confirmed once; send it again to execute.";
          button.textContent = "Confirmed";
        } else {
          result.textContent = "Not confirmed. Reload to check the current action before trying again.";
          button.textContent = "Confirm";
          reloadLink(result, "Reload confirmations.");
        }
      }).catch(function () {
        result.textContent = "The confirmation result could not be verified. Reload to check before trying again.";
        button.textContent = "Confirm";
        reloadLink(result, "Reload confirmations.");
      }).finally(function () { box.removeAttribute("aria-busy"); });
    });
  });
  }
  bindControls();
})();
</script>{% endblock %}""",
    "connections": """{% extends "base" %}{% set page_key = "connections" %}
{% block eyebrow %}CONNECTED TOOLS{% endblock %}
{% block subtitle %}Your accounts. Your permissions. One place to manage access.{% endblock %}
{% block header_actions %}<a class="button secondary" href="/workspace">Back to workspace</a>{% endblock %}
{% block body %}
{% if notice %}<div class="notice {% if notice == 'The connection was not authorized.' %}error{% else %}success{% endif %}" role="status">{{ notice }}</div>{% endif %}

<div class="section-heading"><div><span class="kicker">AVAILABLE CONNECTIONS</span><h2>Add a connection</h2></div><p class="muted">Connect an account, then attach it to an agent's enabled capability.</p></div>
<div class="connection-grid">
  <section class="connection-card card"><div class="card-body"><span class="provider-icon" aria-hidden="true">G</span><h3>Gmail</h3><p class="muted">Read and send with an owner-managed connection. Each send requires your confirmation.</p><p class="field-hint">Capabilities: <code>gmail.read</code>, <code>gmail.send</code></p>
  <button type="button" class="connect primary" data-provider="gmail" data-capabilities="gmail.read,gmail.send" data-csrf="{{ csrf }}">Connect Gmail</button></div></section>
  <section class="connection-card card"><div class="card-body"><span class="provider-icon" aria-hidden="true">r</span><h3>Reddit</h3><p class="muted">Read and post with an owner-managed connection. Each post requires your confirmation.</p><p class="field-hint">Capabilities: <code>reddit.read</code>, <code>reddit.post</code></p>
  <button type="button" class="connect primary" data-provider="reddit" data-capabilities="reddit.read,reddit.post" data-csrf="{{ csrf }}">Connect Reddit</button></div></section>
</div><div id="connect-result" role="status" aria-live="polite" aria-atomic="true"></div>
<div class="section-heading"><div><span class="kicker">ACCOUNT ACCESS</span><h2>Your connections</h2></div><p class="muted">Revoking a connection detaches it from every agent that uses it; it does not undo actions already taken.</p></div>
{% if view.connections %}<div class="connection-grid">{% for c in view.connections %}<section class="card connection-card"><div class="card-header"><div><span class="kicker">{{ c.provider }}</span><h3>{{ c.display_name }}</h3></div><span class="status-badge {% if c.status == 'active' %}active{% elif c.status == 'revoked' %}archived{% else %}gated{% endif %}">{{ c.status|replace('_', ' ') }}</span></div><div class="card-body">
{% if c.status == "revoked" and c.provider_revoke_status == "failed" %}<p class="notice error">The provider could not be reached: remove access in the provider's own account settings.</p>{% endif %}
{% set attachments = view.attachments|selectattr('connection_id', 'equalto', c.id)|list %}
{% if attachments %}<h4>Used by your agents</h4>{% for a in attachments %}<p class="attachment-row">Attached to <a href="/instances/{{ a.instance_id }}">{{ a.instance_name }}</a> for <code>{{ a.capability }}</code></p>{% endfor %}
{% elif c.status == 'revoked' %}<p class="muted">Access has been removed. This connection is no longer attached to an agent.</p>
{% elif c.status == 'active' %}<p class="muted">Ready to attach. Open an agent's controls to choose which capability may use this connection.</p>
{% else %}<p class="muted">This connection needs authorization again before it can be used.</p>{% endif %}
{% if c.status != "revoked" %}<form method="post" action="/connections/{{ c.id }}/revoke">{{ hidden }}<button class="danger" type="submit">Revoke</button></form>{% endif %}</div></section>{% endfor %}</div>
{% else %}<div class="card empty-state"><h3>No connections yet.</h3><p class="muted">Start with Gmail or Reddit above. Your agent receives only the access you explicitly attach.</p></div>{% endif %}
<script>
(function () {
  var buttons = document.querySelectorAll(".connect");
  var starting = false;
  buttons.forEach(function (button) {
    button.addEventListener("click", function () {
      if (starting) return;
      starting = true;
      buttons.forEach(function (b) { b.disabled = true; });
      var label = button.textContent;
      var result = document.getElementById("connect-result");
      button.textContent = "Connecting…";
      result.className = "notice info";
      result.textContent = "Opening authorization…";
      fetch("/connections/oauth/begin", {method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": button.dataset.csrf},
        body: JSON.stringify({provider: button.dataset.provider, capabilities: button.dataset.capabilities.split(",")})})
        .then(function (r) { return r.json().then(function (j) { return {ok: r.ok, data: j}; }); })
        .then(function (response) {
          if (response.ok && response.data.authorization_url) {
            window.location.assign(response.data.authorization_url);
          } else {
            result.className = "notice error";
            result.textContent = "Could not start the connection. " + (response.data.message || "Please reload and try again.");
            starting = false;
            buttons.forEach(function (b) { b.disabled = false; });
            button.textContent = label;
          }
        }).catch(function () {
          result.className = "notice error";
          result.textContent = "The connection could not be verified. Reload this page to check its status before trying again.";
          var link = document.createElement("a");
          link.href = "/connections";
          link.textContent = " Reload connections.";
          result.appendChild(link);
          button.textContent = label;
        });
    });
  });
})();
</script>{% endblock %}""",
}

ENV = Environment(loader=DictLoader({**BASE_TEMPLATES, **COMMERCE_TEMPLATES, **TEMPLATES}), autoescape=True)
ENV.globals.update(money=money, credit=credit, license_label=license_label, result_text=result_text,
                   run_label=run_label, readiness_destination=readiness_destination)


def render(template: str, /, **context: object) -> str:
    context.setdefault("capability_copy", CAPABILITY_COPY)
    return ENV.get_template(template).render(**context)
