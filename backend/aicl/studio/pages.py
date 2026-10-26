"""The owner operations workspace, backed by authenticated Studio projections."""

from jinja2 import DictLoader, Environment

from aicl.web.pages import TEMPLATES as BASE_TEMPLATES


PAGE = """{% extends 'base' %}{% set page_key='audit' %}
{% block eyebrow %}OWNER OPERATIONS{% endblock %}
{% block subtitle %}Understand the work, follow the spending, and see what needs you.{% endblock %}
{% block header_actions %}<a class="button secondary" href="/audit">Full audit history</a>{% endblock %}
{% block body %}
<link rel="stylesheet" href="/static/studio.css">
<div id="operations" data-csrf="{{ csrf }}" data-license-key="{{ studio_license_key|default('') }}">
  <form id="operations-filters" class="operations-filters" aria-label="Dashboard filters">
    <div class="field operations-agent"><label for="operations-agent">Agent</label><select id="operations-agent" name="instance_id"><option value="">All agents</option></select></div>
    <div class="field"><label for="operations-from">From</label><input id="operations-from" name="date_from" type="date"></div>
    <div class="field"><label for="operations-to">Through</label><input id="operations-to" name="date_to" type="date"></div>
    <div class="operations-filter-actions"><button class="primary" type="submit">Apply filters</button><button class="ghost" type="button" id="operations-clear">Clear</button></div>
    <p class="operations-filter-note">Dates use America/New_York. Current balances stay current; spending and work follow the selected period.</p>
  </form>

  <div class="operations-refresh"><p id="operations-status" role="status" aria-live="polite">Loading your workspace…</p><button class="secondary" type="button" id="operations-refresh">Refresh data</button></div>
  <div id="operations-error" class="notice error" role="alert" hidden></div>

  <div class="operations-summaries">
  <section aria-labelledby="operations-balances-heading" class="operations-balances">
    <div class="operations-section-title"><h2 id="operations-balances-heading">Your boundaries, right now</h2><span>Current balances · selected agents</span></div>
    <div class="operations-metrics operations-current">
      <article><span>Service credit available</span><strong id="metric-credit">—</strong><small>Funds available for model work</small></article>
      <article><span>Held or unresolved</span><strong id="metric-held">—</strong><small>Reserved funds are unavailable for new work</small></article>
      <article><span>Resource budget headroom</span><strong id="metric-budget">—</strong><small>Inference + compute policy room, not cash</small></article>
    </div>
  </section>
  <section aria-labelledby="operations-period-heading" class="operations-period">
    <div class="operations-section-title"><h2 id="operations-period-heading">Work in this period</h2><span id="operations-period-label">All recorded activity</span></div>
    <div class="operations-metrics operations-period-metrics">
      <article><span>Inference usage</span><strong id="metric-inference">—</strong><small>Settled model usage</small></article>
      <article><span>Compute estimate</span><strong id="metric-compute">—</strong><small>Recorded runtime estimate</small></article>
      <article><span>Merchant payments</span><strong id="metric-purchases">—</strong><small>Separate from service funding</small></article>
      <article><span>Jobs / accepted outputs</span><strong id="metric-work">—</strong><small>Follow the source work below</small></article>
    </div>
  </section>
  </div>

  <section class="operations-workspace" aria-labelledby="operations-workspace-heading">
    <div class="operations-workspace-heading"><div><p class="kicker">YOUR WORKSPACE</p><h2 id="operations-workspace-heading">A clearer view of your agents</h2><p>Explore the records. Choose Edit layout to arrange your workspace.</p></div><div class="operations-layout-actions"><button type="button" class="secondary" id="operations-edit" aria-pressed="false" disabled>Edit layout</button><button type="button" class="secondary" id="operations-save" disabled>Save layout</button><button type="button" class="ghost" id="operations-reset" disabled>Reset layout</button></div></div>
    <div class="operations-presets"><button class="operations-preset" type="button" id="operations-preset" aria-pressed="false">Spending without accepted work <span>Preset view</span></button><p>Shows agents with recorded costs and no accepted output in the selected period.</p></div>
    <p id="operations-layout-status" class="operations-layout-status" role="status" aria-live="polite"></p>
    <div id="operations-studio" aria-label="Agent operations dashboard"><div class="operations-loading">Preparing the dashboard…</div></div>
    <div id="operations-fallback" class="operations-fallback" hidden><h3>Open the source records</h3><p>The dashboard could not load. Your work and controls are available in the existing owner pages.</p><div class="button-row"><a class="button secondary" href="/requests">Review requests</a><a class="button secondary" href="/audit">Open audit history</a><a class="button secondary" href="/workspace">View agents</a></div></div>
  </section>

  <p class="operations-footnote">Each record identifies its source: real model usage, estimated compute, Sandbox payments or scenario data. Funding, merchant payments and consumed advertising funds represent different accounting views; do not add them together.</p>
</div>
<script src="/static/vendor/ag-studio.min.js" defer></script>
<script src="/static/studio.js" defer></script>
{% endblock %}
"""

ENV = Environment(loader=DictLoader({**BASE_TEMPLATES, "studio/operations": PAGE}), autoescape=True)


def render_studio(*, title="Agent operations", **context):
    return ENV.get_template("studio/operations").render(title=title, **context)
