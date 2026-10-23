"""Trusted Habitat chrome around pixels from an untrusted remote website."""
from jinja2 import DictLoader, Environment

from aicl.owner_requests.pages import TEMPLATES as REQUEST_TEMPLATES, request_action, requests_url
from aicl.web.pages import TEMPLATES as BASE_TEMPLATES


TEMPLATE = """{% extends 'base' %}{% set page_key = 'requests' %}
{% block subtitle %}Sign in for {{ r.agent_name }}. This job stays paused while you control the browser.{% endblock %}
{% block header_actions %}<a class="button secondary small" href="{{ requests_url(r.id) }}">Back to request</a>{% endblock %}
{% block body %}<link rel="stylesheet" href="/static/requests.css"><link rel="stylesheet" href="/static/browser-session.css">
<section class="browser-handoff" data-browser-session data-endpoint="{{ request_action(r.id, 'browser') }}" data-csrf="{{ csrf }}" data-active="{{ 'true' if browser.state == 'active' else 'false' }}">
<div class="browser-context"><div><span class="browser-eyebrow">Access requested</span><strong>{{ r.details.domain }}</strong></div><p>{{ r.reason }}</p></div>
{% if browser.state == 'active' %}
<div class="browser-ownership"><span class="browser-live-dot" aria-hidden="true"></span><strong>You have control</strong><span>The agent cannot use this browser during sign-in.</span><time id="browser-expiry" datetime="{{ browser.expires_at }}">Session ends {{ browser.expires_at }}</time></div>
<div class="browser-window"><div class="browser-address"><span aria-hidden="true">↗</span><span>Current website</span><strong id="browser-origin">{{ browser.domain|default(r.details.domain, true) }}</strong><span id="browser-frame-status" role="status">Connecting…</span></div>
<div class="browser-canvas-wrap"><canvas id="browser-screen" width="1280" height="720" tabindex="0" contenteditable="plaintext-only" spellcheck="false" role="application" aria-label="Remote sign-in browser. Click a website field to type. Press Escape to return to Habitat controls."></canvas><div id="browser-overlay">Connecting to your private browser…</div></div></div>
<div class="browser-helper"><p>Click inside the website to type or paste. Press <kbd>Esc</kbd> to return to Habitat controls. Your agent does not receive your password or login codes.</p><button id="browser-refresh" class="ghost small" type="button">Refresh view</button></div>
<p id="browser-error" class="notice error" role="alert" hidden></p>
<div class="browser-finish"><form id="browser-complete" method="post" action="{{ request_action(r.id, 'browser/complete') }}"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="expected_version" value="{{ r.version }}">{% include 'requests/continuation' %}<button class="primary" type="submit" id="browser-return">Return session to agent</button><p class="field-hint">When you finish signing in, Habitat saves access for this agent’s scheduled jobs for up to 24 hours. You can revoke it from this request. The worker must check access when it continues. Purchases still need their own approval.</p></form><form method="post" action="{{ request_action(r.id, 'browser/cancel') }}"><input type="hidden" name="csrf_token" value="{{ csrf }}"><button id="browser-cancel" class="secondary" type="submit">Cancel sign-in</button><p class="field-hint">Closes the browser and keeps the request pending.</p></form></div>
{% elif browser.state == 'closing' %}<div class="browser-inactive"><h2>Closing the browser safely</h2><p>Access is blocked while Habitat waits for the browser service to confirm shutdown. This job cannot use the session.</p><form method="post" action="{{ request_action(r.id, 'browser/cancel') }}"><input type="hidden" name="csrf_token" value="{{ csrf }}"><button class="primary" type="submit">Retry closing browser</button></form></div>{% else %}<div class="browser-inactive"><h2>{{ 'Session provided' if browser.state == 'complete' else 'Sign-in session is not active' }}</h2><p>{{ 'The interactive browser is closed. The worker must check access before continuing its work.' if browser.state == 'complete' else 'Return to the request to start a new sign-in session. The job remains subject to its current controls.' }}</p><a class="button primary" href="{{ requests_url(r.id) }}">Return to request</a></div>{% endif %}
</section><script src="/static/browser-session.js" defer></script>{% endblock %}"""

ENV = Environment(loader=DictLoader({**BASE_TEMPLATES, **REQUEST_TEMPLATES, "browser/session": TEMPLATE}), autoescape=True)
ENV.globals.update(request_action=request_action, requests_url=requests_url)


def render_browser(**context):
    return ENV.get_template("browser/session").render(title="Cloud sign-in", **context)
