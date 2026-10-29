"""The shared workspace renders untrusted model output as text."""
from html.parser import HTMLParser

from aicl.agent_workspace.pages import render_workspace


def _inputs(html, name=None):
    class Inputs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.values = []

        def handle_starttag(self, tag, attrs):
            if tag == "input":
                self.values.append(dict(attrs))

    parser = Inputs()
    parser.feed(html)
    return [item for item in parser.values if name is None or item.get("name") == name]


def test_workspace_escapes_shared_draft_and_keeps_payment_and_assistant_controls_visible():
    value = '</script><img src=x onerror="alert(1)">'
    state = {"id": "workspace-id", "version": 1, "instance_id": None, "published": None, "dirty": True,
             "capabilities": [{"name": "web.read", "description": "Read approved public pages"}],
             "draft": { "name": value, "goal": value, "inputs": "Context", "deliverables": [], "tools": ["web.read"],
                       "network_domains": [], "limits": {}, "cadence": "daily", "timezone": "America/New_York", "time_of_day": "09:00"},
             "execution": {"readiness": {"balance_micro_usd": 0, "blockers": [{"reason": "credit_insufficient", "message": value}]}}}
    html = render_workspace(state, csrf="csrf", account_name="Owner", messages=[{"role": "assistant", "text": value}], usage={})
    assert '<img src=x' not in html
    assert "\\u003c/script\\u003e" in html
    assert "&lt;/script&gt;" in html
    assert 'id="workspace-draft-form"' in html and 'id="workspace-assistant-form"' in html
    assert 'data-command="fund" disabled' in html and 'data-command="start" disabled' in html
    assert 'data-external-conflict hidden' in html
    assert 'id="workspace-run-message-form"' in html
    assert '<a href="#workspace-tools">Permissions</a>' in html
    assert '<h2>Permissions</h2>' in html
    assert 'data-permission-matrix' in html
    assert 'data-permission-row="inference"' not in html
    assert 'role="radiogroup" aria-label="AI processing"' not in html
    assert _inputs(html, "inference_enabled") == []
    assert 'workspace-inference-hint' not in html
    for name in ("gmail.read", "gmail.send", "reddit.read", "reddit.post"):
        controls = [item for item in _inputs(html) if item.get("data-unavailable-capability") == name]
        assert len(controls) == 2
        assert all(item["type"] == "radio" and "disabled" in item for item in controls)
        assert [item["value"] for item in controls if "checked" in item] == ["off"]
    assert html.count('Not yet available') == 4


def test_web_access_levels_disclose_the_goal_and_keep_legacy_grants_narrow():
    state = {"id": "workspace-id", "version": 1, "instance_id": None, "published": None, "dirty": True,
             "capabilities": [{"name": "web.search"}, {"name": "web.read"}],
             "draft": {"name": "News", "goal": "Find news", "inputs": "Private context", "deliverables": [],
                       "tools": ["web.search"], "network_domains": [], "limits": {}, "cadence": "manual",
                       "timezone": "UTC", "time_of_day": "09:00"},
             "public_research_release": {"legacy": True},
             "execution": {"readiness": {"balance_micro_usd": 0, "blockers": []}}}
    html = render_workspace(state, csrf="csrf", account_name="Owner", messages=[], usage={})
    web = _inputs(html, "web_access_mode")
    assert [item["value"] for item in web] == ["off", "allowlist", "blocklist", "all"]
    assert all(item["type"] == "radio" and "checked" not in item for item in web)
    assert '<select id="workspace-web-access"' not in html
    assert 'data-web-domains hidden' in html
    assert 'data-web-disclosure hidden' in html
    assert 'limited to that approval until you choose access levels' in html
    assert 'name="tools"' not in html
    assert 'name="research_queries"' not in html
    assert 'name="research_source_urls"' not in html
    assert 'name="research_purpose"' not in html
    assert 'data-command="restart" hidden>Restart with updated settings' in html
    state["draft"]["web_access"] = {"mode": "blocklist", "domains": ["example.com"]}
    state["public_research_release"] = {"available": True, "approval_required": True}
    html = render_workspace(state, csrf="csrf", account_name="Owner", messages=[], usage={})
    assert [item["value"] for item in _inputs(html, "web_access_mode") if "checked" in item] == ["blocklist"]
    assert 'data-web-domains hidden' not in html
    assert 'data-web-domains-label>Blocked sites</label>' in html
    assert 'Each includes its subdomains.' in html
    assert 'Allow web research for this goal' in html
    assert 'Context, files, and conversation are excluded from web research.' in html
    assert 'Keep sensitive details out of the goal when search or page reading is on.' in html
    assert 'data-research-approval hidden' not in html


def test_workspace_asset_versions_follow_content_even_when_file_metadata_matches(tmp_path, monkeypatch):
    import os
    from aicl.agent_workspace import pages

    monkeypatch.setattr(pages, "STATIC_DIR", tmp_path)
    state = {"id": "workspace-id", "draft": {"name": "News", "goal": "Find news", "inputs": "",
             "deliverables": [], "tools": [], "network_domains": [], "limits": {}, "cadence": "manual",
             "timezone": "UTC", "time_of_day": "09:00"}}
    assets = [tmp_path / name for name in ("agent-workspace.js", "agent-workspace.css",
              "workspace-markdown.js", "action-details.js", "action-details.css")]
    for asset in assets:
        asset.write_text("old bytes")
        os.utime(asset, (1_700_000_000, 1_700_000_000))
    old_urls = [pages._asset_url(asset.name) for asset in assets]
    first = render_workspace(state, csrf="csrf", account_name="Owner", messages=[], usage=None)
    for asset, url in zip(assets, old_urls):
        assert (f'src="{url}" defer' if asset.suffix == ".js" else f'href="{url}"') in first
    assert first == render_workspace(state, csrf="csrf", account_name="Owner", messages=[], usage=None)
    for asset in assets:
        asset.write_text("new bytes")
        os.utime(asset, (1_700_000_000, 1_700_000_000))
    refreshed = render_workspace(state, csrf="csrf", account_name="Owner", messages=[], usage=None)
    assert all(url not in refreshed for url in old_urls)
    for asset in assets:
        url = pages._asset_url(asset.name)
        assert (f'src="{url}" defer' if asset.suffix == ".js" else f'href="{url}"') in refreshed
