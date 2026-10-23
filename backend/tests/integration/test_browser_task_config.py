"""Owner-configured browser work retains scope without granting checkout authority."""
from copy import deepcopy

import pytest

from aicl.browser.task_config import BROWSER_SCENARIO, browser_purchase_preset, normalize_browser_task
from aicl.control.errors import AiclError
from aicl.workflow.factory import workflow_service
from aicl.workflow.service import MockWorkflowService
from test_owner_journey_pages import _create, _post


def test_browser_task_validation_keeps_exact_public_https_scope():
    task = browser_purchase_preset()["browser_task"]
    assert normalize_browser_task(task) == task
    for url in ("http://ads.snapchat.com/", "https://127.0.0.1/", "https://[::1]/",
                "https://metadata.google.internal/", "https://localhost/", "https://printer.local/",
                "https://user:password@ads.snapchat.com/", "https://ads.snapchat.com:8443/",
                "https://ads.snapchat.com/#token", "https://ads.snapchat.com/?access_token=secret",
                "https://ads.snapchat.com/?", "https://2130706433/", "https://127.1/"):
        with pytest.raises(AiclError):
            normalize_browser_task({**task, "service_url": url})
    for value in (0, True, 1_000_001, 10.5):
        with pytest.raises(AiclError):
            normalize_browser_task({**task, "max_amount_minor": value})
    with pytest.raises(AiclError):
        normalize_browser_task({**task, "currency": "EUR"})


def test_browser_workflow_configuration_roundtrips_without_dispatch_or_payment(web):
    instance_id, payments = _create(web)
    workflow = workflow_service(web.app.state.ctx)
    path = f"/instances/{instance_id}/workflow"
    initial = web.owner_a.get(path)
    assert "Use browser purchase workflow" in initial.text
    response = _post(web, path + "/example", expected_version="1", example=BROWSER_SCENARIO)
    assert response.status_code == 303
    config = workflow.config(web.auth_a, instance_id)
    assert config["scenario"] == BROWSER_SCENARIO
    assert config["deliverables"][0]["key"] == "purchase_proposal"
    assert not config["enabled"] and not workflow.overview(web.auth_a, instance_id)["runs"]
    page = web.owner_a.get(path)
    for name in ("browser_service_url", "browser_objective", "browser_max_amount", "cadence"):
        assert f'name="{name}"' in page.text
    assert "Stops before checkout" in page.text
    assert "name=\"purchase_required_0\"" not in page.text
    fields = {"expected_version": str(config["version"]), "scenario": BROWSER_SCENARIO,
              "goal": "Market my mobile game", "inputs": "Players who like cooperative puzzles",
              "cadence": "hourly", "timezone": "UTC", "browser_service_url": "https://ads.snapchat.com/",
              "browser_objective": "Review a small game-install advertising test", "browser_max_amount": "24.50",
              "deliverable_key": "purchase_proposal", "deliverable_name": "Purchase proposal",
              "deliverable_description": "Evidence and bounded spend", "deliverable_criteria": "Identify the ad account\nCite observed evidence"}
    saved = _post(web, path + "/config", **fields)
    assert saved.status_code == 303, saved.text
    restored = workflow.config(web.auth_a, instance_id)
    assert restored["browser_task"]["max_amount_minor"] == 2450
    assert restored["browser_task"]["objective"] == fields["browser_objective"]
    assert restored["cadence"] == "hourly"
    invalid = _post(web, path + "/config", **{**fields, "expected_version": str(restored["version"]), "browser_max_amount": "-1"})
    assert invalid.status_code == 422
    assert workflow.config(web.auth_a, instance_id) == restored
    assert not payments.dashboard(web.auth_a, instance_id)["purchases"]
    assert not workflow.overview(web.auth_a, instance_id)["runs"]
    with pytest.raises(AiclError):
        workflow.config(web.auth_b, instance_id)


def test_browser_config_rejects_fake_purchase_dependency_and_is_allowed_on_render(web):
    instance_id, _ = _create(web)
    ctx = web.app.state.ctx
    service = MockWorkflowService(ctx.db, ctx.clock, execution_mode="render")
    preset = browser_purchase_preset()
    invalid = deepcopy(preset)
    invalid["deliverables"][0]["purchase_required"] = True
    with pytest.raises(AiclError):
        service.save_config(web.auth_a, instance_id, invalid, 1)
    saved = service.save_config(web.auth_a, instance_id, preset, 1)
    assert saved["browser_task"] == preset["browser_task"]
