"""Escaped, progressive-enhancement UI for the owner assistant.

The page displays saved proposals; only the explicit confirmation form can apply
one. Model text is plain text, and navigation comes from structured references.
"""

from __future__ import annotations

from uuid import UUID

from jinja2 import DictLoader, Environment

from aicl.web.pages import TEMPLATES as BASE_TEMPLATES
from aicl.workflow.agent_tools import TOOL_CATALOG


TEMPLATE = """{% extends 'base' %}{% set page_key = 'assistant' %}
{% block eyebrow %}Habitat assistant{% endblock %}
{% block subtitle %}Turn an outcome into an agent, or check on work already underway.{% endblock %}
{% block header_actions %}<a class="button ghost" href="/chat?new=1">New conversation</a><a class="button ghost" href="/workspace">Back to workspace</a>{% endblock %}
{% block body %}
<link rel="stylesheet" href="/static/assistant.css">
<div class="owner-assistant" data-owner-assistant>
{% if notice %}<p class="notice success assistant-alert" role="status">{{ notice }}</p>{% endif %}
{% if error %}<p class="notice error assistant-alert" role="alert">{{ error }}</p>{% endif %}
<div class="assistant-layout">
<section class="card assistant-conversation" aria-labelledby="assistant-conversation-title">
  <div class="assistant-panel-heading"><div><h2 id="assistant-conversation-title">Let’s work it out together.</h2><p>Tell me the result you want. I’ll help shape the work.</p></div><span class="assistant-presence" aria-label="AI assistant">H</span></div>
  <div class="assistant-transcript" data-assistant-transcript>
  {% if messages %}<ol class="assistant-messages" aria-label="Conversation">{% for message in messages %}
    <li class="assistant-message {{ 'from-owner' if message.role == 'user' else 'from-assistant' }}">
      <p class="assistant-message-label">{{ 'You' if message.role == 'user' else 'Habitat' }}</p>
      {% if message.activities %}<ul class="assistant-activities" aria-label="Assistant activity">{% for activity in message.activities %}<li><span aria-hidden="true">·</span> {{ activity }}</li>{% endfor %}</ul>{% endif %}
      <div class="assistant-message-text">{{ message.text }}</div>
      {% if message.links %}<div class="assistant-reference-links" aria-label="Related work">{% for link in message.links %}<a href="{{ link.href }}">{{ link.label }} <span aria-hidden="true">↗</span></a>{% endfor %}</div>{% endif %}
    </li>
  {% endfor %}</ol>
  {% else %}<div class="assistant-welcome"><p class="assistant-welcome-mark" aria-hidden="true">↗</p><h3>Start with what success looks like.</h3><p>You don’t need an agent specification. Describe the outcome you need, and we’ll shape useful deliverables and choose the tools to support them.</p><div class="assistant-examples" aria-label="Conversation starters"><button type="button" class="secondary" data-assistant-example="Help me turn a recurring task into an agent with clear deliverables and the right tools">Plan an agent <span aria-hidden="true">↗</span></button><button type="button" class="secondary" data-assistant-example="Which agents need attention?">Which agents need attention? <span aria-hidden="true">↗</span></button></div></div>{% endif %}
  <div id="assistant-latest" aria-hidden="true"></div>
  </div>
  <form class="assistant-composer" method="post" action="/chat/messages" data-assistant-submit="message">
    <input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="chat_session_id" value="{{ session_id }}"><input type="hidden" name="request_id" value="{{ request_id }}">
    <label for="assistant-message">{{ 'Continue the conversation' if messages else 'What would you like to achieve?' }}</label>
    <textarea id="assistant-message" name="text" rows="3" maxlength="4000" required placeholder="Describe the result you want, who it is for, and any constraints the agent should follow." aria-describedby="assistant-composer-hint"></textarea>
    <div class="assistant-composer-actions"><span id="assistant-composer-hint" class="field-hint">Ask a question or describe a change to the proposal.</span><button class="primary" type="submit">Send <span aria-hidden="true">↑</span></button></div>
    {% if usage.unknown|default(false) %}<p class="field-hint assistant-allowance-held" role="status">A previous response is unresolved. Its allowance remains reserved; new assistant requests must wait.</p>{% endif %}
    <p class="assistant-request-status field-hint" role="status" aria-live="polite" data-assistant-request-status></p>
  </form>
</section>
<aside class="assistant-preview" aria-labelledby="assistant-preview-title">
<section class="card">
  <div class="assistant-panel-heading"><div><p class="kicker">{{ 'SCHEDULE CHANGE' if proposal and proposal.kind == 'schedule' else 'YOUR PROPOSAL' }}</p><h2 id="assistant-preview-title">{{ 'Confirmed' if proposal and proposal.state == 'committed' else 'Review before applying' if proposal else 'A plan takes shape here.' }}</h2></div>{% if proposal %}<span class="status-badge {{ 'active' if proposal.state == 'committed' else 'draft' }}">{{ 'Confirmed' if proposal.state == 'committed' else 'Draft' }}</span>{% endif %}</div>
  <div class="assistant-preview-body">
  {% if proposal %}{% set data = proposal.data %}
    {% if proposal.kind == 'schedule' %}
      <h3 class="assistant-proposal-name">{{ data.agent_name|default(data.name|default('Agent schedule'), true) }}</h3>
      <p class="assistant-schedule-action">{{ 'Resume scheduled work' if data.enabled else 'Pause scheduled work' }}</p>
      <p class="assistant-description">{% if data.enabled %}The agent can work at its next eligible scheduled time. Its current permissions, budgets and service credit still apply.{% else %}New scheduled work stops. Previous results and purchase requests stay available; actions already started may finish.{% endif %}</p>
      {% if data.reason %}<p class="assistant-proposal-note">{{ data.reason }}</p>{% endif %}
    {% else %}
      <h3 class="assistant-proposal-name">{{ data.name|default('Your new agent', true) }}</h3>
      <dl class="assistant-proposal-fields"><div><dt>Outcome</dt><dd>{{ data.goal|default('We’ll agree on a clear outcome together.', true) }}</dd></div></dl>
      {% if data.inputs %}<details class="assistant-proposal-context"><summary>Context and inputs</summary><p class="assistant-preserve-lines">{{ data.inputs }}</p></details>{% endif %}
      {% if data.scenario|default('pocketplan_ads') == 'general' %}<div class="assistant-budget-note"><h4>General agent</h4><p>Model-generated work based on your saved instructions and approved tools. Results appear in Habitat for your review.</p>{% if data.tools %}<h4>Approved tools</h4><ul>{% for tool in tool_catalog if tool.id in data.tools %}<li>{{ tool.title }}</li>{% endfor %}</ul><p class="field-hint">Creating this agent authorizes these tools during eligible runs. Public web search is limited to one invocation per deliverable; the agent chooses its queries and sources. Search does not authorize messages, publishing or payments.</p>{% else %}<p class="field-hint">Uses your supplied context without external tools. Public web search requires your approval.</p>{% endif %}</div>{% endif %}
      {% if data.deliverables %}<div class="assistant-deliverables"><h4>What you’ll receive</h4>{% for deliverable in data.deliverables %}<details><summary>{{ deliverable.name }}<span>{{ deliverable.criteria|default([])|length }} checks</span></summary>{% if deliverable.description %}<p>{{ deliverable.description }}</p>{% endif %}{% if deliverable.criteria %}<ul>{% for criterion in deliverable.criteria %}<li>{{ criterion }}</li>{% endfor %}</ul>{% endif %}</details>{% endfor %}</div>{% endif %}
      <dl class="assistant-proposal-fields assistant-schedule-fields"><div><dt>Schedule</dt><dd>{{ 'Every hour' if data.cadence == 'hourly' else 'Daily at 9:00 AM' if data.cadence == 'daily' else 'To be agreed' }}</dd></div><div><dt>Timezone</dt><dd>{{ data.timezone|default('To be agreed', true) }}</dd></div></dl>
      {% if data.budget_notes %}<div class="assistant-budget-note"><h4>Spending boundaries</h4><p>{{ data.budget_notes }}</p></div>{% endif %}
    {% endif %}
    {% if proposal.state == 'committed' %}<div class="assistant-confirmed"><span aria-hidden="true">✓</span><p>{{ 'Schedule updated.' if proposal.kind == 'schedule' else 'Your agent is ready to set up.' }}</p></div>{% if proposal.instance_href %}<a class="button primary assistant-confirm-button" href="{{ proposal.instance_href }}">Open agent workflow <span aria-hidden="true">→</span></a>{% endif %}
    {% elif proposal.state == 'pending' %}<div class="assistant-confirmation"><p class="field-hint">{% if proposal.kind == 'schedule' %}This change applies only when you confirm below.{% else %}Creates a draft with its schedule paused. Review spending limits and fund work before enabling it.{% endif %}</p><form method="post" action="/chat/proposals/{{ proposal.id }}/confirm" data-assistant-submit="confirm"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="chat_session_id" value="{{ session_id }}"><input type="hidden" name="version" value="{{ proposal.version }}"><button type="submit" class="primary assistant-confirm-button">{{ 'Resume schedule' if proposal.kind == 'schedule' and data.enabled else 'Pause schedule' if proposal.kind == 'schedule' else 'Create agent' }}</button><p class="assistant-request-status field-hint" role="status" aria-live="polite" data-assistant-request-status></p></form><a class="assistant-revise" href="#assistant-message" data-assistant-revise>Want to change something? Tell me in the conversation.</a></div>{% endif %}
  {% else %}<div class="assistant-preview-placeholder"><span class="assistant-outline-icon" aria-hidden="true">▤</span><p>I’ll turn our conversation into a proposal you can review.</p><ol><li>The outcome and audience</li><li>Deliverables and completion criteria</li><li>A schedule and spending boundaries</li></ol><p class="field-hint">Ask for changes as we go. Nothing is created or changed until you confirm.</p></div>{% endif %}
  </div>
</section>
<details class="assistant-scope"><summary>What this version can help with</summary><p>General agents produce custom text deliverables with completion criteria and hourly or daily schedules. Approve public web search when outside information is needed, or work from your supplied context. The agent chooses its queries and sources within a limit of one search invocation per deliverable. Results appear in Habitat; messaging, publishing, payments and shell actions are not supported. Scheduled generation requires an enabled model, funding and your controls.</p><p>For existing agents, ask about progress, costs or decisions waiting in Requests. Schedule changes need your confirmation.</p></details>
</aside>
</div>
<footer class="assistant-footer"><span>AI-assisted setup · review proposals before confirming.</span><details><summary>Assistant allowance</summary><p>${{ usd(usage.spent_micro_usd|default(0)) }} used{% if usage.held_micro_usd|default(0) %} · ${{ usd(usage.held_micro_usd) }} reserved{% endif %} · ${{ usd(usage.cap_micro_usd|default(0)) }} limit</p><p>Provided by Habitat for setup and monitoring; separate from agent funds.</p></details></footer>
</div>
<script src="/static/assistant.js" defer></script>
{% endblock %}"""


def _uuid(value: object) -> str | None:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _links(values: object) -> list[dict[str, str]]:
    """Only application references may become links, never model-supplied URLs."""
    output = []
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, dict):
            continue
        kind, identifier = value.get("kind"), _uuid(value.get("id"))
        routes = {"agent": "/instances/{}/workflow", "deliverable": "/audit/deliverables/{}", "job": "/audit/jobs/{}"}
        if kind in routes and identifier:
            href = routes[kind].format(identifier)
        elif kind == "audit":
            instance_id = _uuid(value.get("instance_id"))
            href = "/audit" + ("?instance_id=" + instance_id if instance_id else "")
        else:
            continue
        output.append({"href": href, "label": str(value.get("label") or ("View " + str(kind)))})
    return output


def _usd(value: object) -> str:
    amount = max(0, int(value))
    whole, fraction = divmod(amount, 1_000_000)
    return f"{whole}." + f"{fraction:06d}".rstrip("0").ljust(2, "0")


ENV = Environment(loader=DictLoader({**BASE_TEMPLATES, "owner_assistant": TEMPLATE}), autoescape=True)
ENV.globals["usd"] = _usd


def render_assistant(*, messages: list[dict], session_id: str, proposal: dict | None,
                     csrf: str, request_id: str, usage: dict, error: str = "", notice: str = "", account_name: str = "Owner") -> str:
    normalized_messages = []
    for message in messages:
        activities = message.get("activities")
        normalized_messages.append({"role": message.get("role"), "text": message.get("text", ""),
                                    "activities": [str(item) for item in activities] if isinstance(activities, list) else [],
                                    "links": _links(message.get("links"))})
    if proposal:
        instance_id = _uuid(proposal.get("instance_id"))
        proposal = {**proposal, "instance_href": f"/instances/{instance_id}/workflow" if instance_id else None}
    return ENV.get_template("owner_assistant").render(
        title="What can we help you achieve?", messages=normalized_messages, session_id=session_id,
        proposal=proposal, tool_catalog=TOOL_CATALOG, csrf=csrf, account_name=account_name, request_id=request_id, usage=usage, error=error, notice=notice,
    )
