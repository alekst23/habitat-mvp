"""Autoescaped local commerce demonstration pages, using the Habitat owner shell."""

from __future__ import annotations

from jinja2 import DictLoader, Environment

from aicl.web.pages import TEMPLATES as BASE_TEMPLATES

NOTICES = {
    "funding_completed": "Payment completed. Service credit is available for this agent; your setup and task brief are preserved.",
    "payment_completed": "Payment completed and the template was delivered. Resume the task when you are ready.",
    "brief_saved": "Task brief saved. Complete setup, then start when you are ready.",
    "settings_saved": "Purchase controls saved. Every purchase still needs your exact approval and separate buyer consent.",
    "run_started": "Your agent has prepared a launch-kit plan and is waiting for your purchase decision.",
    "purchase_approved": "Habitat approval recorded. Continue to checkout to authorize the payment.",
    "purchase_declined": "Purchase declined. No merchant payment was made; the task has stopped.",
    "run_completed": "Launch kit completed with the delivered template. Inference usage is recorded below.",
}

FAILURES = {
    "buyer_required": "Choose a PayPal account to authorize this payment.",
    "buyer_changed": "The selected account changed. Review this order before confirming payment.",
    "invalid_buyer": "Choose one of the available accounts.",
    "provider_unavailable": "The payment provider could not confirm the result. Check payment status on this same order before taking another action.",
    "provider_mismatch": "The payment API response did not match this order. No new credit or delivery was recorded. Check the same order's payment status.",
    "provider_not_configured": "This PayPal merchant is not configured yet. Add the merchant's Sandbox app credentials before starting this payment.",
    "payment_not_approved": "Approve this order in PayPal first, then return here to finish payment. No payment was recorded.",
    "paypal_return_mismatch": "This PayPal return does not match the saved order. Reopen its checkout to continue safely.",
    "paypal_approval_expired": "Your purchase approval expired during checkout. Review the saved seller, scope and amount, then renew approval for this same order below.",
    "payment_transport_mismatch": "This order belongs to a different payment environment. Reopen it using its original payment configuration.",
    "payment_unresolved": "A payment result is unresolved. Check its payment status before changing or cancelling the purchase.",
    "action_failed": "This action could not complete. Review the current controls and task state, then try again.",
    "validation_failed": "Check all required task fields and their length limits. Money amounts must use dollars with no more than two decimal places.",
    "task_in_progress": "Finish or decline the current task before starting another. No new work was charged.",
    "conflict": "The record changed or this request was already used differently. Review the refreshed page before retrying.",
    "invalid_transition": "That action is no longer available in the current state. Review the refreshed task or checkout.",
    "invalid_state": "That action is no longer available in the current state. Review the refreshed task or checkout.",
    "instance_not_active": "Activate or resume this agent in its controls before continuing the task.",
    "capability_disabled": "Enable inference in the agent controls before continuing the task.",
    "purchase_disabled": "Enable purchases before requesting or completing a purchase.",
    "purchasing_disabled": "Enable purchases before requesting or completing a purchase.",
    "purchases_disabled": "Enable purchases before requesting or completing a purchase.",
    "budget_exhausted": "The agent's existing daily or monthly budget cannot cover this work. Review all four limits.",
    "insufficient_funds": "Add service credit before running more inference.",
    "insufficient_credit": "Add service credit before running more inference.",
    "credit_insufficient": "Add service credit before running more inference.",
    "purchase_limit_exceeded": "The purchase allowance cannot cover this request. Review its held and spent amounts.",
    "purchase_budget_exhausted": "The purchase allowance cannot cover this request. Review its held and spent amounts.",
    "quote_expired": "The quote expired. Its purchase cannot proceed; start a new task for a fresh proposal.",
    "quote_mismatch": "The quote does not match your approval. Review a fresh proposal before approving a purchase.",
    "confirmation_mismatch": "The quote does not match your approval. Review a fresh proposal before approving a purchase.",
    "confirmation_expired": "The purchase approval expired. Start a new task for a fresh proposal.",
    "confirmation_required": "Complete the exact purchase approval and buyer checkout before resuming this task.",
    "reconciliation_pending": "An earlier result remains pending. Resolve its existing checkout before continuing.",
    "gate_unresolved": "An agent control is blocking work. Return to the agent controls and resolve the gate.",
    "price_unavailable": "The configured price table cannot price this work. No model request was made.",
    "budget_unavailable": "A valid budget could not be established. Review the agent controls before retrying.",
    "denied": "The current controls do not allow this action. Review the agent and purchase settings below.",
}

TEMPLATES = {
    'commerce/paypal_finish': """<form method="post" action="/commerce/orders/{{ order.id }}/paypal-complete"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="provider_order_id" value="{{ order.provider_order_id }}">{% if paypal_approval_expired %}<div class="notice info"><strong>Renew your purchase approval</strong><p>Your earlier approval expired. This renews only the exact purchase shown above, on the same PayPal order. Current AICL controls still apply.</p><input type="hidden" name="quote_digest" value="{{ purchase.quote_digest }}"><label><input type="checkbox" name="renew_approval" value="true" required> I approve {{ purchase.quote.item_name }} from {{ order.merchant_name }} for ${{ money(order.amount_minor) }} {{ order.currency }} again.</label></div>{% endif %}<button class="{{ payment_button_class }}" type="submit">{{ 'Renew approval & finish payment' if paypal_approval_expired else 'Finish approved payment' }} · ${{ money(order.amount_minor) }}</button></form>""",
    'commerce/campaign_details': """<section class="campaign-details" aria-label="Exact campaign proposal"><dl class="commerce-summary workflow-summary"><div><dt>App &amp; platform</dt><dd>{{ campaign.product_name }} · {{ campaign.platform }}</dd></div><div><dt>Campaign limits</dt><dd>${{ money(campaign.total_cap_minor) }} total · ${{ money(campaign.daily_cap_minor) }}/day · {{ campaign.duration_days }} days</dd></div><div><dt>Audience</dt><dd>{{ campaign.targeting }}</dd></div><div><dt>Destination</dt><dd class="commerce-id">{{ campaign.destination_url }}</dd></div></dl><details class="audit-request-details" open><summary>Ad creative included in this approval</summary>{% for ad in campaign.creative %}<div class="campaign-creative"><strong>{{ ad.headline }}</strong><p>{{ ad.body }}</p><p class="field-hint">Call to action: {{ ad.call_to_action }}</p></div>{% endfor %}</details><p class="field-hint">{{ campaign.start_condition }} {{ campaign.result_caveat }}</p><div class="campaign-rationale"><p><strong>Why this campaign:</strong> {{ campaign.rationale }}</p><details class="audit-request-details"><summary>Evidence, alternative &amp; decision impact</summary><ul>{% for point in campaign.evidence %}<li>{{ point }}</li>{% endfor %}</ul><p><strong>Alternative:</strong> {{ campaign.alternative }}</p><p><strong>If declined:</strong> {{ campaign.decline_outcome }}</p><p><strong>Measure:</strong> {{ campaign.metrics|join(', ') }}. Results are uncertain.</p></details></div></section>""",
    'commerce/feedback': """{% if commerce_feedback and commerce_feedback.section == feedback_section %}{% if commerce_feedback.notice %}<div class="notice success" role="status">{{ commerce_feedback.notice }}</div>{% endif %}{% if commerce_feedback.failure %}<div class="notice error" role="alert">{{ commerce_feedback.failure }}</div>{% endif %}{% endif %}""",
    'commerce/style': """<style>
.commerce-stack > * + * { margin-top: 22px; }
.commerce-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 22px; align-items: start; }
.commerce-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 24px; }
.commerce-summary dt { color: var(--muted); font-size: 12px; }
.commerce-summary dd { margin: 3px 0 0; font-weight: 600; }
.commerce-output { white-space: pre-wrap; font-family: inherit; overflow-wrap: anywhere; line-height: 1.65; }
.commerce-quote { padding: 18px; border: 1px solid var(--line); border-radius: 12px; background: var(--canvas); }
.commerce-quote > * + * { margin-top: 14px; }
.commerce-checkout { max-width: 760px; margin-inline: auto; }
.campaign-details{font-size:13px}.campaign-details details{margin-top:12px}.campaign-details summary{cursor:pointer}.campaign-creative{padding:10px;background:var(--canvas);border-radius:6px;margin-top:8px}.campaign-creative p{margin:4px 0}.campaign-rationale p{line-height:1.5}.commerce-id { font-size: 12px; word-break: break-all; }
.commerce-checks { padding-left: 22px; }
.commerce-checks li + li { margin-top: 7px; }
@media (max-width: 850px) { .commerce-grid { grid-template-columns: 1fr; } }
@media (max-width: 440px) { .commerce-summary { grid-template-columns: 1fr; } }

.commerce-setup-list { list-style: none; padding: 0; margin: 0; }
.commerce-setup-list li { display: flex; align-items: start; justify-content: space-between; gap: 16px; padding: 15px 0; border-bottom: 1px solid var(--line); }
.commerce-setup-list li > div { min-width: 0; }
.commerce-setup-list li > a { flex-shrink: 0; font-size: 13px; }
.commerce-setup-status { display: block; font-size: 12px; margin-top: 3px; }
.commerce-setup-status.is-ready { color: var(--green); }
.commerce-setup-status.needs-action { color: #895520; }
.commerce-progress { list-style: none; display: flex; flex-wrap: wrap; gap: 8px; padding: 0; }
.commerce-progress li { padding: 7px 10px; border-radius: 7px; background: var(--canvas); color: var(--muted); font-size: 12px; }
.commerce-progress li.done { color: var(--green); }
.commerce-progress li.current { background: var(--green); color: white; font-weight: 600; }
#task-history > summary, .commerce-new-task > summary { padding: 20px; font-weight: 600; cursor: pointer; }
#task-brief-form input, #task-brief-form textarea { width: 100%; }
#commerce-start:disabled { cursor: not-allowed; }
@media (max-width: 600px) { .commerce-setup-list li { flex-direction: column; gap: 8px; } }

</style>""",
    'commerce/budget': """<div class="panel section-anchor" id="purchase-controls"><p class="kicker">PURCHASE BOUNDARIES</p><h3>Agent purchase allowance</h3>
<p>This allowance limits the agent's total merchant purchases. It is <strong>not a wallet or service credit</strong>. Every purchase also needs your Habitat approval and separate buyer checkout consent.</p>
<form method="post" action="/instances/{{ d.instance_id }}/commerce/settings" class="form-grid"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="expected_version" value="{{ d.policy.version }}">
<label class="capability-option"><input type="checkbox" name="enabled"{% if d.policy.enabled %} checked{% endif %}><span class="capability-copy"><span class="capability-title">Enable purchases</span><span class="capability-description">Buy approved resources or fund advertising campaigns.</span></span></label>
<div class="field"><label for="purchase-limit">Total purchase limit (USD)</label><input id="purchase-limit" type="text" inputmode="decimal" name="purchase_limit" value="{{ money(d.policy.limit_minor) }}" aria-describedby="purchase-limit-hint"><p class="field-hint" id="purchase-limit-hint">Spent ${{ money(d.policy.spent_minor) }} · held ${{ money(d.policy.held_minor) }}. Each proposal shows its exact price and scope before approval.</p></div><button type="submit" class="secondary">Save purchase controls</button></form>
</div>""",
    'commerce/funding': """<section class="section-anchor commerce-stack" id="funding">{% with feedback_section="funding" %}{% include "commerce/feedback" %}{% endwith %}<div class="section-heading"><div><p class="kicker">MONEY TO RUN YOUR AGENT</p><h2>Funding</h2><p class="muted">Service credit pays for inference. Purchase allowance is a separate policy limit.</p></div></div><div class="stat-grid" aria-label="Separate service credit and merchant spending">
<div class="stat-card"><span class="stat-label">Service credit</span><strong class="stat-value">${{ credit(d.balance_micro_usd) }}</strong><span class="stat-note">Allocated to this agent · inference only</span></div>
<div class="stat-card"><span class="stat-label">Purchase allowance available</span><strong class="stat-value">${{ money(d.policy.available_minor) }}</strong><span class="stat-note">Policy limit, not money · ${{ money(d.policy.held_minor) }} held</span></div>
<div class="stat-card"><span class="stat-label">Merchant purchases</span><strong class="stat-value">${{ money(d.policy.spent_minor) }}</strong><span class="stat-note">Buyer → seller · separate from service credit</span></div>
</div>
<section class="card"><div class="card-header"><div><p class="kicker">FUND THE AGENT</p><h3>Fund with PayPal</h3></div></div><div class="card-body">
<p>{% if d.payment_transport == 'paypal_sandbox' %}Authorize funding on PayPal using your Sandbox buyer account. Your amount and agent are carried into checkout.{% elif d.payment_profile %}<strong>PayPal · {{ d.payment_profile.buyer_label }}</strong> · remembered for your account. You can change the account at checkout.{% else %}Choose a PayPal account at your first checkout. We will remember it across your agents.{% endif %}</p>
<p>A top-up pays <strong>Habitat</strong> for service credit. Completed payment adds credit directly to this agent. Pending or cancelled payments add nothing.</p>
<form method="post" action="/instances/{{ d.instance_id }}/commerce/topups"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="request_id" value="{{ request_id }}-topup"><div class="button-row">{% for amount in d.topup_amounts_minor %}<button class="{{ 'primary' if loop.first else 'secondary' }}" type="submit" name="amount_minor" value="{{ amount }}">Add ${{ money(amount) }} with PayPal</button>{% endfor %}</div></form>
<p class="field-hint">{% if d.payment_transport == 'paypal_sandbox' %}PayPal Sandbox · test funds only. Every payment requires your consent; Habitat does not store a reusable payment authorization.{% else %}Your amount and agent are carried into checkout. Each payment needs your authorization; remembering an account does not authorize future charges.{% endif %}</p>
</div></section>
<section class="card"><div class="card-header"><div><p class="kicker">SAVED PAYMENT HISTORY</p><h3>Orders &amp; receipts</h3></div></div><div class="card-body">
{% if d.orders %}<div class="table-wrap"><table class="data-table"><caption class="field-hint">Payment history for this agent.</caption><thead><tr><th scope="col">Purpose</th><th scope="col">Recipient</th><th scope="col">Amount</th><th scope="col">State</th><th scope="col">Details</th></tr></thead><tbody>{% for order in d.orders %}<tr><td>{{ 'Service credit' if order.purpose == 'service_topup' else 'Agent purchase' }}</td><td>{{ order.merchant_name }}</td><td>${{ money(order.amount_minor) }}</td><td>{{ order.state }}</td><td><a href="/commerce/orders/{{ order.id }}">{{ 'View receipt' if order.state == 'completed' else 'Review order' }}</a></td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="muted">Your completed, pending and cancelled orders will appear here.</p>{% endif %}
<p class="field-hint">Completed top-ups issue service credit once. Completed purchases count against purchase allowance and never debit service credit.</p>
</div></section></section>""",
    'commerce/task': """<section class="section-anchor commerce-stack" id="task">{% with feedback_section="task" %}{% include "commerce/feedback" %}{% endwith %}
<div class="section-heading"><div><p class="kicker">YOUR AGENT'S WORK</p><h2>Marketing launch kit</h2><p class="muted">Turn your product, audience and goal into launch copy using an approved template.</p></div></div>

{% if d.attention_count or tool_attention_count %}<div class="notice info"><strong>Needs your attention</strong><p>{% if d.attention_count %}{{ d.attention_count }} task{{ 's' if d.attention_count != 1 else '' }} waiting for a decision or next step. {% endif %}{% if tool_attention_count %}<a href="#tool-confirmations">{{ tool_attention_count }} separate tool confirmation{{ 's' if tool_attention_count != 1 else '' }}</a>.{% endif %}</p>{% if d.active_run_count > 1 %}<p>Older unfinished tasks are in <a href="#task-history">task history</a>. Resolve those before starting another.</p>{% endif %}</div>{% endif %}
{% if d.current_run %}{% with run=d.current_run, historical=false %}{% include "commerce/run" %}{% endwith %}{% endif %}
{% if not d.active_run_count %}
{% if d.current_run %}<details class="card commerce-new-task" id="new-task"><summary>Set up a fresh task</summary><div class="card-body">{% include "commerce/brief" %}</div></details>{% else %}<section class="card" id="new-task"><div class="card-header"><div><p class="kicker">1 · DESCRIBE THE OUTCOME</p><h3>Your task brief</h3></div></div><div class="card-body">{% include "commerce/brief" %}</div></section>{% endif %}
{% endif %}
{% set setup_readiness = d.current_readiness if d.active_run_count else d.readiness %}
<section class="section-anchor" id="setup">{% with feedback_section="setup" %}{% include "commerce/feedback" %}{% endwith %}<div class="card" id="task-setup"><div class="card-header"><div><p class="kicker">{{ 'AGENT READINESS' if d.active_run_count else 'NEXT TASK · SETUP' if d.current_run else '2 · PREPARE YOUR AGENT' }}</p><h3>{{ ('Ready for the next step' if d.active_run_count else 'Setup is ready') if setup_readiness.ready else 'Review these controls' if d.active_run_count else 'Setup for a fresh task' if d.current_run else 'Complete setup' }}</h3></div><span class="status-badge {{ 'active' if setup_readiness.ready else 'draft' }}">{{ 'Ready' if setup_readiness.ready else 'Action needed' }}</span></div><div class="card-body">
<p><strong>Service credit: ${{ credit(d.balance_micro_usd) }}</strong> · <a href="#funding">Funding and receipts</a></p>
<p>Set the permissions and spending boundaries, then fund inference. These settings stay with the agent and are checked again before work.</p>
<ul class="commerce-setup-list">
{% set groups = [('Inference permission', ['capability_disabled'], 'capabilities', 'Review inference permission'), ('Resource budgets', ['budget_exhausted', 'budget_unavailable', 'price_unavailable', 'reconciliation_pending'], 'budgets', 'Review resource budgets'), ('Purchase permission and allowance', ['purchases_disabled', 'purchase_limit_exceeded'], 'purchase-controls', 'Review purchase controls'), ('Service credit for inference', ['credit_insufficient'], 'funding', 'Add service credit'), ('Agent activation and controls', ['instance_not_active', 'gate_unresolved'], 'overview', 'Review agent controls'), ('Payment status', ['payment_unresolved'], 'funding', 'Review orders and receipts')] %}
{% for title, reasons, target, action in groups %}{% set check = namespace(blocked=false) %}{% for blocker in setup_readiness.blockers if blocker.reason in reasons %}{% set check.blocked=true %}{% endfor %}
<li><div><strong>{{ title }}</strong><span class="commerce-setup-status {{ 'needs-action' if check.blocked else 'is-ready' }}">{{ 'Already paid' if title == 'Purchase permission and allowance' and d.current_run and d.current_run.state == 'ready_to_resume' else 'Needs attention' if check.blocked else 'Ready' }}</span>{% for blocker in setup_readiness.blockers if blocker.reason in reasons %}<p class="field-hint">{{ blocker.message }}</p>{% endfor %}</div><a href="#{{ target }}">{{ action }}</a></li>{% endfor %}
</ul>
<p class="field-hint">Service credit pays Habitat for inference. Purchase allowance is a policy limit; buyer checkout pays the seller separately.</p>
{% if not d.active_run_count %}
{% if d.inference.estimated_step_micro_usd is not none %}<p>Expected task: two inference steps at <strong>${{ credit(d.inference.measured_step_micro_usd) }} each</strong>, plus a <strong>${{ money(d.catalog.amount_minor) }} template</strong> if you approve it. Each inference step reserves up to ${{ credit(d.inference.estimated_step_micro_usd) }}.</p>{% endif %}
<form method="post" action="/instances/{{ d.instance_id }}/commerce/runs" id="commerce-run-form"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="request_id" value="{{ request_id }}-run">{% for field, value in d.draft_brief.items() %}<input type="hidden" name="{{ field }}" value="{{ value }}">{% endfor %}<button class="primary" type="submit" id="commerce-start" data-ready="{{ 'true' if setup_readiness.ready else 'false' }}"{% if not setup_readiness.ready %} disabled{% endif %}>Start launch-kit task</button><p class="field-hint" id="commerce-start-hint">{{ 'The saved brief above will be used. Starting charges the planning step; it never approves a purchase.' if setup_readiness.ready else 'Complete the setup items above. No work has started and no credit has been charged for a new task.' }}</p></form>
{% endif %}
</div></div></section>
{% if d.history_runs %}<details class="card" id="task-history"><summary>Task history · {{ d.history_runs|length }} earlier attempt{{ 's' if d.history_runs|length != 1 else '' }}</summary><div class="card-body commerce-stack">{% for run in d.history_runs %}{% with historical=true %}{% include "commerce/run" %}{% endwith %}{% endfor %}</div></details>{% endif %}
</section>""",
    'commerce/brief': """<p>Describe the product you want to introduce, who it is for, and what the launch should achieve. Your agent will use these details in its plan and result.</p>
<form method="post" action="/instances/{{ d.instance_id }}/commerce/brief" id="task-brief-form" class="form-grid"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="expected_version" value="{{ d.policy.version }}">
<div class="field"><label for="brief-product">Product or service</label><input id="brief-product" name="product_name" value="{{ d.draft_brief.product_name }}" required maxlength="120"></div>
<div class="field"><label for="brief-audience">Who is it for?</label><input id="brief-audience" name="audience" value="{{ d.draft_brief.audience }}" required maxlength="240"></div>
<div class="field"><label for="brief-goal">What should this launch achieve?</label><textarea id="brief-goal" name="goal" required maxlength="600" rows="3">{{ d.draft_brief.goal }}</textarea></div>
<div class="button-row"><button type="submit" class="secondary">Save task brief</button><a href="#setup">Continue to setup</a></div><p class="field-hint">{{ 'Your brief is saved.' if d.brief_saved else 'An example brief is filled in. You can use it as-is or save your own.' }} Save edits before leaving this section. Saving does not start work or use credit.</p></form>""",
    'commerce/run': """{% set p = run.purchase %}{% set active = run.state in ('awaiting_approval', 'awaiting_checkout', 'payment_pending', 'ready_to_resume') %}
<section class="card section-anchor" id="run-{{ run.id }}"><div class="card-header"><div><p class="kicker">{{ 'EARLIER TASK' if historical else 'CURRENT TASK' }} · {{ run.brief.product_name }}</p><h3>{{ run_label(run.state) }}</h3></div><span class="status-badge {{ 'active' if run.state == 'completed' else 'draft' }}">{{ run.state|replace('_', ' ') }}</span></div><div class="card-body">
<ol class="commerce-progress" aria-label="Task progress"><li class="done">Plan ready</li><li class="{{ 'current' if run.state == 'awaiting_approval' else 'done' if run.state in ('awaiting_checkout', 'payment_pending', 'ready_to_resume', 'completed') else '' }}"{% if run.state == 'awaiting_approval' %} aria-current="step"{% endif %}>Your approval</li><li class="{{ 'current' if run.state in ('awaiting_checkout', 'payment_pending') else 'done' if run.state in ('ready_to_resume', 'completed') else '' }}"{% if run.state in ('awaiting_checkout', 'payment_pending') %} aria-current="step"{% endif %}>Buyer checkout</li><li class="{{ 'current' if run.state == 'ready_to_resume' else 'done' if run.state == 'completed' else '' }}"{% if run.state == 'ready_to_resume' %} aria-current="step"{% endif %}>Delivery &amp; resume</li><li class="{{ 'done' if run.state == 'completed' else '' }}"{% if run.state == 'completed' %} aria-current="step"{% endif %}>Result</li></ol>
<p><strong>Your goal:</strong> {{ run.brief.goal }}<br><span class="muted">For {{ run.brief.audience }}.</span></p>
{% if run.output %}<div class="panel"><p class="kicker">YOUR RESULT</p><h3>Your marketing launch kit</h3><p class="commerce-output">{{ result_text(run.output) }}</p></div>{% endif %}
{% if p %}<div class="commerce-quote"><h4>{{ 'Purchased template' if p.state == 'paid' else 'Purchase proposal' }}</h4><p>Use this licensed template to organize the campaign brief, launch copy and call to action for <strong>{{ run.brief.product_name }}</strong>.</p>
<dl class="commerce-summary"><div><dt>Seller</dt><dd>{{ p.quote.merchant_name }}</dd></div><div><dt>Item</dt><dd>{{ p.quote.item_name }}</dd></div><div><dt>Total including all fees</dt><dd>${{ money(p.quote.amount_minor) }} {{ p.quote.currency }}</dd></div><div><dt>License</dt><dd>{{ license_label(p.quote.license) }}</dd></div><div><dt>Funding source</dt><dd>PayPal → seller</dd></div><div><dt>Asset recipient</dt><dd>This agent: {{ detail.snapshot.name }}</dd></div></dl>
<details><summary>Exact quote identity and expiry</summary><p>SKU {{ p.quote.offer_id }} · quantity {{ p.quote.quantity }} · quote version {{ p.quote.version }}</p><p class="commerce-id">{{ p.quote_digest }}</p><p class="field-hint">Expires: {{ p.expires_at }}. Recipient: {{ p.quote.recipient }}. Approval applies only to this seller, item, license and total.</p></details>
{% if p.state == 'awaiting_approval' %}<p><strong>Your decision:</strong> allow this exact purchase, or decline to stop this task. No merchant payment has been made.</p><form method="post" action="/commerce/purchases/{{ p.id }}/decision"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="quote_digest" value="{{ p.quote_digest }}"><div class="button-row"><button class="primary" type="submit" name="decision" value="approve">Approve and continue to PayPal</button><button class="secondary" type="submit" name="decision" value="decline">Decline purchase</button></div></form><p class="field-hint">Approve this exact proposal to open its prepared PayPal checkout. Your account choice and order details carry forward; payment still needs your consent.</p>
{% elif p.state in ('awaiting_checkout', 'payment_pending') %}<p class="notice info">{% if p.state == 'payment_pending' %}Payment is pending. The purchase allowance remains held. Resolve this same order; the task cannot use an asset that has not been delivered.{% else %}Your Habitat approval is recorded. Next, review the seller and total in buyer checkout. Approval alone does not pay the seller.{% endif %}</p><a class="button primary" href="/commerce/orders/{{ p.order_id }}">{{ 'Resolve pending checkout' if p.state == 'payment_pending' else 'Continue to PayPal' }}</a>
{% elif p.state == 'paid' %}<p class="notice success">Payment completed. The template was delivered.</p>{% if p.fulfillment %}<details><summary>View delivered template</summary><h4>{{ p.fulfillment.name }}</h4><p class="commerce-output">{{ p.fulfillment.content }}</p><p class="field-hint">{{ license_label(p.fulfillment.license) }}</p></details>{% endif %}{% set paid_order = d.orders|selectattr("id", "equalto", p.order_id)|first %}{% if paid_order and paid_order.capture_id %}<details><summary>Payment receipt</summary><p>{{ paid_order.merchant_name }} · ${{ money(paid_order.amount_minor) }} {{ paid_order.currency }}</p><p class="commerce-id">{{ paid_order.capture_id }}</p>{% if paid_order.buyer_label %}<p>PayPal · {{ paid_order.buyer_label }}</p>{% endif %}</details>{% endif %}<a href="/commerce/orders/{{ p.order_id }}">View payment receipt</a>
{% else %}<p class="notice info">{% if p.state == 'declined' %}You declined this proposal.{% elif p.state == 'cancelled' %}Buyer checkout was cancelled.{% else %}This proposal expired.{% endif %} No merchant payment was made, and its purchase hold is released. This attempt has stopped; any planning usage already incurred remains recorded.</p>{% endif %}
</div>{% endif %}
{% if run.state == 'ready_to_resume' %}<div class="panel"><h4>Review the delivery, then continue</h4><p>The template is available. Payment never restarts your agent automatically.</p><form method="post" action="/commerce/runs/{{ run.id }}/resume"><input type="hidden" name="csrf_token" value="{{ csrf }}"><button class="primary" type="submit">Resume task with purchased template</button></form><p class="field-hint">Resuming charges the final inference step and rechecks lifecycle, permissions, budgets and service credit. <a href="#setup">Review readiness</a>.</p></div>{% endif %}
<p class="field-hint">Inference charge: <strong>${{ credit(run.inference_cost_micro_usd) }}</strong>{% if run.token_usage %} · {{ run.token_usage.input_tokens }} input / {{ run.token_usage.output_tokens }} output tokens{% endif %}. Merchant spending: <strong>${{ money(p.quote.amount_minor if p and p.state == 'paid' else 0) }}</strong>, separate from service credit.</p>
{% if not active and not historical %}<p><a class="button secondary" href="#new-task">Start a fresh task</a></p><p class="field-hint">A fresh task keeps your saved brief, charges a new planning step and requires a new purchase approval. The earlier attempt stays in history.</p>{% endif %}
</div></section>""",
    'commerce/script': """function revealCommerceAnchor() {
    var id = window.location.hash.slice(1);
    var target = id && document.getElementById(id);
    if (!target) return;
    var node = target;
    while (node) { if (node.tagName === "DETAILS") node.open = true; node = node.parentElement; }
  }
  revealCommerceAnchor();
  if (!window.commerceHashBound) { window.addEventListener("hashchange", revealCommerceAnchor); window.commerceHashBound = true; }
  var briefForm = document.getElementById("task-brief-form");
  var commerceStart = document.getElementById("commerce-start");
  if (briefForm && commerceStart) {
    var fields = Array.from(briefForm.querySelectorAll("[name='product_name'], [name='audience'], [name='goal']"));
    var hint = document.getElementById("commerce-start-hint");
    var originalHint = hint.textContent;
    function updateBriefStart() {
      var dirty = fields.some(function (field) { return field.value !== field.defaultValue; });
      commerceStart.disabled = dirty || commerceStart.dataset.ready !== "true";
      hint.textContent = dirty ? "Save your task brief before starting. The saved version is still unchanged." : originalHint;
    }
    briefForm.oninput = updateBriefStart;
    updateBriefStart();
  }
""",
    'checkout': """{% extends "base" %}{% set page_key = "instance" %}
{% block eyebrow %}PAYMENT{% endblock %}{% block subtitle %}{{ "Your payment is complete. The receipt is saved with your agent." if order.state == "completed" else "This payment was cancelled. Your agent and task are preserved." if order.state == "cancelled" else "Your order is ready. Authorize this payment, then return to your agent." }}{% endblock %}
{% block header_actions %}{% if workflow_job %}<a class="button secondary" href="/audit?view=purchases&amp;instance_id={{ order.instance_id }}#purchase-{{ purchase.id }}">Back to purchase review</a>{% else %}<a class="button secondary" href="/instances/{{ order.instance_id }}#{{ 'run-' ~ purchase.run_id if purchase else 'setup' }}">{{ 'Back to task' if purchase else 'Back to setup' }}</a>{% endif %}{% endblock %}
{% block body %}{% if request_url|default('') %}<p class="field-hint"><a href="{{ request_url }}">← Back to this request</a> · Payment authorization</p>{% endif %}<style>
.paypal-brand { display: flex; align-items: center; gap: 14px; margin-bottom: 9px; }
.paypal-brand img { display: block; width: 88px; height: auto; }
.paypal-brand span { color: var(--muted); font-size: 12px; font-weight: 600; }
.commerce-checkout .paypal-pay { background: #ffd140; border-color: #ffd140; color: #003087; border-radius: 999px; padding-inline: 24px; font-weight: 700; }
.commerce-checkout .paypal-pay:hover { background: #f3c644; border-color: #f3c644; }
.checkout-control-note { border-left: 3px solid var(--line); padding-left: 10px; }
.commerce-stack > * + * { margin-top: 22px; }
.commerce-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 22px; align-items: start; }
.commerce-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 24px; }
.commerce-summary dt { color: var(--muted); font-size: 12px; }
.commerce-summary dd { margin: 3px 0 0; font-weight: 600; }
.commerce-output { white-space: pre-wrap; font-family: inherit; overflow-wrap: anywhere; line-height: 1.65; }
.commerce-quote { padding: 18px; border: 1px solid var(--line); border-radius: 12px; background: var(--canvas); }
.commerce-quote > * + * { margin-top: 14px; }
.commerce-checkout { max-width: 760px; margin-inline: auto; }
.campaign-details{font-size:13px}.campaign-details details{margin-top:12px}.campaign-details summary{cursor:pointer}.campaign-creative{padding:10px;background:var(--canvas);border-radius:6px;margin-top:8px}.campaign-creative p{margin:4px 0}.campaign-rationale p{line-height:1.5}.commerce-id { font-size: 12px; word-break: break-all; }
.commerce-checks { padding-left: 22px; }
.commerce-checks li + li { margin-top: 7px; }
@media (max-width: 850px) { .commerce-grid { grid-template-columns: 1fr; } }
@media (max-width: 440px) { .commerce-summary { grid-template-columns: 1fr; } }
</style>
<div class="commerce-stack commerce-checkout">
{% if failure %}<div class="notice error" role="alert">{{ failure }}</div>{% endif %}
{% if paypal_return == 'returned' and order.state not in ('completed', 'cancelled') %}<div class="notice info" role="status"><strong>Returned from PayPal</strong><p>Finish this payment below. Habitat verifies PayPal approval and the exact amount before recording a completed payment.</p></div>{% elif paypal_return == 'cancelled' and order.state not in ('completed', 'cancelled') %}<div class="notice info" role="status"><strong>Checkout interrupted</strong><p>No completed payment has been recorded here. This order and any purchase hold are preserved. Continue the same checkout or check its payment status.</p></div>{% endif %}
<section class="card"><div class="card-header"><div><div class="paypal-brand"><img src="/static/brand/paypal-logo-black.png" alt="PayPal" width="2497" height="839"><span>{{ ('Sandbox receipt · test funds' if order.state == 'completed' else 'Sandbox checkout · test funds') if order.is_paypal_sandbox else ('PayPal payment receipt' if order.state == 'completed' else 'PayPal checkout') }}</span></div><h2>{{ 'Payment completed' if order.state == 'completed' else 'Cancelled payment' if order.state == 'cancelled' else 'Fund your agent' if order.purpose == 'service_topup' else 'Authorize your purchase' }}</h2></div><span class="status-badge draft">{{ order.state }}</span></div><div class="card-body">
<dl class="commerce-summary"><div><dt>Recipient merchant</dt><dd>{{ order.merchant_name }}</dd></div><div><dt>Total</dt><dd>${{ money(order.amount_minor) }} {{ order.currency }}</dd></div><div><dt>Purpose</dt><dd>{{ 'Service credit for inference and compute' if order.purpose == 'service_topup' else 'Prepaid advertising campaign' if purchase and purchase.quote.campaign else 'Owner-approved template purchase' }}</dd></div><div><dt>Payment method</dt><dd>PayPal</dd></div></dl>
{% if order.purpose == 'service_topup' %}<p class="field-hint checkout-control-note">AICL gates resource use against your budgets and permissions. Agent purchases use separate owner-approved PayPal payments.</p>{% endif %}
{% if purchase %}{% set ad_purchase = purchase.quote.campaign|default(none) %}<p><strong>{{ purchase.quote.item_name }}</strong> · for {{ run.brief.product_name }}</p><p class="field-hint">{{ "The approved purchase and its payment receipt are saved." if order.state == "completed" else "Your Habitat approval is recorded. Your task brief and purchase details are already saved." if order.state == "cancelled" else "Your Habitat approval is recorded. Authorize this seller payment below; your task brief and purchase details are already saved." }}</p>{% if ad_purchase %}{% with campaign=ad_purchase %}{% include 'commerce/campaign_details' %}{% endwith %}{% else %}<details><summary>Purchase details</summary><p>{{ run.brief.goal }}</p><p>{{ purchase.quote.offer_id }} · quantity {{ purchase.quote.quantity }} · quote version {{ purchase.quote.version }}</p><p>{{ license_label(purchase.quote.license) }}</p><p>Asset recipient: <span class="commerce-id">{{ purchase.quote.recipient }}</span></p></details>{% endif %}{% endif %}
{% if workflow_job %}<div class="commerce-job-context"><p><strong>Supports deliverable:</strong> {{ workflow_job.deliverable_name }} · {{ workflow_job.agent_name }}</p><p class="field-hint">{{ workflow_job.deliverable_description }}</p><a href="/audit/jobs/{{ workflow_job.id }}">View source job</a></div><div class="notice info"><strong>After this purchase</strong><p>{{ ("Process campaign activation now; reporting follows the schedule." if workflow_job.continuation == "now" else "Start campaign processing at the next eligible scheduled run.") if ad_purchase else ("Continue the waiting work as soon as payment and delivery complete." if workflow_job.continuation == "now" else "Continue the waiting work at the next eligible scheduled run.") }} Current funding, permissions and schedule controls still apply. <a href="/audit?view=purchases&amp;instance_id={{ order.instance_id }}">Return to purchase requests</a></p></div>{% endif %}
{% if order.buyer_label and not order.is_paypal_sandbox %}<div class="commerce-quote"><strong>PayPal · {{ order.buyer_label }}</strong><p class="field-hint">{{ 'This account is selected for this order. Each seller payment needs your consent.' if order.buyer_can_change else 'This order keeps the account selected when payment started.' }}</p>
{% if order.buyer_can_change %}<details><summary>Change account</summary><form method="post" action="/commerce/orders/{{ order.id }}/buyer"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="expected_buyer_id" value="{{ order.buyer_id }}"><div class="field"><label for="change-buyer">PayPal account</label><select id="change-buyer" name="buyer_id" required>{% for buyer_id, label in buyer_choices.items() %}<option value="{{ buyer_id }}"{% if buyer_id == order.buyer_id %} selected{% endif %}>{{ label }}</option>{% endfor %}</select></div><p class="field-hint">Remember this choice for future checkouts across your agents. Existing payments keep their original account. This does not make a payment.</p><button class="secondary" type="submit">Use this account</button></form></details>{% endif %}</div>{% endif %}

{% if order.state in ('created', 'pending') %}
{% if order.payment_phase in ('inflight', 'unknown') %}<div class="notice info" role="status"><strong>Payment result needs checking</strong><p>The payment may have completed at the payment provider. Habitat has kept this order and any purchase hold while it confirms the outcome. Checking status does not submit another payment.</p></div>
{% else %}
{% if order.state == 'pending' %}<p class="notice info">Payment confirmation is pending. No completed credit or purchase has been recorded. Continue with this same order to resolve it.</p>{% endif %}
<p>Completing this payment{% if order.purpose == 'service_topup' %} credits this agent once.{% elif ad_purchase %} prepays this exact campaign with {{ ad_purchase.platform }}. Ad delivery and measured spend follow separately; inference credit is unchanged.{% else %} pays the template seller. It does not use the agent's service credit.{% endif %}</p>
{% if order.is_paypal_sandbox %}
<p class="field-hint">PayPal Sandbox · test funds only. Sign in with your Sandbox buyer account on PayPal; Habitat does not collect your PayPal password.</p>
{% if order.can_begin_paypal %}<form method="post" action="/commerce/orders/{{ order.id }}/paypal-start"><input type="hidden" name="csrf_token" value="{{ csrf }}"><button class="primary paypal-pay" type="submit">Continue to PayPal · ${{ money(order.amount_minor) }}</button></form><form method="post" action="/commerce/orders/{{ order.id }}/paypal-cancel"><input type="hidden" name="csrf_token" value="{{ csrf }}"><button class="ghost" type="submit">Cancel payment</button></form>
{% elif order.can_complete_paypal %}
{% if paypal_return == 'returned' %}{% with payment_button_class='primary paypal-pay' %}{% include 'commerce/paypal_finish' %}{% endwith %}{% endif %}
{% if order.approval_url %}<a class="button {{ 'secondary' if paypal_return == 'returned' else 'primary paypal-pay' }}" href="{{ order.approval_url }}">{{ 'Return to PayPal' if paypal_return == 'returned' else 'Continue PayPal checkout' }}</a>{% endif %}
{% if paypal_return != 'returned' %}<details{% if paypal_approval_expired %} open{% endif %}><summary>{{ 'Renew expired purchase approval' if paypal_approval_expired else 'Already approved in PayPal?' }}</summary><p class="field-hint">Finish this same order. PayPal must confirm your approval before Habitat can capture payment.</p>{% with payment_button_class='secondary' %}{% include 'commerce/paypal_finish' %}{% endwith %}</details>{% endif %}
{% endif %}
{% else %}
<form method="post" action="/commerce/orders/{{ order.id }}/checkout"><input type="hidden" name="csrf_token" value="{{ csrf }}">
{% if order.buyer_id %}<input type="hidden" name="buyer_id" value="{{ order.buyer_id }}">{% elif order.buyer_required %}<div class="field"><label for="checkout-buyer">PayPal account</label><select id="checkout-buyer" name="buyer_id" required><option value="">Choose an account</option>{% for buyer_id, label in buyer_choices.items() %}<option value="{{ buyer_id }}">{{ label }}</option>{% endfor %}</select><p class="field-hint">We will remember this account across your agents. Each payment still needs your authorization.</p></div>{% endif %}
<div class="button-row"><button class="primary paypal-pay" type="submit" name="outcome" value="complete">Pay ${{ money(order.amount_minor) }} with PayPal</button><button class="ghost" type="submit" name="outcome" value="cancel" formnovalidate>Cancel payment</button></div><p class="field-hint">Demo checkout — no real charges.</p>{% if order.state == 'created' %}<details><summary>Payment options</summary><button class="secondary" type="submit" name="outcome" value="pending">Mark as pending</button></details>{% endif %}</form>
{% endif %}
{% endif %}
{% if order.can_reconcile %}<form method="post" action="/commerce/orders/{{ order.id }}/reconcile"><input type="hidden" name="csrf_token" value="{{ csrf }}"><button class="secondary" type="submit">Check payment status</button></form>{% endif %}
{% elif order.state == 'completed' %}<div class="notice success" role="status"><strong>Payment completed</strong><p>{% if order.purpose == 'service_topup' %}The service credit is allocated to your agent.{% elif ad_purchase %}The campaign is funded. Payment is not proof of ad delivery; track campaign activity and consumed spend in Audit. <a href="/audit?view=campaigns&amp;instance_id={{ order.instance_id }}">View campaign</a>{% elif workflow_job %}The purchase receipt and resource are saved. Review the continuation status in Audit.{% elif run.state == 'completed' %}The purchase receipt and delivered template are saved. Your task is completed.{% else %}The purchase receipt and delivered template are saved. Return to the task to resume it explicitly.{% endif %}</p></div><dl class="commerce-summary"><div><dt>Payment receipt</dt><dd><details><summary>View receipt ID</summary><span class="commerce-id">{{ order.capture_id }}</span></details></dd></div><div><dt>Paid to</dt><dd>{{ order.merchant_name }}</dd></div></dl>{% if workflow_job %}<a class="button primary" href="/audit?view=purchases&amp;instance_id={{ order.instance_id }}">Return to Audit</a>{% else %}<a class="button primary" href="/instances/{{ order.instance_id }}#{{ 'run-' ~ purchase.run_id if purchase else 'setup' }}">{{ ('View completed task' if run.state == 'completed' else 'Return and resume task') if purchase else 'Return to funded agent' }}</a>{% endif %}
{% elif order.state == 'cancelled' %}<p class="notice info" role="status">Payment cancelled. No credit or merchant payment was recorded.</p>{% if workflow_job %}<a class="button secondary" href="/audit?view=purchases&amp;instance_id={{ order.instance_id }}">Return to Audit</a>{% else %}<a class="button secondary" href="/instances/{{ order.instance_id }}#{{ 'run-' ~ purchase.run_id if purchase else 'setup' }}">Return to agent</a>{% endif %}{% endif %}
<details><summary>Order identity</summary><p class="commerce-id">Habitat order: {{ order.id }}</p>{% if order.provider_order_id %}<p class="commerce-id">Provider order: {{ order.provider_order_id }}</p>{% endif %}{% if order.payment_transport in ('http_mock', 'paypal_sandbox') %}<p>Payment status: {{ order.payment_phase|replace('_', ' ') }}</p>{% endif %}{% if order.is_paypal_sandbox %}<p class="field-hint">PayPal Sandbox · test funds only.</p>{% endif %}<p class="field-hint">Created {{ order.created_at }} · recipient {{ order.merchant_id }}. Reopening this order does not create another payment.</p></details>
</div></section></div>{% endblock %}""",
}


def money(minor: int) -> str:
    whole, fraction = divmod(int(minor), 100)
    return f"{whole}.{fraction:02d}"


def credit(micro_usd: int) -> str:
    whole, fraction = divmod(int(micro_usd), 1_000_000)
    return f"{whole}." + f"{fraction:06d}".rstrip("0").ljust(2, "0")


def run_label(state: str) -> str:
    return {
        "awaiting_approval": "Your purchase approval is needed",
        "awaiting_checkout": "Continue with buyer checkout",
        "payment_pending": "Waiting for a payment result",
        "ready_to_resume": "Template delivered — ready to resume",
        "completed": "Launch kit completed",
        "declined": "Purchase declined",
        "cancelled": "Purchase cancelled",
        "expired": "Purchase quote expired",
    }.get(state, "Launch-kit task")


def readiness_destination(reason: str) -> tuple[str, str]:
    return {
        "instance_not_active": ("overview", "Review lifecycle"),
        "capability_disabled": ("capabilities", "Enable inference"),
        "credit_insufficient": ("funding", "Add service credit"),
        "budget_exhausted": ("budgets", "Set budget limits"),
        "budget_unavailable": ("budgets", "Review budget limits"),
        "purchases_disabled": ("purchase-controls", "Set purchase allowance"),
        "purchase_limit_exceeded": ("purchase-controls", "Review purchase allowance"),
        "reconciliation_pending": ("activity", "Review pending activity"),
        "payment_unresolved": ("funding", "Review payment status"),
        "gate_unresolved": ("overview", "Review agent controls"),
        "price_unavailable": ("budgets", "Review budget readiness"),
    }.get(reason, ("overview", "Review agent controls"))


def license_label(value: str) -> str:
    return "CC0-1.0" if value == "CC0-1.0 — original local demo fixture" else value


def result_text(value: str) -> str:
    # Present older saved results without their former boilerplate. Keep the
    # persisted output and all purchase/approval records unchanged.
    parts = value.split("\n\n", 2)
    previous_notice = (
        "Generated by the local scripted model from your saved task brief and the delivered template. "
        "This supported example fills a fixed structure; no external model or campaign ran."
    )
    if len(parts) == 3 and parts[1] == previous_notice:
        value = parts[0] + "\n\n" + parts[2]
    return value.replace("\nPurchased fixture: ", "\nPurchased template: ").replace(
        "\nLicense: CC0-1.0 — original local demo fixture\n", "\nLicense: CC0-1.0\n")


ENV = Environment(loader=DictLoader({**BASE_TEMPLATES, **TEMPLATES}), autoescape=True)
ENV.globals.update(license_label=license_label, result_text=result_text, money=money, credit=credit, run_label=run_label, readiness_destination=readiness_destination)


def render(template: str, /, **context: object) -> str:
    return ENV.get_template(template).render(**context)
