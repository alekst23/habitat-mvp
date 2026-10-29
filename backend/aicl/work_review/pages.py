"""Owner work inbox. Rendering and browsing never execute agent work."""
from pathlib import Path
import hashlib

from jinja2 import DictLoader, Environment
from aicl.web.pages import TEMPLATES


TEMPLATE = """{% extends 'base' %}{% set page_key = 'work' %}
{% block eyebrow %}Your work{% endblock %}
{% block subtitle %}Read the results. Keep the history. Find what needs your attention.{% endblock %}
{% block header_actions %}<a class="button ghost" href="/workspace">Manage agents</a><button type="button" class="secondary" id="review-assistant-toggle" aria-expanded="false" aria-controls="review-assistant">Agent assistant</button>{% endblock %}
{% block body %}
<link rel="stylesheet" href="{{ assets.css }}"><link rel="stylesheet" href="{{ assets.action_css }}">
<div class="work-review" id="work-review" data-csrf="{{ csrf }}">
  <noscript><p class="notice info">Enable JavaScript to browse the inbox, or <a href="/audit?view=deliverables">open saved outputs in Audit</a>.</p></noscript>
  <form id="review-filters" class="review-filters" role="search">
    <label class="review-search" for="review-search">Search work<input id="review-search" name="q" type="search" maxlength="160" placeholder="Agent, goal, or result name" autocomplete="off"></label>
    <label for="review-agent">Agent<select id="review-agent" name="workspace_id"><option value="">All agents</option></select></label>
    <label for="review-view">Show<select id="review-view" name="view"><option value="all">All work</option><option value="unseen">Unseen</option><option value="needs_attention">Needs attention</option><option value="saved">Saved</option></select></label>
    <details class="review-date-filter"><summary>Date range</summary><div><label for="review-from">From<input type="date" id="review-from" name="from_date"></label><label for="review-to">Through<input type="date" id="review-to" name="to_date"></label><small>Run dates in UTC.</small></div></details>
    <button class="secondary" type="submit">Refresh</button>
  </form>
  <div class="review-overview"><p data-review-counts role="status">Loading your work…</p><div><a href="/audit?view=deliverables">Other workflow results in Audit</a><button type="button" class="ghost small" data-clear-filters hidden>Clear filters</button></div></div>
  <p class="notice error" data-review-error role="alert" hidden></p>
  <div class="review-layout">
    <section class="review-inbox" aria-label="Review inbox">
      <div class="review-list-pane"><h2 class="review-list-heading">Latest work</h2><div data-review-list aria-label="Runs"></div><button type="button" class="secondary review-more" data-review-more hidden>Load older work</button></div>
      <article class="review-reader" data-review-reader aria-label="Selected work" aria-busy="true"><div class="review-empty"><h2>Your work will appear here</h2><p>Results, partial drafts, and run history stay together.</p></div></article>
    </section>
    <aside class="card review-assistant" id="review-assistant" aria-label="Agent assistant" hidden><div class="card-header"><h2>Agent assistant</h2><button type="button" class="ghost small" data-close-assistant>Close</button></div><div class="card-body" data-review-assistant><p>Select a run to open its agent’s assistant.</p></div></aside>
  </div>
</div>
<script src="{{ assets.markdown }}" defer></script><script src="{{ assets.action_js }}" defer></script><script src="{{ assets.js }}" defer></script>
{% endblock %}"""

ENV = Environment(loader=DictLoader({**TEMPLATES, "work_review": TEMPLATE}), autoescape=True)


def render_review(*, csrf, account_name, **_):
    static = Path(__file__).parent.parent / "web" / "static"
    def asset(name):
        return "/static/" + name + "?v=" + hashlib.sha256((static / name).read_bytes()).hexdigest()[:16]
    return ENV.get_template("work_review").render(
        title="Review your work", csrf=csrf, account_name=account_name, unified_workspace=True,
        assets={"css": asset("work-review.css"), "js": asset("work-review.js"), "markdown": asset("workspace-markdown.js"), "action_css": asset("action-details.css"), "action_js": asset("action-details.js")})
