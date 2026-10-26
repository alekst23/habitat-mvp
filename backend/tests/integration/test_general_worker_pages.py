"""Custom agent setup remains reviewable and preserves its execution scope."""

from aicl.chat.assistant_pages import render_assistant
from aicl.workflow.factory import workflow_service
from test_owner_journey_pages import _create, _post


def test_general_proposal_shows_tools_delivery_and_owner_confirmation():
    proposal = {"id": "proposal", "version": 1, "kind": "agent", "state": "pending", "data": {
        "scenario": "general", "name": "Community garden planner", "goal": "Plan community garden maintenance",
        "inputs": "Prioritize accessible paths", "tools": ["web_search"],
        "cadence": "daily", "timezone": "America/New_York", "deliverables": [
            {"name": "Garden plan", "description": "Seasonal maintenance guidance", "criteria": ["Cite evidence"]}],
    }}
    page = render_assistant(messages=[], session_id="session", proposal=proposal,
                            csrf="csrf", request_id="request", usage={})
    assert "Public web research" in page and "Approved tools" in page
    assert "Results appear in Habitat" in page
    assert "Daily at 9:00 AM" in page and "America/New_York" in page
    assert "Creates a draft with its schedule paused" in page
    assert 'action="/chat/proposals/proposal/confirm"' in page
    assert "General agents produce custom text deliverables" in page


def test_general_config_edit_keeps_tools_and_excludes_fixture_controls(web):
    instance_id, payments = _create(web)
    workflow = workflow_service(web.app.state.ctx)
    path = f"/instances/{instance_id}/workflow"
    fields = {"expected_version": "1", "scenario": "general",
              "goal": "Plan community garden maintenance", "inputs": "Prioritize accessible paths",
              "cadence": "daily", "timezone": "America/New_York", "tools": ["web_search"],
              "deliverable_key": "brief", "deliverable_name": "Garden maintenance plan",
              "deliverable_description": "Maintenance priorities with public guidance",
              "deliverable_criteria": "Link supporting guidance\nPrioritize accessible paths"}
    saved = _post(web, path + "/config", **fields)
    assert saved.status_code == 303, saved.text
    config = workflow.config(web.auth_a, instance_id)
    page = web.owner_a.get(path)
    assert page.status_code == 200
    assert 'name="scenario" value="general"' in page.text
    assert 'name="tools" value="web_search" checked' in page.text
    assert 'name="purchase_required_0"' not in page.text
    assert 'name="validation_scenario_0"' not in page.text
    assert "General agent" in page.text and "Results appear in Habitat" in page.text
    assert "requires real model inference" in page.text
    assert "Saving your selection authorizes the agent to use these tools" in page.text
    assert "Campaign plans and performance reports" not in page.text
    assert 'href="/instances/' + instance_id + '#overview"' in page.text
    fields.update(expected_version=str(config["version"]), cadence="hourly", tools=["web_search"])
    assert _post(web, path + "/config", **fields).status_code == 303
    restored = workflow.config(web.auth_a, instance_id)
    assert restored["scenario"] == "general" and restored["tools"] == ["web_search"]
    assert restored["cadence"] == "hourly" and not restored["enabled"]
    assert not workflow.overview(web.auth_a, instance_id)["runs"]
    assert not payments.dashboard(web.auth_a, instance_id)["purchases"]
    audit = web.owner_a.get("/audit", params={"instance_id": instance_id})
    assert "General agent outputs use real model generation" in audit.text
    assert "scheduled work and payments are simulated locally" not in audit.text
    fields.update(expected_version=str(restored["version"]), tools=[])
    assert _post(web, path + "/config", **fields).status_code == 303
    assert workflow.config(web.auth_a, instance_id)["tools"] == []
    assert web.owner_b.get(path).status_code == 404


def test_failed_general_output_offers_explicit_revision_without_accept_or_auto_retry():
    from aicl.workflow.pages import render

    item = {"id": "failed-output", "instance_id": "agent", "run_id": "job", "agent_name": "Community garden planner",
            "name": "Garden maintenance plan", "state": "needs_work", "version": 1, "created_at": None,
            "config_version": 1, "goal": "Plan seasonal maintenance", "content": "Evidence is incomplete.",
            "config_snapshot": {"scenario": "general"}, "latest": True, "versions": [],
            "criteria": [{"criterion": "Cite primary evidence", "passed": False, "reason": "Missing citation"}],
            "inference": {"model": "gpt-6-sol", "provider": "openai", "response_id": "response",
                          "input_tokens": 10, "output_tokens": 20, "cost_micro_usd": 100,
                          "web_search_calls": 1, "tool_trace": [{"type": "search", "queries": ["accessible garden paths"],
                              "sources": [{"url": "https://example.org/garden?season=spring&format=guide",
                                           "title": "Garden <guide>"},
                                          {"url": "javascript:alert(1)", "title": "Unsafe source"}]}]}}
    page = render("workflow/deliverable", item=item, title=item["name"], csrf="csrf")
    assert "Future scheduled reports will continue" in page
    assert "1 web search call" in page and "Tool use and sources" in page
    assert 'href="https://example.org/garden?season=spring&amp;format=guide"' in page
    assert "Garden &lt;guide&gt;" in page and "Garden <guide>" not in page
    assert "javascript:alert" not in page and "Unsafe source" not in page
    assert "automatically revised" in page
    assert 'action="/audit/deliverables/failed-output/review"' in page
    assert 'name="decision" value="request_changes"' in page
    assert 'name="decision" value="accept"' not in page
    assert "attempt a correction on its next eligible scheduled run" not in page
    historical = render("workflow/deliverable", item={**item, "latest": False}, title=item["name"], csrf="csrf")
    assert 'action="/audit/deliverables/failed-output/review"' not in historical
    fixture = render("workflow/deliverable", item={**item, "config_snapshot": {"scenario": "generic"}},
                     title=item["name"], csrf="csrf")
    assert "attempt a correction on its next eligible scheduled run" in fixture
    assert 'action="/audit/deliverables/failed-output/review"' not in fixture
