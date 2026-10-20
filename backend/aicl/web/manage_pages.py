"""Autoescaped owner pages for instance controls and simulated connections (E11-5)."""

from __future__ import annotations

from jinja2 import DictLoader, Environment

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
{% block eyebrow %}AGENT CONTROL ROOM{% endblock %}
{% block subtitle %}Set the boundaries. Review the activity. Stay in control.{% endblock %}
{% block header_actions %}<a class="button secondary" href="/workspace">Back to workspace</a>{% endblock %}
{% block body %}
{% if notice %}<div class="notice success" role="status">{{ notice }}</div>{% endif %}
{% if error %}<div class="notice error" role="alert"><strong>{{ error.error }}{% if error.reason %}: {{ error.reason }}{% endif %}</strong>
<p>{{ error.message }}</p>{% if error.current_version %}<p>Current version: {{ error.current_version }}. Reload and retry.</p>{% endif %}
{% if error.field_errors %}<ul>{% for e in error.field_errors %}<li>{{ e.field }}: {{ e.code }}</li>{% endfor %}</ul>{% endif %}</div>{% endif %}
<div class="stat-grid">
  <div class="stat-card"><span class="stat-label">Current status</span><span class="stat-value"><span class="status-badge {{ d.snapshot.status }}">{{ d.snapshot.status }}</span></span><span class="stat-note">Lifecycle: {{ d.snapshot.lifecycle }}</span></div>
  <div class="stat-card"><span class="stat-label">Inference · daily available</span><span class="stat-value">${{ usd(d.budget.windows.inference.day.available) }}</span><span class="stat-note">Of ${{ usd(d.budget.windows.inference.day.limit) }} daily limit</span></div>
  <div class="stat-card"><span class="stat-label">Compute · daily available</span><span class="stat-value">${{ usd(d.budget.windows.compute.day.available) }}</span><span class="stat-note">Of ${{ usd(d.budget.windows.compute.day.limit) }} daily limit</span></div>
  <div class="stat-card"><span class="stat-label">Enabled capabilities</span><span class="stat-value">{{ d.snapshot.capabilities.values()|select|list|length }} <small>/ {{ d.snapshot.capabilities|length }}</small></span><span class="stat-note">Only the permissions you choose</span></div>
</div>
<nav class="button-row section-anchor" aria-label="Agent sections"><a class="button ghost" href="#overview">Overview</a><a class="button ghost" href="#budgets">Budgets</a><a class="button ghost" href="#capabilities">Capabilities</a><a class="button ghost" href="#activity">Activity</a></nav>
<div class="notice info"><strong>Simulated environment</strong><p>Real provider adapters are not enabled: connections and work in this product are simulated. Revoking a connection detaches it and gates the agents that used it; revocation does not undo actions already taken.</p></div>
<div class="detail-grid" id="overview">
  <div class="main-column">
    <section class="card"><div class="card-header"><div><span class="kicker">YOUR AGENT</span><h2>Purpose &amp; controls</h2></div><span class="status-badge {{ d.snapshot.status }}">{{ d.snapshot.status }}</span></div>
    <div class="card-body"><h3>Instructions</h3>{% if d.snapshot.instructions %}<p style="white-space: pre-wrap">{{ d.snapshot.instructions }}</p>{% else %}<p class="muted">No instructions have been added to this agent.</p>{% endif %}
    {% if d.snapshot.gated_reason %}<div class="notice error" role="status"><strong>Work is gated</strong><p>Gated: <code>{{ d.snapshot.gated_reason }}</code></p><p>Fix the relevant control below, then re-check it before running work.</p></div>
    {% elif d.snapshot.status == "gated" %}<div class="notice info" role="status"><strong>Work is gated while an outstanding request is reconciled.</strong><p>Its reservation remains held until the outcome is known.</p></div>{% endif %}
    {% if d.snapshot.lifecycle == "draft" %}<p class="muted">This agent is a draft. Set its budgets and permissions, then activate it when you are ready.</p>
    {% elif d.snapshot.lifecycle == "paused" %}<p class="muted">You paused this agent. Resume it to allow new work, subject to its budgets and permissions.</p>
    {% elif d.snapshot.lifecycle == "archived" %}<p class="muted">This agent is archived. It cannot run again; its history remains available.</p>
    {% else %}<p class="muted">This agent is active. Every request must still pass its budget, capability and connection checks.</p>{% endif %}
    {% if actions %}<form method="post" action="/instances/{{ d.snapshot.id }}/lifecycle" class="button-row">{{ hidden }}
    {% for action, label in actions %}<button class="{% if action == 'archive' %}danger{% elif action == 'pause' %}secondary{% else %}primary{% endif %}" type="submit" name="action" value="{{ action }}">{{ label }}</button>{% endfor %}</form>
    <p class="field-hint">Pause is reversible. Archive permanently stops this agent.</p>{% endif %}
    <div class="panel"><form method="post" action="/instances/{{ d.snapshot.id }}/resolve-gate">{{ hidden }}<button class="secondary" type="submit">Re-check and clear</button></form><p class="field-hint">Gated reasons stay until you fix the control and the system re-checks it as permitting work.</p></div>
    </div></section>
  </div>
  <div class="side-column">
    <section class="card"><div class="card-header"><div><span class="kicker">TRY YOUR CONTROLS</span><h2>Simulated work request</h2></div></div><div class="card-body">
    <p class="muted">Simulated: no real provider call is made. Submit a request to see how your controls respond.</p>
    <form id="work-form" data-instance="{{ d.snapshot.id }}" data-csrf="{{ csrf }}" class="form-grid"><div class="field"><label for="work-capability">Capability</label>
    <select id="work-capability" name="capability">{% for c in d.snapshot.capabilities %}<option>{{ c }}</option>{% endfor %}</select></div>
    <div class="field"><label for="work-minutes">Compute minutes</label><input id="work-minutes" name="compute_minutes" type="text" inputmode="numeric" value="1" aria-describedby="work-hint"></div>
    <p class="field-hint" id="work-hint">Use a whole number of minutes. Inference and compute limits must both permit the request.</p><button class="primary" type="submit">Run simulated work</button></form>
    <div id="work-result" class="work-result" role="status" aria-live="polite" aria-atomic="true"></div>
    </div></section>
    <section class="card"><div class="card-header"><div><span class="kicker">OWNER APPROVAL</span><h2>Confirmations</h2></div><span class="status-badge draft">{{ d.pending_actions|length }} pending</span></div><div class="card-body">
    {% for p in d.pending_actions %}<div class="pending panel" data-pending="{{ p.id }}" data-csrf="{{ csrf }}"><h3>{{ p.capability }}</h3><div class="preview-grid">{% for k, v in p.preview.items() %}<p><span class="muted">{{ k }}</span><br>{{ v }}</p>{% endfor %}</div>
    <p class="field-hint">Confirmation permits this specific action once. Submit the same request again to execute it.</p><button type="button" class="confirm primary">Confirm</button><p role="status" aria-live="polite"></p></div>
    {% else %}<div class="empty-state"><p>Nothing is waiting for confirmation.</p><p class="muted">Actions that send or post require your approval before they can proceed.</p></div>{% endfor %}
    </div></section>
  </div>
</div>
<section class="card section-anchor" id="budgets"><div class="card-header"><div><span class="kicker">SPENDING BOUNDARIES</span><h2>Budget</h2></div><span class="status-badge draft">USD control limits</span></div><div class="card-body">
<p class="muted">Daily and monthly limits apply together. Held amounts cover work whose outcome is still pending; settled amounts reflect recorded usage. These limits are not a cash balance.</p>
<div class="table-wrap"><table class="data-table"><caption class="field-hint">Current budget windows · all amounts in USD</caption><thead><tr><th scope="col">Category</th><th scope="col">Window</th><th scope="col">Limit</th><th scope="col">Settled</th><th scope="col">Held</th><th scope="col">Available</th></tr></thead><tbody>
{% for cat, windows in d.budget.windows.items() %}{% for w, a in windows.items() %}<tr><th scope="row">{{ cat }}</th><td>{{ 'Daily' if w == 'day' else 'Monthly' }}</td><td>{{ usd(a.limit) }}</td><td>{{ usd(a.settled) }}</td><td>{{ usd(a.held) }}</td><td><strong>{{ usd(a.available) }}</strong></td></tr>{% endfor %}{% endfor %}
</tbody></table></div>
<form method="post" action="/instances/{{ d.snapshot.id }}/limits">{{ hidden }}<h3>Adjust your limits</h3><p class="field-hint">A zero limit blocks work. Set all four limits explicitly before running your agent.</p><div class="limit-grid">
{% for name, label in limit_fields %}<div class="field"><label for="{{ name }}">{{ label }}</label><input id="{{ name }}" name="{{ name }}" type="text" inputmode="decimal" value="{{ limit_values[name] }}" aria-describedby="budget-units"></div>{% endfor %}
</div><p id="budget-units" class="field-hint">USD · up to six decimal places</p><button class="primary" type="submit">Save limits</button></form>
</div></section>
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
<section class="card"><div class="card-header"><h3>Usage (simulated work)</h3></div><div class="card-body">
{% if d.usage_history %}<div class="table-wrap"><table class="data-table"><thead><tr><th scope="col">Recorded</th><th scope="col">Inference (USD)</th><th scope="col">Compute (USD)</th><th scope="col">Compute minutes</th></tr></thead><tbody>
{% for u in d.usage_history %}<tr><td><time datetime="{{ u.recorded_at.isoformat() }}">{{ u.recorded_at.strftime('%b %d, %Y · %H:%M UTC') }}</time></td><td>{{ usd(u.inference_micro_usd) }}</td><td>{{ usd(u.compute_micro_usd) }}</td><td>{{ u.compute_minutes }}</td></tr>{% endfor %}</tbody></table></div>
{% else %}<div class="empty-state"><p>No usage yet.</p><p class="muted">Completed simulated work will appear here with its recorded cost and compute time.</p></div>{% endif %}</div></section>
<section class="card"><div class="card-header"><h3>Audit history</h3><span class="status-badge draft">Control events</span></div><div class="card-body">
{% if d.audit %}<ol class="activity-list">{% for e in d.audit %}<li class="activity-item"><span class="activity-icon" aria-hidden="true">·</span><div><code>{{ e.event_type }}</code><p class="muted">{{ e.outcome }} · {{ e.actor_kind }}{% if e.occurred_at %} · <time datetime="{{ e.occurred_at.isoformat() }}">{{ e.occurred_at.strftime('%b %d, %Y · %H:%M UTC') }}</time>{% endif %}</p></div></li>{% endfor %}</ol>{% else %}<p class="muted">No events.</p>{% endif %}</div></section></div>
<script>
(function () {
  function reloadLink(box, message) {
    var link = document.createElement("a");
    link.href = window.location.pathname;
    link.textContent = message;
    box.appendChild(document.createTextNode(" "));
    box.appendChild(link);
  }
  var form = document.getElementById("work-form");
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
    result.textContent = "Checking permissions and budget, then running simulated work…";
    fetch("/instances/" + form.dataset.instance + "/work-requests", {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": form.dataset.csrf},
      body: JSON.stringify({work_id: id, capability: form.elements.capability.value, payload: {sim: {compute_minutes: minutes}},
        estimate: {inference_input_tokens: 0, inference_output_tokens: 0, compute_minutes: minutes}})})
      .then(function (r) { return r.json().then(function (j) { return {ok: r.ok, data: j}; }); })
      .then(function (response) {
        var value = response.data.outcome || response.data.reason || response.data.error || "unknown";
        result.className = "work-result notice " + (response.ok && value === "succeeded" ? "success" : "info");
        result.textContent = "Result: " + value + ".";
        if (response.data.message) result.appendChild(document.createTextNode(" " + response.data.message));
        if (value === "unknown") result.appendChild(document.createTextNode(" The outcome is still being reconciled; its budget reservation remains held."));
        reloadLink(result, "Reload to see usage, gates and confirmations.");
        button.disabled = value === "unknown";
      })
      .catch(function () {
        result.className = "work-result notice error";
        result.textContent = "The request result could not be verified. It may have been processed. Check activity before submitting again.";
        reloadLink(result, "Reload and check activity.");
      })
      .finally(function () {
        button.textContent = "Run simulated work";
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
})();
</script>{% endblock %}""",
    "connections": """{% extends "base" %}{% set page_key = "connections" %}
{% block eyebrow %}CONNECTED TOOLS{% endblock %}
{% block subtitle %}Your accounts. Your permissions. One place to manage access.{% endblock %}
{% block header_actions %}<a class="button secondary" href="/workspace">Back to workspace</a>{% endblock %}
{% block body %}
{% if notice %}<div class="notice {% if notice == 'The connection was not authorized.' %}error{% else %}success{% endif %}" role="status">{{ notice }}</div>{% endif %}
<div class="notice info"><strong>Simulated connections</strong><p>Real provider adapters are not enabled: connecting uses a simulated provider page. Revocation does not undo actions already taken.</p></div>
<div class="section-heading"><div><span class="kicker">AVAILABLE IN THIS PROTOTYPE</span><h2>Add a connection</h2></div><p class="muted">Connect an account, then attach it to an agent's enabled capability.</p></div>
<div class="connection-grid">
  <section class="connection-card card"><div class="card-body"><span class="provider-icon" aria-hidden="true">G</span><h3>Gmail</h3><p class="muted">Read and send with an owner-managed connection. Each send requires your confirmation.</p><p class="field-hint">Capabilities: <code>gmail.read</code>, <code>gmail.send</code></p>
  <button type="button" class="connect primary" data-provider="gmail" data-capabilities="gmail.read,gmail.send" data-csrf="{{ csrf }}">Connect Gmail</button></div></section>
  <section class="connection-card card"><div class="card-body"><span class="provider-icon" aria-hidden="true">r</span><h3>Reddit</h3><p class="muted">Read and post with an owner-managed connection. Each post requires your confirmation.</p><p class="field-hint">Capabilities: <code>reddit.read</code>, <code>reddit.post</code></p>
  <button type="button" class="connect primary" data-provider="reddit" data-capabilities="reddit.read,reddit.post" data-csrf="{{ csrf }}">Connect Reddit</button></div></section>
</div><div id="connect-result" role="status" aria-live="polite" aria-atomic="true"></div>
<div class="section-heading"><div><span class="kicker">ACCOUNT ACCESS</span><h2>Your connections</h2></div><p class="muted">Revoking a connection detaches it from every agent that uses it.</p></div>
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
      result.textContent = "Opening the simulated authorization flow…";
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

ENV = Environment(loader=DictLoader({**BASE_TEMPLATES, **TEMPLATES}), autoescape=True)


def render(template: str, /, **context: object) -> str:
    context.setdefault("capability_copy", CAPABILITY_COPY)
    return ENV.get_template(template).render(**context)
