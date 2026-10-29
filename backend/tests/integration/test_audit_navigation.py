"""The review workspace carries its agent and date scope across every view."""
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit
from aicl.workflow.routes import _audit_filter


class AuditLinks(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inside = False
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "nav" and attrs.get("aria-label") == "Audit views":
            self.inside = True
        if self.inside and tag == "a":
            self.links.append(attrs)

    def handle_endtag(self, tag):
        if tag == "nav":
            self.inside = False


def test_every_audit_tab_keeps_agent_and_date_scope(web):
    created = web.tool(web.owner_a, "create_instance", {
        "idempotency_key": "wiz_" + "e" * 32, "template_id": "default",
        "name": "Review scope", "instructions": "Prepare a report.", "enabled_capabilities": [],
    }).json()["instance"]["id"]
    filters = {"instance_id": created, "date_from": "2026-10-01", "date_to": "2026-10-28"}
    for view in ("operations", "actions", "deliverables", "costs", "purchases", "campaigns"):
        path = "/audit/studio" if view == "operations" else "/audit"
        page = web.owner_a.get(path, params={**filters, "view": view})
        assert page.status_code == 200
        links = AuditLinks(page.text).links
        assert len(links) == 6
        assert sum(link.get("aria-current") == "page" for link in links) == 1
        for link in links:
            query = parse_qs(urlsplit(link["href"]).query)
            assert all(query.get(key) == [value] for key, value in filters.items())
        assert 'value="2026-10-01"' in page.text
        assert 'value="2026-10-28"' in page.text
        if view in ("costs", "campaigns"):
            assert page.text.count('src="/static/vendor/ag-studio.min.js"') == 1
            assert 'src="/static/audit-studio.js"' in page.text
            assert 'ag-grid-community.min.js' not in page.text
        if view == "costs":
            assert 'data-kind="costs" data-source="audit-cost-data"' in page.text
            assert 'id="audit-cost-fallback"' in page.text
    # Output and purchase states have different meanings, but each choice is
    # retained when the owner visits another tab and returns.
    page = web.owner_a.get("/audit", params={**filters, "view": "deliverables", "status": "draft"})
    for view in ("operations", "actions", "deliverables"):
        link = next(link for link in AuditLinks(page.text).links if link["data-audit-view"] == view)
        page = web.owner_a.get(link["href"])
        assert page.status_code == 200
    assert '<option value="draft" selected>' in page.text


def test_period_filters_flow_totals_without_changing_current_balances():
    data = {"totals": {"service_balance_micro_usd": 4500000, "purchase_held_minor": 100,
                       "inference_cost_micro_usd": 500000, "run_count": 2},
            "cost_rows": [
                {"created_at": "2026-10-20T16:00:00Z", "category": "Inference usage", "amount_usd": .2},
                {"created_at": "2026-09-20T16:00:00Z", "category": "Inference usage", "amount_usd": .3}],
            "runs": [{"created_at": "2026-10-20T16:00:00Z"}, {"created_at": "2026-09-20T16:00:00Z"}]}
    filtered, *_ = _audit_filter(data, "costs", "", "2026-10-01", "2026-10-28")
    assert filtered["totals"]["inference_cost_micro_usd"] == 200000
    assert filtered["totals"]["run_count"] == 1
    assert filtered["totals"]["service_balance_micro_usd"] == 4500000
    assert filtered["totals"]["purchase_held_minor"] == 100
