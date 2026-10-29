"""Shared review navigation. Agent and date scope travel in ordinary URLs."""
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from jinja2 import pass_context


STATUS_KEYS = ("status_purchases", "status_deliverables")


def saved_statuses(query):
    """Keep view-specific choices in the URL without applying unrelated states."""
    allowed = {"", "pending", "awaiting_approval", "awaiting_checkout", "payment_pending", "paid",
               "declined", "cancelled", "expired", "submitted", "accepted", "needs_work",
               "changes_requested", "completed", "draft"}
    return {key: query.get(key, "") for key in STATUS_KEYS if query.get(key) in allowed}


def audit_url(view, instance_id="", date_from="", date_to="", statuses=None):
    values = (("view", view if view != "operations" else ""), ("instance_id", instance_id),
              ("date_from", date_from), ("date_to", date_to))
    params = {key: str(value) for key, value in values if value}
    params.update({key: value for key, value in (statuses or {}).items() if value})
    if (statuses or {}).get("status_" + view):
        params["status"] = statuses["status_" + view]
    query = urlencode(params)
    return ("/audit/studio" if view == "operations" else "/audit") + ("?" + query if query else "")


@pass_context
def record_url(context, path):
    parts = urlsplit(path)
    query = dict(parse_qsl(parts.query))
    query.update({key: str(context.get(key)) for key in ("instance_id", "date_from", "date_to")
                  if context.get(key)})
    query.update({key: value for key, value in context.get("saved_statuses", {}).items() if value})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


TEMPLATES = {
    "audit/navigation": """<link rel="stylesheet" href="/static/audit-navigation.css">
<nav class="workflow-tabs audit-tabs" aria-label="Audit views">{% for key, name in [('operations','Agent operations'),('costs','Costs & statistics'),('actions','Actions'),('purchases','Purchases'),('deliverables','Deliverables'),('campaigns','Campaigns')] %}<a data-audit-view="{{ key }}" href="{{ audit_url(key, instance_id|default(''), date_from|default(''), date_to|default(''), saved_statuses|default({})) }}"{% if view == key %} aria-current="page"{% endif %}>{{ name }}</a>{% endfor %}</nav>""",
}
