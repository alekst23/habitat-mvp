"""Autoescaped, compact owner request inbox and response forms."""

from __future__ import annotations

from urllib.parse import quote, urlencode

from jinja2 import DictLoader, Environment

from aicl.commerce.pages import money
from aicl.web.pages import TEMPLATES as BASE_TEMPLATES
from aicl.workflow.pages import date_label, label


KINDS = {
    "authentication": "Sign-in required",
    "clarification": "Question",
    "permission": "Permission",
    "purchase": "Purchase",
}


def requests_url(selected: str = "", instance_id: str = "", status: str = "pending", kind: str = "") -> str:
    values = {key: value for key, value in (
        ("selected", selected), ("instance_id", instance_id), ("status", status), ("kind", kind)
    ) if value}
    return "/requests?" + urlencode(values)


def request_action(request_id: str, action: str) -> str:
    return "/requests/" + quote(str(request_id), safe="") + "/" + action


TEMPLATES = {
    "requests/inbox": """{% extends 'base' %}{% set page_key = 'requests' %}
{% block subtitle %}Questions, access and spending decisions, together in one place.{% endblock %}
{% block header_actions %}<a class="button ghost small" href="/audit">View audit history <span aria-hidden="true">↗</span></a>{% endblock %}
{% block body %}<link rel="stylesheet" href="/static/requests.css"><script defer src="/static/requests.js"></script>
<div class="requests-workspace">
{% if error %}<p class="notice error" role="alert">{{ error }}</p>{% endif %}
{% if notice %}<p class="notice success" role="status">{{ notice }}</p>{% endif %}
<div class="requests-toolbar"><nav class="requests-tabs" aria-label="Request views">
<a href="{{ requests_url('', instance_id, 'pending', kind) }}"{% if status == 'pending' %} aria-current="page"{% endif %}>Needs response <span class="requests-count">{{ pending_count|default(0) }}</span></a>
<a href="{{ requests_url('', instance_id, 'all', kind) }}"{% if status != 'pending' %} aria-current="page"{% endif %}>All activity</a>
</nav><form class="requests-filters" action="/requests" method="get"><input type="hidden" name="status" value="{{ status }}">
<div><label class="requests-sr-only" for="requests-agent">Filter by agent</label><select id="requests-agent" name="instance_id"><option value="">All agents</option>{% for agent in agents %}<option value="{{ agent.id }}"{% if instance_id == agent.id %} selected{% endif %}>{{ agent.name }}</option>{% endfor %}</select></div>
<div><label class="requests-sr-only" for="requests-kind">Filter by request type</label><select id="requests-kind" name="kind"><option value="">All types</option>{% for value, text in request_kinds.items() %}<option value="{{ value }}"{% if kind == value %} selected{% endif %}>{{ text }}</option>{% endfor %}</select></div>
<button class="secondary small" type="submit">Filter</button></form></div>
<div class="requests-layout">
<section class="requests-list-panel" aria-labelledby="requests-list-heading"><div class="requests-list-heading"><h2 id="requests-list-heading">{{ 'Waiting for you' if status == 'pending' else 'Requests' }}</h2><span>{{ requests|length }}</span></div>
<ul class="requests-list">{% for item in requests %}<li><a class="requests-item{% if selected and selected.id == item.id %} is-selected{% endif %}" href="{{ requests_url(item.id, instance_id, status, kind) }}#request-detail"{% if selected and selected.id == item.id %} aria-current="true"{% endif %}>
<div class="requests-item-meta"><span class="requests-kind">{{ request_kinds.get(item.kind, label(item.kind)) }}</span><span class="requests-state {{ 'is-pending' if item.status == 'pending' else '' }}">{{ label(item.stage or item.status) }}</span></div>
<h3>{{ item.title }}</h3><p class="requests-agent-name">{{ item.agent_name }}</p><p class="requests-item-reason">{{ item.reason }}</p><div class="requests-item-footer"><time datetime="{{ item.created_at }}">{{ date_label(item.created_at) }}</time>{% if item.kind == 'purchase' and item.purchase %}<strong>${{ money(item.purchase.quote.amount_minor) }} {{ item.purchase.quote.currency }}</strong>{% elif item.proposal %}<strong>${{ money(item.proposal.amount_minor) }} {{ item.proposal.currency }}</strong>{% endif %}</div>
</a></li>{% else %}<li class="requests-list-empty"><span class="requests-empty-mark" aria-hidden="true">✓</span><strong>{{ 'Nothing needs your response' if status == 'pending' else 'No requests yet' }}</strong><p>{{ 'New questions and approval requests will appear here.' if not instance_id and not kind else 'Try another agent or request type.' }}</p></li>{% endfor %}</ul></section>
<section class="requests-detail" id="request-detail" aria-labelledby="request-detail-heading" tabindex="-1">
{% if selected %}{% set r = selected %}
<header class="requests-detail-header"><div class="requests-item-meta"><span class="requests-kind">{{ request_kinds.get(r.kind, label(r.kind)) }}</span><span class="requests-state {{ 'is-pending' if r.status == 'pending' else '' }}">{{ label(r.stage or r.status) }}</span></div><h2 id="request-detail-heading">{{ r.title }}</h2><p class="requests-byline"><a href="/instances/{{ r.instance_id|urlencode }}/workflow">{{ r.agent_name }}</a><span aria-hidden="true">·</span><time datetime="{{ r.created_at }}">{{ date_label(r.created_at) }}</time></p></header>
<div class="requests-detail-body">
<section class="requests-reason"><h3>Why your agent needs this</h3><p>{{ r.reason }}</p></section>
{% if r.job_id or r.goal or r.job_name %}<section class="requests-source"><div class="requests-source-title"><h3>Work behind this request</h3>{% if r.job_id %}<a href="/audit/jobs/{{ r.job_id|urlencode }}">View job <span aria-hidden="true">↗</span></a>{% endif %}</div>{% if r.job_name %}<p><strong>{{ r.job_name }}</strong></p>{% endif %}{% if r.goal %}<p>{{ r.goal }}</p>{% endif %}{% if r.kind == 'purchase' and r.purchase and r.purchase.source_job and r.purchase.source_job.latest_deliverable %}<a class="requests-output-link" href="/audit/deliverables/{{ r.purchase.source_job.latest_deliverable.id|urlencode }}">View supporting deliverable <span aria-hidden="true">↗</span></a>{% endif %}</section>{% endif %}
{% if r.proposal %}{% include 'requests/browser-purchase' %}
{% elif r.kind == 'purchase' %}{% include 'requests/purchase' %}
{% elif r.status == 'pending' %}{% include 'requests/response' %}
{% else %}{% include 'requests/history' %}{% endif %}
<details class="requests-record"><summary>Request record</summary><dl><div><dt>Created</dt><dd>{{ date_label(r.created_at) }}</dd></div><div><dt>Last updated</dt><dd>{{ date_label(r.updated_at) }}</dd></div><div><dt>Reference</dt><dd><code>{{ r.id }}</code></dd></div></dl></details>
</div>{% else %}<div class="requests-detail-empty"><span class="requests-empty-mark" aria-hidden="true">↖</span><h2 id="request-detail-heading">{{ 'Choose a request' if requests else 'You’re up to date' }}</h2><p>{{ 'Review the work, respond, and choose how the job continues.' if requests else 'Your agents will ask here when they need a decision, access, or more information.' }}</p><a href="/workspace">Back to workspace</a></div>{% endif %}</section>
</div></div>{% endblock %}""",
    "requests/continuation": """<fieldset class="requests-continuation"><legend>{{ continuation_title|default('After your response') }}</legend><label><input type="radio" name="continuation" value="now"{% if r.continuation == 'now' %} checked{% endif %}> Resume this job now</label><label><input type="radio" name="continuation" value="schedule"{% if r.continuation != 'now' %} checked{% endif %}> Continue on schedule</label><p>Current budgets, permissions and schedule controls still apply.</p></fieldset>""",
    "requests/response": """{% if r.kind == 'authentication' %}<div class="requests-auth-domain"><span class="requests-domain-label">Website requesting sign-in</span><strong>{{ r.details.domain|default(r.details.origin|default('Domain unavailable'), true) }}</strong>{% if r.details.requested_access %}<p>{{ r.details.requested_access }}</p>{% endif %}{% if r.details.account_label %}<p>Account: {{ r.details.account_label }}</p>{% endif %}</div>{% if r.browser_state == 'closing' %}<p class="notice info">The browser is closing. Access stays blocked until shutdown is confirmed.</p><a class="button secondary" href="{{ request_action(r.id, 'browser') }}">Review browser shutdown</a>{% elif r.capability == 'available' %}<div class="requests-browser-start"><p>Sign in directly to the website in your private cloud browser. The agent waits while you have control.</p><form method="post" action="{{ request_action(r.id, 'browser/start') }}"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="expected_version" value="{{ r.version }}"><button class="primary" type="submit">Open secure sign-in <span aria-hidden="true">↗</span></button></form><p class="field-hint">Access can be saved for this agent’s scheduled jobs for up to 24 hours. Purchases still require separate approval.</p></div>{% else %}<div class="requests-unavailable"><button type="button" disabled aria-describedby="requests-signin-unavailable">Open secure sign-in</button><p id="requests-signin-unavailable">{{ r.capability_message }}</p><p>Signing in grants access to this service. Spending still requires separate approval.</p></div>{% endif %}<form method="post" action="{{ request_action(r.id, 'respond') }}"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="expected_version" value="{{ r.version }}"><button class="secondary" type="submit" name="decision" value="decline">Decline access</button></form>
{% elif r.kind == 'clarification' %}<form class="requests-response-form" method="post" action="{{ request_action(r.id, 'respond') }}"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="expected_version" value="{{ r.version }}">
{% if r.details.question %}<h3 class="requests-question">{{ r.details.question }}</h3>{% endif %}
{% if r.details.options %}<div class="requests-suggested"><p>Suggested answers</p><div class="requests-answer-choices">{% for option in r.details.options %}<button type="button" class="secondary small" data-request-answer="{{ option.label if option is mapping else option }}" aria-controls="request-answer">{{ option.label if option is mapping else option }}</button>{% endfor %}</div></div>{% endif %}
<div class="field"><label for="request-answer">Your answer</label><textarea id="request-answer" name="answer" rows="3" maxlength="4000" placeholder="Choose a suggestion or write your own answer." aria-describedby="request-answer-scope" required></textarea><p id="request-answer-scope" class="field-hint">Your answer is saved with this job. It does not change the agent’s ongoing configuration.</p></div>
{% include 'requests/continuation' %}<div class="requests-actions"><button class="primary" type="submit" name="decision" value="answer">Send answer</button><button class="ghost" type="submit" name="decision" value="decline" formnovalidate>Decline request</button></div></form>
{% elif r.kind == 'permission' %}<div class="requests-scope"><h3>Permission for this request</h3>{% if r.details.action %}<p><strong>{{ r.details.action }}</strong></p>{% endif %}<p>{{ r.details.scope|default(r.title, true) }}</p>{% if r.details.domain %}<p class="field-hint">Website: {{ r.details.domain }}</p>{% endif %}<p class="field-hint">Approval applies only to the action described here. It does not change the agent’s ongoing permissions.</p></div><form class="requests-response-form" method="post" action="{{ request_action(r.id, 'respond') }}"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="expected_version" value="{{ r.version }}">{% include 'requests/continuation' %}<div class="requests-actions"><button class="primary" type="submit" name="decision" value="approve">Approve request</button><button class="secondary" type="submit" name="decision" value="decline">Decline request</button></div></form>{% endif %}""",
    "requests/browser-purchase": """{% set p = r.proposal %}
<section class="requests-proposal"><h3>Proposed purchase</h3><dl class="requests-purchase-facts"><div><dt>Seller / platform</dt><dd>{{ p.seller }}<br><span class="field-hint">{{ p.domain }}</span></dd></div><div><dt>Proposed budget</dt><dd class="requests-amount">${{ money(p.amount_minor) }} <span>{{ p.currency }}</span></dd></div><div><dt>Purchase</dt><dd>{{ p.description }}</dd></div></dl><p class="field-hint">This is the agent’s proposed spend, not a confirmed checkout quote. Pricing and availability would need to be checked before a payment.</p></section>
{% if p.source_deliverable %}<p class="requests-output-link"><a href="/audit/deliverables/{{ p.source_deliverable.id|urlencode }}">View supporting deliverable · version {{ p.source_deliverable.version }} <span aria-hidden="true">↗</span></a></p>{% endif %}
<details class="requests-proposal" open><summary>Browser evidence</summary><p class="field-hint">Observations from the source website that informed this proposal.</p>{% for evidence in p.evidence %}<div class="requests-creative"><strong>{{ evidence.title }}</strong><p>{{ evidence.excerpt }}</p><a href="{{ evidence.url }}" target="_blank" rel="noopener noreferrer">{{ evidence.url }} <span aria-hidden="true">↗</span></a></div>{% endfor %}</details>
<div class="requests-result"><strong>Stops before checkout</strong><p>Approval records your decision on this proposal. It does not place an order, publish an ad, authorize PayPal, or spend funds.</p></div>
{% if p.state == 'pending' %}<form class="requests-response-form" method="post" action="{{ request_action(r.id, 'decision') }}"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="expected_version" value="{{ r.version }}"><div class="requests-actions"><button class="primary" type="submit" name="decision" value="approve">Approve proposal</button><button class="secondary" type="submit" name="decision" value="decline">Decline proposal</button></div></form>
{% else %}<section class="requests-result"><h3>{{ 'Proposal approved' if p.state == 'approved' else 'Proposal superseded' if p.state == 'superseded' else 'Proposal declined' }}</h3><p>{{ 'The supporting work is being revised. Review the new proposal when it is ready.' if p.state == 'superseded' else 'Your decision is saved with the source job.' }} No payment was made.</p></section>{% endif %}""",
    "requests/purchase": """{% set p = r.purchase %}{% if p %}{% set campaign = p.quote.campaign|default(none) %}
<dl class="requests-purchase-facts"><div><dt>Seller</dt><dd>{{ p.quote.merchant_name }}</dd></div><div><dt>Total including fees</dt><dd class="requests-amount">${{ money(p.quote.amount_minor) }} <span>{{ p.quote.currency }}</span></dd></div><div><dt>Purchase</dt><dd>{{ p.quote.item_name }}</dd></div></dl>
{% if campaign %}<details class="requests-proposal"><summary>Review the exact campaign</summary><dl class="requests-purchase-facts"><div><dt>App &amp; platform</dt><dd>{{ campaign.product_name }} · {{ campaign.platform }}</dd></div><div><dt>Spending limits</dt><dd>${{ money(campaign.daily_cap_minor) }}/day · {{ campaign.duration_days }} days</dd></div><div><dt>Audience</dt><dd>{{ campaign.targeting }}</dd></div><div><dt>Destination</dt><dd>{{ campaign.destination_url }}</dd></div></dl>{% for ad in campaign.creative %}<div class="requests-creative"><strong>{{ ad.headline }}</strong><p>{{ ad.body }}</p><p class="field-hint">{{ ad.call_to_action }}</p></div>{% endfor %}{% if campaign.rationale %}<p><strong>Why this campaign:</strong> {{ campaign.rationale }}</p>{% endif %}{% if campaign.evidence %}<ul>{% for point in campaign.evidence %}<li>{{ point }}</li>{% endfor %}</ul>{% endif %}{% if campaign.alternative %}<p><strong>Alternative:</strong> {{ campaign.alternative }}</p>{% endif %}{% if campaign.decline_outcome %}<p><strong>If declined:</strong> {{ campaign.decline_outcome }}</p>{% endif %}</details>{% endif %}
{% if p.source_work %}<div class="requests-source"><h3>Supporting work</h3>{% for work in p.source_work %}<p><a href="/audit/deliverables/{{ work.deliverable_id|urlencode }}">{{ work.name }} ↗</a></p>{% endfor %}</div>{% endif %}
{% if p.blocked_reason %}<p class="notice info">{{ label(p.blocked_reason) }} · <a href="/instances/{{ r.instance_id|urlencode }}#overview">Review controls</a></p>{% endif %}
{% if p.expired|default(false) or p.state == 'expired' %}<p class="notice info">This quote has expired. A fresh proposal needs your approval.</p><a href="/audit?view=purchases&amp;instance_id={{ r.instance_id|urlencode }}#purchase-{{ p.id|urlencode }}">Review the expired proposal</a>
{% elif p.state == 'awaiting_approval' %}<form class="requests-response-form" method="post" action="{{ request_action(r.id, 'decision') }}"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="quote_digest" value="{{ p.quote_digest }}"><input type="hidden" name="expected_version" value="{{ r.version }}">{% with continuation_title='After verified payment' %}{% include 'requests/continuation' %}{% endwith %}<div class="requests-actions"><button class="primary" type="submit" name="decision" value="approve">Approve purchase</button><button class="secondary" type="submit" name="decision" value="decline">Decline purchase</button></div><p class="requests-payment-note">Approval covers this exact seller, purchase and total{% if campaign %}, including the campaign details above{% endif %}. Changes need a new approval. PayPal authorization is the next step; approval alone does not make a payment.</p></form>
{% elif p.state in ('awaiting_checkout', 'payment_pending') %}<div class="requests-checkout"><ol class="requests-progress" aria-label="Purchase progress"><li class="is-complete">✓ Purchase approved</li><li aria-current="step">{{ '2 · Verify payment' if p.state == 'payment_pending' else '2 · Authorize with PayPal' }}</li><li>3 · Continue work</li></ol><p>{{ 'Payment is pending. Work continues only after the required payment outcome is verified.' if p.state == 'payment_pending' else 'Your decision is saved. Authorize the prepared seller payment with PayPal to complete this request.' }}</p>{% if p.order_id %}<a class="button primary" href="/commerce/orders/{{ p.order_id|urlencode }}">{{ 'Review pending payment' if p.state == 'payment_pending' else 'Continue to PayPal' }}</a>{% endif %}<p class="field-hint">After payment: {{ 'resume this job now' if r.continuation == 'now' else 'continue on schedule' }}, subject to current controls.</p></div>
{% elif p.state == 'paid' %}<div class="requests-result"><strong>Payment completed</strong><p>The payment result is recorded. Work and delivery remain subject to the agent’s controls.</p>{% if p.order_id %}<a href="/commerce/orders/{{ p.order_id|urlencode }}">View payment receipt</a>{% endif %}</div>
{% else %}<div class="requests-result"><strong>{{ label(p.state) }}</strong><p>{{ 'You declined this purchase. No merchant payment was made.' if p.state == 'declined' else 'Checkout was cancelled. No merchant payment was made.' if p.state == 'cancelled' else 'This request remains available as part of the agent’s history.' }}</p>{% if p.order_id %}<a href="/commerce/orders/{{ p.order_id|urlencode }}">View payment details</a>{% endif %}</div>{% endif %}
{% else %}<p class="notice info">Purchase details are unavailable. Open Audit to review the original record.</p>{% endif %}""",
    "requests/history": """<section class="requests-result"><h3>{{ 'Request declined' if r.status == 'declined' else 'Closing browser' if r.kind == 'authentication' and r.browser_state == 'closing' else 'Session provided' if r.kind == 'authentication' else 'Response recorded' }}</h3>{% if r.kind == 'authentication' and r.browser_state == 'closing' %}<p>Browser access is blocked while shutdown is confirmed.</p><a href="{{ request_action(r.id, 'browser') }}">Retry closing the browser</a>{% endif %}{% if r.response %}{% if r.response is mapping %}{% if r.kind == 'authentication' and r.status == 'resolved' %}{% if r.browser_state == 'closing' %}<p>The session cannot be used while the browser is closing.</p>{% elif r.browser_state in ('revoked', 'expired') %}<p>Saved browser access is {{ r.browser_state }}. A new sign-in request is needed to use this service again.</p>{% else %}<p>The interactive browser is closed. The worker must check access before continuing; this does not authorize purchases.</p>{% endif %}{% elif r.response.answer %}<p class="requests-answer-saved">{{ r.response.answer }}</p>{% elif r.response.decision %}<p>{{ label(r.response.decision) }}</p>{% endif %}{% else %}<p class="requests-answer-saved">{{ r.response }}</p>{% endif %}{% endif %}<p class="field-hint">{{ 'This job remains stopped. Your decision is recorded.' if r.status == 'declined' else 'Your response is saved with this job. Continuation remains subject to current AICL controls.' }}</p>{% if r.status != 'declined' %}<p class="field-hint">Requested continuation: {{ 'resume this job now' if r.continuation == 'now' else 'continue on schedule' }}.</p>{% endif %}{% if r.kind == 'authentication' and r.status == 'resolved' and r.browser_state == 'complete' %}<form method="post" action="{{ request_action(r.id, 'browser/revoke') }}"><input type="hidden" name="csrf_token" value="{{ csrf }}"><button class="secondary small" type="submit">Revoke saved access</button></form>{% endif %}</section>""",
}


ENV = Environment(loader=DictLoader({**BASE_TEMPLATES, **TEMPLATES}), autoescape=True)
ENV.globals.update(
    money=money,
    date_label=date_label,
    label=label,
    request_kinds=KINDS,
    requests_url=requests_url,
    request_action=request_action,
)


def render(template: str, /, **context: object) -> str:
    context.setdefault("title", "Requests")
    context.setdefault("status", "pending")
    context.setdefault("kind", "")
    context.setdefault("instance_id", "")
    context.setdefault("selected", None)
    context.setdefault("agents", [])
    context.setdefault("requests", [])
    return ENV.get_template(template).render(**context)
