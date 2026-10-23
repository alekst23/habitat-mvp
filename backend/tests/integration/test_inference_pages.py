"""Provenance shown only for recorded model calls; fixture results remain explicit."""

from aicl.workflow.pages import render


def test_deliverable_provenance_is_measured_escaped_and_distinct_from_fixture_checks():
    item = {
        "id": "output-1", "instance_id": "agent-1", "run_id": "job-1", "name": "Campaign plan",
        "agent_name": "Campaign assistant", "goal": "Market PocketPlan", "version": 1,
        "config_version": 1, "created_at": "2026-10-22T12:00:00Z", "state": "submitted",
        "content": "A focused campaign plan.", "versions": [],
        "criteria": [{"criterion": "State the audience", "passed": True, "reason": "Audience included."}],
    }
    fixture = render("workflow/deliverable", title=item["name"], item=item, csrf="fixture-csrf")
    assert "local scenario fixtures" in fixture and "Demo validation" in fixture
    assert "Generated with" not in fixture and "Generation details" not in fixture

    item["inference"] = {
        "provider": "openai", "model": "gpt-6-sol", "response_id": "resp_<script>unsafe</script>",
        "input_tokens": 1234, "output_tokens": 567, "cost_micro_usd": 5678,
        "validation_method": "model_self_assessment_and_structural_checks",
    }
    page = render("workflow/deliverable", title=item["name"], item=item, csrf="fixture-csrf")
    assert "Generated with GPT-6 Sol" in page
    assert "1234 input tokens" in page and "567 output tokens" in page and "$0.005678" in page
    assert "Generation details" in page and "resp_&lt;script&gt;unsafe&lt;/script&gt;" in page
    assert "resp_<script>" not in page
    assert "Model self-assessment + structural checks" in page
    assert "You review accuracy and quality" in page
    assert "local scenario fixtures" not in page and "Demo validation" not in page
    assert "Advertising delivery and metrics remain scenario data" in page
    assert 'name="decision" value="accept"' in page and 'name="decision" value="request_changes"' in page


def test_config_and_audit_describe_real_inference_without_claiming_live_advertising():
    cfg = {
        "instance_id": "agent-1", "version": 1, "instance_version": 1, "saved": True,
        "scenario": "pocketplan_ads", "goal": "Market PocketPlan", "inputs": "Freelancers",
        "deliverables": [{"key": "campaign_plan", "name": "Campaign plan", "criteria": ["State the audience"]}],
        "cadence": "daily", "timezone": "UTC", "enabled": False,
    }
    overview = {"runs": [], "payment_transport": "paypal_sandbox"}
    fixture = render("workflow/config", title="Agent workflow", cfg=cfg, overview=overview, agent={}, csrf="x")
    assert "no real agent or model runs" in fixture
    assert "Scheduled work, validation and advertising remain simulated" in fixture
    cfg["inference_mode"] = "openai"
    page = render("workflow/config", title="Agent workflow", cfg=cfg, overview=overview, agent={}, csrf="x")
    assert "Campaign plans and performance reports use GPT-6 Sol" in page
    assert "no real agent or model runs" not in page
    assert "PayPal Sandbox payments use test funds" in page
    assert "Advertising delivery and metrics remain scenario data" in page

    audit = render("workflow/audit", title="Audit", view="deliverables", agents=[],
                   d={"totals": {}, "deliverables": [], "payment_transport": "paypal_sandbox", "inference_mode": "openai"})
    assert "Campaign plans and performance reports use GPT-6 Sol" in audit
    assert "Inference, scheduled work and advertising remain simulated" not in audit
    assert "Advertising delivery and metrics remain scenario data" in audit
    assert "PayPal Sandbox payments use test funds" in audit
