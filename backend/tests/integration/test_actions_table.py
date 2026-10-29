"""Actions tables expose summary evidence while retaining the owner audit scope."""
import json
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from aicl.workflow.pages import label, render


class ActionMarkup(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.in_data = False
        self.data = ""
        self.links = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.in_data = attrs.get("id") == "audit-actions-data"
        if tag == "a":
            self.links.append(attrs.get("href"))

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_data = False

    def handle_data(self, value):
        if self.in_data:
            self.data += value


def test_actions_table_summary_allowlist_and_source_links():
    action = '<script>alert("action")</script>'
    reason = '<img src=x onerror="alert(1)">'
    event = {
        "occurred_at": "2026-10-28T12:00:00Z", "agent_name": "Digest <owner>",
        "action": action, "event_type": "runtime.tool", "outcome": "applied",
        "reason": reason, "run_id": "runtime:run-1", "instance_id": "agent-1",
        "evidence_url": "/audit/jobs/runtime%3Arun-1#step-step-1", "purchase_id": "purchase-1",
        "payload": {"private_prompt": "PROTECTED_INPUT_NOT_FOR_LIST"},
        "content": "PROTECTED_OUTPUT_NOT_FOR_LIST", "provider_metadata": "SECRET_METADATA",
    }
    markup = render("workflow/actions", d={"events": [event]}, instance_id="agent-1",
                    date_from="2026-10-01", date_to="2026-10-28",
                    saved_statuses={"status_deliverables": "draft"}, filters_active=True)
    parsed = ActionMarkup(markup)
    row, = json.loads(parsed.data)
    assert set(row) == {"occurred_at", "agent_name", "action", "outcome", "reason",
                        "run_id", "evidence_url", "source_label", "purchase_url"}
    assert row["action"] == label(action) and row["reason"] == label(reason)
    assert '<script>alert' not in markup and '<img src=x' not in markup
    assert "&lt;script&gt;" in markup and "&lt;img" in markup
    assert all(value not in markup for value in (
        "PROTECTED_INPUT_NOT_FOR_LIST", "PROTECTED_OUTPUT_NOT_FOR_LIST", "SECRET_METADATA"))
    for field, fragment in (("evidence_url", "step-step-1"), ("purchase_url", "purchase-purchase-1")):
        url = urlsplit(row[field])
        assert url.fragment == fragment and row[field] in parsed.links
        expected = {"instance_id": ["agent-1"], "date_from": ["2026-10-01"],
                    "date_to": ["2026-10-28"], "status_deliverables": ["draft"]}
        if field == "purchase_url":
            expected["view"] = ["purchases"]
        assert parse_qs(url.query) == expected


def test_actions_owner_route_uses_studio_and_preserves_empty_scope(web):
    created = web.tool(web.owner_a, "create_instance", {
        "idempotency_key": "wiz_" + "a" * 32, "template_id": "default",
        "name": "Actions audit", "instructions": "Prepare a report.", "enabled_capabilities": [],
    }).json()["instance"]["id"]
    response = web.owner_a.get("/audit", params={"view": "actions", "instance_id": created,
                                               "date_from": "2000-01-01", "date_to": "2000-01-02"})
    assert response.status_code == 200
    assert 'data-kind="actions" data-source="audit-actions-data" data-fallback="audit-actions-fallback"' in response.text
    assert response.text.count('src="/static/vendor/ag-studio.min.js"') == 1
    assert response.text.count('src="/static/audit-studio.js"') == 1
    assert 'ag-grid-community.min.js' not in response.text
    assert 'No matching activity' in response.text
    assert json.loads(ActionMarkup(response.text).data) == []
    assert web.owner_b.get("/audit", params={"view": "actions", "instance_id": created}).status_code == 404
