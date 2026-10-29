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
{% macro run_control(action, label, style='secondary') -%}
<form method="post" action="/chat/runs/{{ runtime_run.id }}/{{ action }}" data-assistant-submit="{{ action }}"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="chat_session_id" value="{{ session_id }}"><button type="submit" class="{{ style }}">{{ label }}</button><p class="assistant-request-status field-hint" role="status" aria-live="polite" data-assistant-request-status></p></form>
{%- endmacro %}
{% macro readiness_panel(readiness, instance_id) -%}
{% if readiness %}<div class="assistant-funding">
  <h3>{{ 'Ready for the next step' if readiness.ready else 'Before work can continue' }}</h3>
  <p>Available service credit: <strong>${{ usd(readiness.balance_micro_usd) }}</strong></p>
  {% if readiness.required_micro_usd is not none %}<p class="field-hint">The next step requires up to ${{ usd(readiness.required_micro_usd) }} in available credit. Total cost depends on the work.</p>{% endif %}
  {% if readiness.blockers %}<ul>{% for blocker in readiness.blockers %}<li>{{ blocker.message }}</li>{% endfor %}</ul>{% endif %}
  {% if readiness.blockers|selectattr('reason', 'equalto', 'credit_insufficient')|list %}
  {% if readiness.funding_order_id %}<p>Finish or check your existing payment before adding more funds.</p><a class="button primary assistant-confirm-button" href="/commerce/orders/{{ readiness.funding_order_id }}">Continue payment</a>{% else %}
  <form method="post" action="/chat/funding" data-assistant-submit="funding">
    <input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="chat_session_id" value="{{ session_id }}"><input type="hidden" name="instance_id" value="{{ instance_id }}"><input type="hidden" name="request_id" value="{{ request_id }}">
    <label for="assistant-topup-{{ instance_id }}">Add service credit</label><select id="assistant-topup-{{ instance_id }}" name="amount_minor"><option value="500">$5.00</option><option value="1000">$10.00</option><option value="2000">$20.00</option></select>
    <button type="submit" class="primary assistant-confirm-button">Add funds with PayPal</button>
    <p class="field-hint">Review and authorize payment in checkout, then return here to start or resume this work.</p><p class="assistant-request-status field-hint" role="status" aria-live="polite" data-assistant-request-status></p>
  </form>{% endif %}{% endif %}
  {% if readiness.blockers|rejectattr('reason', 'equalto', 'credit_insufficient')|list %}<a href="/instances/{{ instance_id }}#budgets">Review spending limits and controls</a>{% endif %}
</div>{% endif %}
{%- endmacro %}
{% block eyebrow %}Habitat assistant{% endblock %}
{% block subtitle %}Turn an outcome into an agent, or check on work already underway.{% endblock %}
{% block header_actions %}<a class="button ghost" href="/chat?new=1">New conversation</a><a class="button ghost" href="/workspace">Back to workspace</a>{% endblock %}
{% block body %}
<link rel="stylesheet" href="/static/assistant.css">
<div class="owner-assistant" data-owner-assistant data-session-id="{{ session_id }}">
{% if notice %}<p class="notice success assistant-alert" role="status">{{ notice }}</p>{% endif %}
{% if error %}<p class="notice error assistant-alert" role="alert">{{ error }}</p>{% endif %}
<div class="assistant-layout">
<section class="card assistant-conversation" aria-labelledby="assistant-conversation-title">
  <div class="assistant-panel-heading"><div><h2 id="assistant-conversation-title">Let’s work it out together.</h2><p>{{ 'Follow progress, answer questions, or guide this work.' if runtime_run else 'Tell me the result you want. I’ll help shape the work.' }}</p></div><span class="assistant-presence" aria-label="AI assistant">H</span></div>
  <div class="assistant-transcript" data-assistant-transcript>
  {% if messages %}<ol class="assistant-messages" aria-label="Conversation">{% for message in messages %}
    <li class="assistant-message {{ 'from-owner' if message.role == 'user' else 'from-assistant' }}"{% if message.event_id %} data-runtime-event-id="{{ message.event_id }}"{% endif %}>
      <p class="assistant-message-label">{{ 'You' if message.role == 'user' else 'Habitat' }}</p>
      {% if message.activities %}<ul class="assistant-activities" aria-label="Assistant activity">{% for activity in message.activities %}<li><span aria-hidden="true">·</span> {{ activity }}</li>{% endfor %}</ul>{% endif %}
      <div class="assistant-message-text">{{ message.text }}</div>
      {% if message.links %}<div class="assistant-reference-links" aria-label="Related work">{% for link in message.links %}<a href="{{ link.href }}">{{ link.label }} <span aria-hidden="true">↗</span></a>{% endfor %}</div>{% endif %}
    </li>
  {% endfor %}</ol>
  {% elif runtime_run %}<div class="assistant-welcome"><h3>Stay in the conversation.</h3><p>The work plan and saved results appear alongside this chat. Add context or answer a question here to help your agent continue.</p></div>
  {% else %}<div class="assistant-welcome"><p class="assistant-welcome-mark" aria-hidden="true">↗</p><h3>Start with what success looks like.</h3><p>You don’t need an agent specification. Describe the outcome you need, and we’ll shape useful deliverables and choose the tools to support them.</p><div class="assistant-examples" aria-label="Conversation starters"><button type="button" class="secondary" data-assistant-example="Help me turn a recurring task into an agent with clear deliverables and the right tools">Plan an agent <span aria-hidden="true">↗</span></button><button type="button" class="secondary" data-assistant-example="Which agents need attention?">Which agents need attention? <span aria-hidden="true">↗</span></button></div></div>{% endif %}
  <div id="assistant-latest" aria-hidden="true"></div>
  </div>
  {% set run_terminal = runtime_run and runtime_run.status in ('completed', 'failed', 'cancelled') %}
  <p class="assistant-terminal field-hint" data-assistant-terminal{% if not run_terminal %} hidden{% endif %}>{{ 'This work is complete. Start a new conversation for another task.' if runtime_run and runtime_run.status == 'completed' else 'This run has ended. Start a new conversation for another task.' }}</p>
  <form class="assistant-composer" method="post" action="/chat/messages" data-assistant-submit="message"{% if run_terminal %} hidden{% endif %}>
    <input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="chat_session_id" value="{{ session_id }}"><input type="hidden" name="request_id" value="{{ request_id }}">
    {% if runtime_run %}<input type="hidden" name="run_id" value="{{ runtime_run.id }}"><input type="hidden" name="question_id" value="{{ runtime_run.question.id if runtime_run.question else '' }}"{% if not runtime_run.question %} disabled{% endif %}>{% endif %}
    <label for="assistant-message">{{ 'Answer the agent’s question' if runtime_run and runtime_run.question else 'Guide this work' if runtime_run else 'Continue the conversation' if messages else 'What would you like to achieve?' }}</label>
    <textarea id="assistant-message" name="text" rows="3" maxlength="4000" required placeholder="{{ 'Add context, a correction, or an answer for this run.' if runtime_run else 'Describe the result you want, who it is for, and any constraints the agent should follow.' }}" aria-describedby="assistant-composer-hint"></textarea>
    <div class="assistant-composer-actions"><span id="assistant-composer-hint" class="field-hint">{{ 'Your message goes directly to this run. Its permissions and spending limits still apply.' if runtime_run else 'Ask a question or describe a change to the proposal.' }}</span><button class="primary" type="submit">Send <span aria-hidden="true">↑</span></button></div>
    {% if not runtime_run and usage.unknown|default(false) %}<p class="field-hint assistant-allowance-held" role="status">A previous response is unresolved. Its allowance remains reserved; new assistant requests must wait.</p>{% endif %}
    <p class="assistant-request-status field-hint" role="status" aria-live="polite" data-assistant-request-status></p>
  </form>
</section>
<aside class="assistant-preview" aria-labelledby="assistant-preview-title">
{% if runtime_run %}
<section class="card assistant-run" data-assistant-run data-run-id="{{ runtime_run.id }}" data-run-status="{{ runtime_run.status }}" data-run-version="{{ runtime_run.version }}">
  <div class="assistant-panel-heading"><div><p class="kicker">AGENT WORK</p><h2 id="assistant-preview-title">Your work</h2></div><span class="status-badge assistant-run-status" data-run-status-label>{{ run_status_label }}</span></div>
  <div class="assistant-preview-body">
    <p class="assistant-run-objective" data-run-objective>{{ runtime_run.objective }}</p>
    <p class="notice assistant-run-reason" data-run-reason{% if not runtime_run.reason %} hidden{% endif %}>{{ ('Service credit is available. You can resume this work.' if runtime_run.readiness and runtime_run.readiness.ready else 'This work needs more service credit. Add funds below, then resume.') if runtime_run.reason == 'credit_insufficient' else runtime_run.reason|default('', true)|replace('_', ' ') }}</p>
    <div data-run-readiness>{% if runtime_run.status in ['blocked', 'paused'] %}{{ readiness_panel(runtime_run.readiness, runtime_run.instance_id) }}{% endif %}</div>
    <section class="assistant-run-question" data-run-question{% if not runtime_run.question %} hidden{% endif %}><h3>Your input is needed</h3><p data-run-question-text>{{ runtime_run.question.text if runtime_run.question else '' }}</p><div class="assistant-question-options" data-run-options>{% if runtime_run.question %}{% for option in runtime_run.question.options %}<button type="button" class="secondary" data-assistant-option="{{ option }}">{{ option }}</button>{% endfor %}{% endif %}</div><a href="#assistant-message" data-assistant-revise>Answer in the conversation</a></section>
    <section class="assistant-run-plan"><h3>Work plan</h3><ol data-run-plan>{% for item in runtime_run.plan %}<li><div><span class="assistant-plan-title">{{ item.title }}</span><span class="assistant-plan-state">{{ item.state|replace('_', ' ')|capitalize }}</span></div>{% if item.summary %}<p>{{ item.summary }}</p>{% endif %}</li>{% endfor %}</ol><p class="field-hint" data-run-empty-plan{% if runtime_run.plan %} hidden{% endif %}>The agent will save its plan when work begins.</p></section>
    <section class="assistant-run-artifacts"><h3>Results</h3><div data-run-artifacts>{% for artifact in runtime_run.artifacts %}<details class="assistant-run-artifact"{% if artifact.completed %} open{% endif %}><summary>{{ artifact.name }}<span>Version {{ artifact.version }} · {{ 'Completed' if artifact.completed else 'Draft' }}</span></summary><div class="assistant-artifact-content">{{ artifact.content }}</div></details>{% endfor %}</div><p class="field-hint" data-run-empty-artifacts{% if runtime_run.artifacts %} hidden{% endif %}>Saved drafts and completed results will appear here.</p></section>
    <div class="assistant-run-controls" data-run-controls>{% if runtime_run.can_advance %}{{ run_control('advance', 'Continue work', 'primary') }}{% endif %}{% if runtime_run.can_pause %}{{ run_control('pause', 'Pause work') }}{% endif %}{% if runtime_run.can_resume %}{{ run_control('resume', 'Resume work', 'primary') }}{% endif %}{% if runtime_run.can_cancel %}{{ run_control('cancel', 'Cancel work', 'ghost') }}{% endif %}</div>
    <div class="assistant-run-refresh"><a href="/chat?session={{ session_id }}">Refresh progress</a><span class="field-hint" data-run-refresh-status role="status" aria-live="polite"></span></div>
    <p class="field-hint assistant-run-boundary">Public page reads use approved exact domains. Search and browser interaction are unavailable in this execution mode.</p>
  </div>
</section>
{% else %}
{% if runtime_available and runtime_candidates %}<section class="card assistant-run-start">
  <div class="assistant-panel-heading"><div><p class="kicker">PREPARE TO WORK</p><h2>Start an agent’s work</h2></div></div>
  <div class="assistant-preview-body">
    <label for="assistant-run-agent">Agent</label><select id="assistant-run-agent" name="instance_id" form="assistant-start-form">{% for candidate in runtime_candidates %}<option value="{{ candidate.id }}"{% if candidate.id == selected_instance %} selected{% endif %} data-web-read="{{ 'true' if candidate.web_read else 'false' }}">{{ candidate.name }}</option>{% endfor %}</select>
  {% for candidate in runtime_candidates %}<div data-candidate-readiness="{{ candidate.id }}" data-ready="{{ 'true' if candidate.readiness and candidate.readiness.ready else 'false' }}"{% if candidate.id != selected_instance %} hidden{% endif %}>{{ readiness_panel(candidate.readiness, candidate.id) }}</div>{% endfor %}
  </div>
  <form id="assistant-start-form" class="assistant-preview-body" method="post" action="/chat/runs/start" data-assistant-submit="start">
    <input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="chat_session_id" value="{{ session_id }}"><input type="hidden" name="request_id" value="{{ request_id }}">
    <p class="field-hint">Uses this agent’s saved goal and completion criteria. Existing permissions, spending limits and service credit apply.</p>
    <label class="assistant-tool-consent"><input type="checkbox" name="tools" value="web.read" data-runtime-web-read{% if not selected_web_read %} disabled{% endif %}> Allow public web page reads for this run</label>
    <p class="field-hint">Reads are restricted to the agent’s approved exact domains. Search and browser interaction are unavailable in this execution mode.</p>
    <details class="assistant-run-setup"><summary>Review agent controls</summary>{% for candidate in runtime_candidates %}<a href="{{ candidate.setup_href }}">{{ candidate.name }}</a>{% endfor %}</details>
    <button type="submit" class="primary assistant-confirm-button" data-start-work{% if not selected_ready %} disabled{% endif %}>Start work</button><p class="assistant-request-status field-hint" role="status" aria-live="polite" data-assistant-request-status></p>
  </form>
</section>{% endif %}
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
{% endif %}
</aside>
</div>
<footer class="assistant-footer"><span>{{ 'Agent work · your permissions and spending limits apply.' if runtime_run else 'AI-assisted setup · review proposals before confirming.' }}</span>{% if not runtime_run %}<details><summary>Assistant allowance</summary><p>${{ usd(usage.spent_micro_usd|default(0)) }} used{% if usage.held_micro_usd|default(0) %} · ${{ usd(usage.held_micro_usd) }} reserved{% endif %} · ${{ usd(usage.cap_micro_usd|default(0)) }} limit</p><p>Provided by Habitat for setup and monitoring; separate from agent funds.</p></details>{% endif %}</footer>
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
                     csrf: str, request_id: str, usage: dict, error: str = "", notice: str = "", account_name: str = "Owner",
                     runtime_run: dict | None = None, runtime_candidates: list[dict] | None = None,
                     runtime_available: bool = False, preferred_instance: str = "", unified_workspace: bool = False) -> str:
    normalized_messages = []
    for message in messages:
        activities = message.get("activities")
        normalized_messages.append({"role": message.get("role"), "text": message.get("text", ""),
                                    "event_id": _uuid(message.get("id")),
                                    "activities": [str(item) for item in activities] if isinstance(activities, list) else [],
                                    "links": _links(message.get("links"))})
    if proposal:
        instance_id = _uuid(proposal.get("instance_id"))
        proposal = {**proposal, "instance_href": f"/instances/{instance_id}/workflow" if instance_id else None}
    candidates = []
    for candidate in runtime_candidates or []:
        instance_id = _uuid(candidate.get("id"))
        if instance_id:
            candidates.append({**candidate, "id": instance_id, "setup_href": f"/instances/{instance_id}",
                               "web_read": any(tool.get("name") == "web.read" for tool in candidate.get("tools", []))})
    selected_instance = proposal.get("instance_id") if proposal else None
    if any(candidate["id"] == preferred_instance for candidate in candidates):
        selected_instance = preferred_instance
    if not any(candidate["id"] == selected_instance for candidate in candidates):
        selected_instance = candidates[0]["id"] if candidates else None
    selected_web_read = next((candidate["web_read"] for candidate in candidates if candidate["id"] == selected_instance), False)
    selected_ready = next((candidate.get("readiness", {}).get("ready", False)
                           for candidate in candidates if candidate["id"] == selected_instance), False)
    if runtime_run and not _uuid(runtime_run.get("id")):
        runtime_run = None
    status_labels = {"queued": "Ready to continue", "running": "Working", "waiting_owner": "Needs your input",
                     "blocked": "Blocked", "paused": "Paused", "completed": "Completed", "failed": "Failed", "cancelled": "Cancelled"}
    return ENV.get_template("owner_assistant").render(
        title="What can we help you achieve?", messages=normalized_messages, session_id=session_id,
        unified_workspace=unified_workspace,
        proposal=proposal, tool_catalog=TOOL_CATALOG, csrf=csrf, account_name=account_name, request_id=request_id, usage=usage, error=error, notice=notice,
        runtime_run=runtime_run, runtime_available=runtime_available, runtime_candidates=candidates,
        selected_instance=selected_instance, selected_web_read=selected_web_read, selected_ready=selected_ready,
        run_status_label=status_labels.get(runtime_run["status"], "Unavailable") if runtime_run else "",
    )
