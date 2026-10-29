"""Owner journey over real HTTP routes and SQLite, with local payment/model fixtures."""

from __future__ import annotations

from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

from aicl.app import FIXTURE_CSRF_TOKEN
from aicl.commerce.service import MockCommerceService
from aicl.creation.service import read_instance_snapshot
from aicl.workflow.factory import workflow_service


class _FormFields(HTMLParser):
    """Read submitted values from a rendered form, including its version and CSRF."""

    def __init__(self, markup, action):
        super().__init__()
        self.action = action
        self.fields = None
        self.inside = False
        self.textarea = None
        self.feed(markup)
        assert self.fields is not None, f"No form for {action}"

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.inside = attrs.get("action") == self.action
            if self.inside:
                self.fields = {}
        if not self.inside or not attrs.get("name"):
            return
        if tag == "input" and (attrs.get("type") not in ("checkbox", "radio") or "checked" in attrs):
            self.fields[attrs["name"]] = attrs.get("value", "")
        elif tag == "textarea":
            self.textarea = attrs["name"]
            self.fields[self.textarea] = ""

    def handle_data(self, data):
        if self.inside and self.textarea:
            self.fields[self.textarea] += data

    def handle_endtag(self, tag):
        if tag == "textarea":
            self.textarea = None
        elif tag == "form":
            self.inside = False


def _post(web, path, **fields):
    return web.owner_a.post(
        path, data={"csrf_token": FIXTURE_CSRF_TOKEN, **fields},
        headers={"origin": web.app.state.ctx.settings.public_base_url}, follow_redirects=False,
    )


def _create(web, capabilities=()):
    response = web.tool(web.owner_a, "create_instance", {
        "idempotency_key": "wiz_" + "f" * 32, "template_id": "default",
        "name": "Owner journey", "instructions": "Keep purchases within my approval boundary.",
        "enabled_capabilities": list(capabilities),
    })
    assert response.status_code == 200, response.text
    instance_id = response.json()["instance"]["id"]
    ctx = web.app.state.ctx
    return instance_id, MockCommerceService(ctx.db, ctx.clock)


def _make_ready(web, instance_id):
    canonical = f"/instances/{instance_id}"
    for path, values in (
        ("/limits", {"inference_daily_usd": "1", "inference_monthly_usd": "10",
                     "compute_daily_usd": "1", "compute_monthly_usd": "10"}),
    ):
        version = read_instance_snapshot(web.auth_a, instance_id).version
        response = _post(web, canonical + path, expected_version=version, **values)
        assert response.status_code == 303, response.text
    settings_action = canonical + "/commerce/settings"
    settings = _FormFields(web.owner_a.get(canonical).text, settings_action).fields
    configured = _post(web, settings_action, **{**settings, "enabled": "on", "purchase_limit": "2.00"})
    assert configured.status_code == 303, configured.text
    topup = _post(web, canonical + "/commerce/topups", amount_minor="500", request_id="journey-funding")
    assert topup.status_code == 303, topup.text
    order_path = topup.headers["location"]
    completed = _post(web, order_path + "/checkout", outcome="complete", buyer_id="demo-buyer")
    assert completed.status_code == 303, completed.text
    assert urlsplit(completed.headers["location"]).fragment == "setup"
    receipt = web.owner_a.get(order_path)
    assert f'href="{canonical}#setup"' in receipt.text


def _save_workflow(web, instance_id, *, goal="Plan a community garden", purchase=True):
    workflow = workflow_service(web.app.state.ctx)
    config = workflow.config(web.auth_a, instance_id)
    fields = {
        "goal": goal, "inputs": "Local residents & volunteers", "cadence": "hourly", "timezone": "UTC",
        "expected_version": str(config["version"]), "deliverable_key": "report",
        "deliverable_name": "Garden launch plan", "deliverable_description": "An owner-ready plan.",
        "deliverable_criteria": "Include a headline\nInclude a clear next action",
        "validation_scenario_0": "pass",
    }
    if purchase:
        fields["purchase_required_0"] = "on"
    # The rendered form includes an optional blank second deliverable. Real
    # browser submission must ignore it without dropping the configured one.
    for field in ("deliverable_key", "deliverable_name", "deliverable_description", "deliverable_criteria"):
        fields[field] = [fields[field], ""]
    response = _post(web, f"/instances/{instance_id}/workflow/config", **fields)
    assert response.status_code == 303, response.text
    assert workflow.config(web.auth_a, instance_id)["goal"] == goal
    assert len(workflow.config(web.auth_a, instance_id)["deliverables"]) == 1
    return workflow


def _tick(web, instance_id, workflow):
    due = workflow.config(web.auth_a, instance_id)["next_due"]
    response = _post(web, f"/instances/{instance_id}/workflow/advance", expected_due=due)
    assert response.status_code == 303, response.text
    return workflow.overview(web.auth_a, instance_id)


def _schedule(web, instance_id, enabled):
    path = f"/instances/{instance_id}/workflow"
    fields = _FormFields(web.owner_a.get(path).text, path + "/schedule").fields
    return _post(web, path + "/schedule", **{**fields, "enabled": str(enabled).lower()})


def test_draft_exposes_configuration_and_boundaries_without_manual_task_or_charges(web):
    instance_id, service = _create(web)
    canonical = f"/instances/{instance_id}"
    page = web.owner_a.get(canonical)
    assert page.status_code == 200
    assert f'href="{canonical}/workflow"' in page.text
    assert 'id="setup"' in page.text and 'id="funding"' in page.text
    assert "Tool confirmations" in page.text
    workflow_page = web.owner_a.get(canonical + "/workflow")
    assert workflow_page.status_code == 200
    for field in ("goal", "inputs", "deliverable_name", "deliverable_criteria", "cadence", "timezone"):
        assert f'name="{field}"' in workflow_page.text
    for markup in (page.text, workflow_page.text):
        assert f'action="{canonical}/commerce/runs"' not in markup
        assert "Start a fresh task" not in markup
    assert service.dashboard(web.auth_a, instance_id)["runs"] == []
    assert service.dashboard(web.auth_a, instance_id)["balance_micro_usd"] == 0
    invalid = _post(web, canonical + "/workflow/config", goal="Keep this entered goal", inputs="Owner notes",
                    cadence="hourly", timezone="UTC", expected_version="1", deliverable_key="report",
                    deliverable_name="Report", deliverable_description="Useful recommendations", deliverable_criteria="")
    assert invalid.status_code == 422
    assert "Keep this entered goal" in invalid.text and "Owner notes" in invalid.text
    assert not workflow_service(web.app.state.ctx).config(web.auth_a, instance_id)["saved"]


def test_configured_scheduled_purchase_flows_through_independent_audit_and_escaped_output(web):
    instance_id, payments = _create(web, ("inference",))
    canonical = f"/instances/{instance_id}"
    goal = "Cedar <script>alert(1)</script> invites <b>twenty</b> local owners."
    workflow = _save_workflow(web, instance_id, goal=goal)
    saved = web.owner_a.get(canonical + "/workflow")
    assert escape(goal, quote=False) in saved.text
    _make_ready(web, instance_id)
    assert _schedule(web, instance_id, True).status_code == 303
    assert read_instance_snapshot(web.auth_a, instance_id).lifecycle == "active"
    assert workflow.overview(web.auth_a, instance_id)["runs"] == []
    first = _tick(web, instance_id, workflow)
    request, = first["purchases"]
    assert first["deliverables"] == []
    inbox = web.owner_a.get("/audit?view=purchases")
    assert inbox.status_code == 200 and request["id"] in inbox.text
    job_path = f"/audit/jobs/{request['source_job']['id']}"
    assert f'href="{job_path}"' in inbox.text
    with web.app.state.ctx.db.reader() as conn:
        before = list(conn.iterdump())
    job_page = web.owner_a.get(job_path)
    assert job_page.status_code == 200
    assert escape(goal, quote=False) in job_page.text
    assert "<script>alert(1)</script>" not in job_page.text and "<b>twenty</b>" not in job_page.text
    assert "An owner-ready plan." in job_page.text and "Include a headline" in job_page.text
    assert request["quote"]["item_name"] in job_page.text
    assert web.owner_b.get(job_path).status_code == 404
    with web.app.state.ctx.db.reader() as conn:
        assert list(conn.iterdump()) == before
    decision_path = f"/audit/purchases/{request['id']}/decision"
    decision = _post(web, decision_path, decision="approve", continuation="now", quote_digest=request["quote_digest"])
    assert decision.status_code == 303 and decision.headers["location"].startswith("/commerce/orders/")
    approved = payments.purchase(web.auth_a, request["id"])
    assert approved["state"] == "awaiting_checkout" and approved["fulfillment"] is None
    assert workflow.overview(web.auth_a, instance_id)["deliverables"] == []
    order_path = f"/commerce/orders/{approved['order_id']}"
    assert "Choose an account" not in web.owner_a.get(order_path).text  # Reuse the funding buyer.
    _post(web, order_path + "/checkout", outcome="pending")
    assert workflow.overview(web.auth_a, instance_id)["deliverables"] == []
    _post(web, order_path + "/checkout", outcome="complete")
    output, = workflow.overview(web.auth_a, instance_id)["deliverables"]
    assert output["state"] == "submitted" and goal in output["content"]
    detail_path = f"/audit/deliverables/{output['id']}"
    detail = web.owner_a.get(detail_path)
    assert detail.status_code == 200 and escape(goal, quote=False) in detail.text
    assert f'href="{job_path}"' in detail.text
    job_page = web.owner_a.get(job_path)
    assert f'href="{detail_path}"' in job_page.text
    assert "<script>alert(1)</script>" not in detail.text and "<b>twenty</b>" not in detail.text
    assert web.owner_b.get(detail_path).status_code == 404
    review = _post(web, detail_path + "/review", decision="accept", feedback="", expected_version=output["version"])
    assert review.status_code == 303
    assert workflow.deliverable(web.auth_a, output["id"])["state"] == "accepted"
    final = payments.dashboard(web.auth_a, instance_id)
    assert final["policy"]["spent_minor"] == 100 and final["policy"]["held_minor"] == 0


def test_declined_request_remains_in_audit_and_dashboard_reads_never_trigger_work(web):
    instance_id, payments = _create(web, ("inference",))
    workflow = _save_workflow(web, instance_id)
    _make_ready(web, instance_id)
    _schedule(web, instance_id, True)
    first = _tick(web, instance_id, workflow)
    request, = first["purchases"]
    response = _post(web, f"/audit/purchases/{request['id']}/decision", decision="decline",
                     quote_digest=request["quote_digest"], continuation="schedule")
    assert response.status_code == 303
    assert payments.purchase(web.auth_a, request["id"])["state"] == "declined"
    before = workflow.overview(web.auth_a, instance_id)
    balance = payments.dashboard(web.auth_a, instance_id)["balance_micro_usd"]
    for view in ("costs", "actions", "purchases", "deliverables"):
        page = web.owner_a.get(f"/audit?view={view}&instance_id={instance_id}")
        assert page.status_code == 200
        if view == "purchases":
            assert "Declined" in page.text
        if view == "costs":
            assert 'src="/static/vendor/ag-studio.min.js"' in page.text
            assert 'data-kind="costs"' in page.text
    assert workflow.overview(web.auth_a, instance_id) == before
    assert payments.dashboard(web.auth_a, instance_id)["balance_micro_usd"] == balance
    assert payments.dashboard(web.auth_a, instance_id)["policy"]["held_minor"] == 0
    assert web.owner_b.get(f"/audit?instance_id={instance_id}").status_code == 404


def test_rejected_purchase_approval_cannot_change_paid_job_continuation_or_execute_it(web):
    instance_id, payments = _create(web, ("inference",))
    workflow = _save_workflow(web, instance_id)
    _make_ready(web, instance_id)
    _schedule(web, instance_id, True)
    request, = _tick(web, instance_id, workflow)["purchases"]
    decision_path = f"/audit/purchases/{request['id']}/decision"
    approved = _post(web, decision_path, decision="approve", continuation="schedule", quote_digest=request["quote_digest"])
    _post(web, approved.headers["location"] + "/checkout", outcome="complete")
    assert workflow.overview(web.auth_a, instance_id)["deliverables"] == []
    balance = payments.dashboard(web.auth_a, instance_id)["balance_micro_usd"]
    rejected = _post(web, decision_path, decision="approve", continuation="now", quote_digest="0" * 64)
    assert rejected.status_code == 303 and "error=" in rejected.headers["location"]
    waiting = workflow.overview(web.auth_a, instance_id)
    assert waiting["deliverables"] == [] and waiting["runs"][0]["continuation"] == "schedule"
    assert payments.dashboard(web.auth_a, instance_id)["balance_micro_usd"] == balance
    resumed = _post(web, f"/audit/purchases/{request['id']}/continuation", continuation="now")
    assert resumed.status_code == 303
    assert workflow.overview(web.auth_a, instance_id)["deliverables"][0]["state"] == "submitted"


def test_workflow_routes_require_csrf_and_derive_owner_from_session(web):
    from fastapi.testclient import TestClient

    instance_id, _ = _create(web, ("inference",))
    workflow = _save_workflow(web, instance_id, purchase=False)
    _make_ready(web, instance_id)
    _schedule(web, instance_id, True)
    output, = _tick(web, instance_id, workflow)["deliverables"]
    routes = (
        (f"/instances/{instance_id}/workflow/config", {"expected_version": "2"}),
        (f"/instances/{instance_id}/workflow/schedule", {"enabled": "false"}),
        (f"/instances/{instance_id}/workflow/advance", {"expected_due": workflow.config(web.auth_a, instance_id)["next_due"]}),
        (f"/audit/deliverables/{output['id']}/review", {"decision": "accept", "expected_version": "1"}),
        ("/audit/purchases/unowned/decision", {"decision": "approve", "continuation": "now", "quote_digest": "0" * 64}),
        ("/audit/purchases/unowned/refresh", {}),
        ("/audit/purchases/unowned/continuation", {"continuation": "now"}),
    )
    origin = {"origin": web.app.state.ctx.settings.public_base_url}
    with TestClient(web.app) as anonymous:
        assert anonymous.get(f"/instances/{instance_id}/workflow", follow_redirects=False).status_code == 303
        assert anonymous.get(f"/audit/jobs/{output['run_id']}", follow_redirects=False).status_code == 303
        for path, values in routes:
            assert web.owner_a.post(path, data=values, headers=origin).status_code == 403
            secured = {"csrf_token": FIXTURE_CSRF_TOKEN, **values}
            assert anonymous.post(path, data=secured, headers=origin).status_code == 401
            assert web.owner_b.post(path, data=secured, headers=origin).status_code == 404
    assert workflow.deliverable(web.auth_a, output["id"])["state"] == "submitted"
