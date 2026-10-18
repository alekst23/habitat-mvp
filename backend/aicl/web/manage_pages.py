"""Jinja2 templates (autoescaped, no |safe) for the owner pages: instance detail and Connections (E11-5)."""

from __future__ import annotations

from jinja2 import DictLoader, Environment

from aicl.web.pages import TEMPLATES as BASE_TEMPLATES

NOTICES = {"saved": "Saved.", "cleared": "Gate cleared.", "revoked": "Connection revoked.",
           "connected": "Connected.", "denied": "The connection was not authorized."}

TEMPLATES = {
    "instance": """{% extends "base" %}{% block body %}
<p><a href="/workspace">Back to workspace</a> <a href="/connections">Connections</a></p>
{% if notice %}<p role="status">{{ notice }}</p>{% endif %}
{% if error %}<div role="alert"><p>{{ error.error }}{% if error.reason %}: {{ error.reason }}{% endif %}</p>
<p>{{ error.message }}</p>{% if error.current_version %}<p>Current version: {{ error.current_version }}. Reload and retry.</p>{% endif %}
{% if error.field_errors %}<ul>{% for e in error.field_errors %}<li>{{ e.field }}: {{ e.code }}</li>{% endfor %}</ul>{% endif %}</div>{% endif %}
<section aria-label="Agent"><h2>Agent</h2>
<p>Name: {{ d.snapshot.name }}</p><p>Lifecycle: {{ d.snapshot.lifecycle }}</p><p>Status: {{ d.snapshot.status }}</p>
<p>Instructions: <span style="white-space: pre-wrap">{{ d.snapshot.instructions }}</span></p>
{% if d.snapshot.gated_reason %}<p role="status">Gated: <code>{{ d.snapshot.gated_reason }}</code></p>
<form method="post" action="/instances/{{ d.snapshot.id }}/resolve-gate">{{ hidden }}
<button type="submit">Re-check and clear</button></form>{% endif %}
<p>Gated reasons stay until you fix the control and the system re-checks it as permitting work.</p>
<form method="post" action="/instances/{{ d.snapshot.id }}/lifecycle">{{ hidden }}
{% for action, label in actions %}<button type="submit" name="action" value="{{ action }}">{{ label }}</button> {% endfor %}</form></section>
<p>Real provider adapters are not enabled: connections and work in this product are simulated. Revoking a connection detaches it and gates the agents that used it; revocation does not undo actions already taken.</p>
<section aria-label="Budget"><h2>Budget</h2><table><thead><tr><th>Category</th><th>Window</th><th>Limit</th><th>Settled</th><th>Held</th><th>Available</th></tr></thead><tbody>
{% for cat, windows in d.budget.windows.items() %}{% for w, a in windows.items() %}<tr><td>{{ cat }}</td><td>{{ w }}</td><td>{{ usd(a.limit) }}</td><td>{{ usd(a.settled) }}</td><td>{{ usd(a.held) }}</td><td>{{ usd(a.available) }}</td></tr>{% endfor %}{% endfor %}
</tbody></table>
<form method="post" action="/instances/{{ d.snapshot.id }}/limits">{{ hidden }}
{% for name, label in limit_fields %}<p><label for="{{ name }}">{{ label }}</label> <input id="{{ name }}" name="{{ name }}" type="text" inputmode="decimal" value="{{ limit_values[name] }}"> USD</p>{% endfor %}
<button type="submit">Save limits</button></form></section>
<section aria-label="Capabilities"><h2>Capabilities</h2>
<form method="post" action="/instances/{{ d.snapshot.id }}/capabilities">{{ hidden }}
{% for c, on in d.snapshot.capabilities.items() %}<p><label><input type="checkbox" name="capabilities" value="{{ c }}"{% if on %} checked{% endif %}>{{ c }}</label></p>{% endfor %}
<button type="submit">Save capabilities</button></form></section>
<section aria-label="Connections"><h2>Attachments</h2>
{% for row in attach_rows %}<div><p>{{ row.capability }}:
{% if row.attached %}{{ row.attached.connection_display_name }} ({{ row.attached.connection_status }})</p>
<form method="post" action="/instances/{{ d.snapshot.id }}/attachments/detach">{{ hidden }}<input type="hidden" name="capability" value="{{ row.capability }}"><button type="submit">Detach</button></form>
{% elif row.options %}</p><form method="post" action="/instances/{{ d.snapshot.id }}/attachments">{{ hidden }}<input type="hidden" name="capability" value="{{ row.capability }}">
<label for="conn-{{ row.capability }}">Connection for {{ row.capability }}</label>
<select id="conn-{{ row.capability }}" name="connection_id">{% for c in row.options %}<option value="{{ c.id }}">{{ c.display_name }}</option>{% endfor %}</select>
<button type="submit">Attach</button></form>
{% else %}not attached; no active connection is available (see Connections).</p>{% endif %}</div>{% else %}<p>Enable a connection-backed capability to attach a connection.</p>{% endfor %}</section>
<section aria-label="Network domains"><h2>Network domains</h2>
{% if d.snapshot.network_domains %}<ul>{% for h in d.snapshot.network_domains %}<li>{{ h }}
<form method="post" action="/instances/{{ d.snapshot.id }}/domains/remove" style="display:inline">{{ hidden }}<input type="hidden" name="host" value="{{ h }}"><button type="submit">Remove domain</button></form></li>{% endfor %}</ul>
{% else %}<p>No owner domains.</p>{% endif %}
<form method="post" action="/instances/{{ d.snapshot.id }}/domains">{{ hidden }}<label for="domain-host">Network.fetch domain</label> <input id="domain-host" name="host" type="text">
<button type="submit">Add domain</button></form></section>
<section aria-label="Simulated work"><h2>Simulated work request</h2>
<p>Simulated: no real provider call is made.</p>
<form id="work-form" data-instance="{{ d.snapshot.id }}" data-csrf="{{ csrf }}"><label for="work-capability">Capability</label>
<select id="work-capability" name="capability">{% for c in d.snapshot.capabilities %}<option>{{ c }}</option>{% endfor %}</select>
<label for="work-minutes">Compute minutes</label> <input id="work-minutes" name="compute_minutes" type="text" inputmode="numeric" value="1">
<button type="submit">Run simulated work</button></form><p id="work-result" role="status"></p></section>
<section aria-label="Pending confirmations"><h2>Confirmations</h2>
{% for p in d.pending_actions %}<div class="pending" data-pending="{{ p.id }}" data-csrf="{{ csrf }}"><p>{{ p.capability }}{% for k, v in p.preview.items() %} {{ k }}={{ v }}{% endfor %}</p>
<button type="button" class="confirm">Confirm</button> <span role="status"></span></div>{% else %}<p>Nothing is waiting for confirmation.</p>{% endfor %}</section>
<section aria-label="Usage"><h2>Usage (simulated work)</h2>
{% if d.usage_history %}<table><thead><tr><th>Recorded</th><th>Inference</th><th>Compute</th><th>Compute minutes</th></tr></thead><tbody>
{% for u in d.usage_history %}<tr><td>{{ u.recorded_at.isoformat() }}</td><td>{{ usd(u.inference_micro_usd) }}</td><td>{{ usd(u.compute_micro_usd) }}</td><td>{{ u.compute_minutes }}</td></tr>{% endfor %}</tbody></table>
{% else %}<p>No usage yet.</p>{% endif %}</section>
<section aria-label="Audit"><h2>Audit history</h2>
{% if d.audit %}<ol>{% for e in d.audit %}<li>{{ e.event_type }} ({{ e.outcome }}, {{ e.actor_kind }})</li>{% endfor %}</ol>{% else %}<p>No events.</p>{% endif %}</section>
<script>
(function () {
  var form = document.getElementById("work-form");
  if (form) form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var minutes = parseInt(form.compute_minutes.value, 10) || 0;
    var id = "work_" + Array.from(crypto.getRandomValues(new Uint8Array(16))).map(function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
    fetch("/instances/" + form.dataset.instance + "/work-requests", {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": form.dataset.csrf},
      body: JSON.stringify({work_id: id, capability: form.capability.value, payload: {sim: {compute_minutes: minutes}},
        estimate: {inference_input_tokens: 0, inference_output_tokens: 0, compute_minutes: minutes}})})
      .then(function (r) { return r.json().then(function (j) { return [r.status, j]; }); })
      .then(function (x) { document.getElementById("work-result").textContent = "Result: " + (x[1].outcome || x[1].reason || x[1].error) + ". Reload to see usage."; });
  });
  document.querySelectorAll(".pending").forEach(function (box) {
    box.querySelector(".confirm").addEventListener("click", function () {
      fetch("/pending-actions/" + box.dataset.pending + "/confirm", {method: "POST", credentials: "same-origin",
        headers: {"X-CSRF-Token": box.dataset.csrf}}).then(function (r) {
        box.querySelector("[role=status]").textContent = r.ok ? "Confirmed once; send it again to execute." : "Not confirmed.";
      });
    });
  });
})();
</script>{% endblock %}""",
    "connections": """{% extends "base" %}{% block body %}
<p><a href="/workspace">Back to workspace</a></p>
{% if notice %}<p role="status">{{ notice }}</p>{% endif %}
<p>Real provider adapters are not enabled: connecting uses a simulated provider page. Revocation does not undo actions already taken.</p>
<p><button type="button" class="connect" data-provider="gmail" data-capabilities="gmail.read,gmail.send" data-csrf="{{ csrf }}">Connect Gmail</button>
<button type="button" class="connect" data-provider="reddit" data-capabilities="reddit.read,reddit.post" data-csrf="{{ csrf }}">Connect Reddit</button> <span id="connect-result" role="status"></span></p>
{% if view.connections %}<ul>{% for c in view.connections %}<li>{{ c.display_name }} ({{ c.provider }}): {{ c.status }}
{% if c.status == "revoked" and c.provider_revoke_status == "failed" %}The provider could not be reached: remove access in the provider's own account settings.{% endif %}
{% for a in view.attachments if a.connection_id == c.id %}<br>Attached to <a href="/instances/{{ a.instance_id }}">{{ a.instance_name }}</a> for {{ a.capability }}{% endfor %}
{% if c.status != "revoked" %}<form method="post" action="/connections/{{ c.id }}/revoke">{{ hidden }}<button type="submit">Revoke</button></form>{% endif %}</li>{% endfor %}</ul>
{% else %}<p>No connections yet.</p>{% endif %}
<script>
document.querySelectorAll(".connect").forEach(function (b) {
  b.addEventListener("click", function () {
    fetch("/connections/oauth/begin", {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": b.dataset.csrf},
      body: JSON.stringify({provider: b.dataset.provider, capabilities: b.dataset.capabilities.split(",")})})
      .then(function (r) { return r.json(); })
      .then(function (j) { if (j.authorization_url) { window.location.assign(j.authorization_url); }
        else { document.getElementById("connect-result").textContent = "Could not start the connection."; } });
  });
});
</script>{% endblock %}""",
}

ENV = Environment(loader=DictLoader({**BASE_TEMPLATES, **TEMPLATES}), autoescape=True)


def render(template: str, /, **context: object) -> str:
    return ENV.get_template(template).render(**context)
