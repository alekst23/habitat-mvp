"""Server-rendered pages (Jinja2, autoescaped) for landing, sign-in, workspace and the wizard (E11-3)."""

from __future__ import annotations

from jinja2 import DictLoader, Environment

BASE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{{ title }} - Habitat</title></head>
<body><main><h1>{{ title }}</h1>{% block body %}{% endblock %}</main></body></html>"""

TEMPLATES = {
    "base": BASE,
    "landing": """{% extends "base" %}{% block body %}<p>Hosted agents with budgets you control.</p>
<p><a href="/auth/sign-in">Create your first agent</a></p>{% endblock %}""",
    "sign_in": """{% extends "base" %}{% block body %}
<form method="post" action="/auth/magic-link"><label for="email">Email</label>
<input id="email" name="email" type="email" autocomplete="email">
<button type="submit">Send sign-in link</button></form>{% endblock %}""",
    "link_sent": """{% extends "base" %}{% block body %}<p>{{ message }}</p>{% endblock %}""",
    "verify": """{% extends "base" %}{% block body %}
<form method="post" action="/auth/verify"><input type="hidden" name="token" value="{{ token }}">
<button type="submit">Confirm sign-in</button></form>{% endblock %}""",
    "invalid": """{% extends "base" %}{% block body %}<p>This link is invalid or expired.</p>
<p><a href="/auth/sign-in">Request a new link</a></p>{% endblock %}""",
    "workspace": """{% extends "base" %}{% block body %}
{% if instances %}<ul>{% for i in instances %}<li>{{ i.name }} ({{ i.lifecycle }})</li>{% endfor %}</ul>
{% else %}<p>You have no agents yet.</p>{% endif %}
<p><a href="/agents/new">Create with wizard</a> <a href="/chat">Create with chat</a></p>
<form method="post" action="/auth/logout"><input type="hidden" name="csrf_token" value="{{ csrf }}">
<button type="submit">Sign out</button></form>{% endblock %}""",
    "wizard": """{% extends "base" %}{% block body %}
{% if errors %}<ul>{% for e in errors %}<li>{{ e.field }}: {{ e.code }}</li>{% endfor %}</ul>{% endif %}
<form method="post" action="/agents/new">
<input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="idempotency_key" value="{{ key }}">
<label for="name">Name</label><input id="name" name="name" value="{{ name }}">
<label for="instructions">Instructions</label><textarea id="instructions" name="instructions">{{ instructions }}</textarea>
<fieldset><legend>Capabilities</legend>{% for c in capabilities %}
<label><input type="checkbox" name="capabilities" value="{{ c }}"{% if c in selected %} checked{% endif %}> {{ c }}</label>
{% endfor %}</fieldset><button type="submit">Create</button></form>{% endblock %}""",
    "chat": """{% extends "base" %}{% block body %}
<p>Tell me about the agent you want and I will guide you step by step.</p>
{% if error %}<p role="alert">{{ error }}</p>{% endif %}
<ol aria-label="Conversation">{% for m in messages %}<li><strong>{{ "You" if m.role == "user" else "Assistant" }}:</strong>
<span style="white-space: pre-wrap">{{ m.text }}</span></li>{% endfor %}</ol>
<form method="post" action="/chat/messages">
<input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="chat_session_id" value="{{ session_id }}">
<label for="message">Message</label><input id="message" name="text" autocomplete="off">
<button type="submit">Send</button></form>
<p><a href="/workspace">Back to workspace</a></p>{% endblock %}""",
    "created": """{% extends "base" %}{% block body %}
<p>{{ instance.name }}</p><p>This agent is a draft: it is not active until you activate it.</p>
<p><a href="/workspace">Back to workspace</a></p>{% endblock %}""",
}

ENV = Environment(loader=DictLoader(TEMPLATES), autoescape=True)


def render(template: str, /, **context: object) -> str:
    return ENV.get_template(template).render(**context)
