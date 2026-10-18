"""E11-5 proofs (F3-S4, F3-S5, F3-S7, F2-S1, F2-S2, F2-S3, F2-S6): read projections over the real SQLite Env and the
owner pages through the real create_app. Operations and gate rules are NOT re-tested (E11-2); this proves that the
pages project them truthfully (tenant filter, USD, allow-listed audit, no secret_ref) and post
expected_version + CSRF to the existing operations, showing the committed result or the structured denial."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import pytest

import seams
from aicl.app import FIXTURE_CSRF_TOKEN
from aicl.connections.ports import FakeProviderOAuth
from aicl.control.audit import DETAILS_ALLOW_LIST
from aicl.control.budget import Estimate
from aicl.control.errors import AiclError
from aicl.control.instances import Limits
from aicl.creation.service import read_instance_snapshot
from aicl.web.views import SqliteProjectionService, format_usd, parse_usd
from aicl.work.models import WorkRequest
from aicl.work.ports import FakeWorkExecutor
from support import work_id

KEY = bytes(range(32))
GENEROUS = Limits(1_000_000, 10_000_000, 1_000_000, 10_000_000)
BODY_MARKER = "PAYLOAD-BODY-MUST-NOT-RENDER"


@pytest.mark.ac("E11-5.AC1", code="backend/aicl/web/views.py:SqliteProjectionService")
def test_projections_are_tenant_filtered_usd_rendered_and_never_carry_bodies_or_secret_refs(build_env):
    env = build_env()
    projections = SqliteProjectionService(env.db, env.clock, env.budget.hold_stale_seconds)
    auth, inst = env.new_instance(capabilities=("inference",))
    other_auth, other = env.new_instance()
    ops = seams.instance_operations(env)
    version = ops.set_lifecycle(auth, inst.id, 1, "activate").instance.version

    assert (format_usd(1_500_000), format_usd(0), format_usd(1)) == ("1.500000", "0.000000", "0.000001")
    assert parse_usd("1.5") == 1_500_000 and parse_usd("0.000001") == 1
    for bad in ("-1", "abc", "1.1234567", "1000000.000001"):  # malformed, negative, >6 decimals, > MAX_LIMIT_MICRO_USD
        with pytest.raises(AiclError) as err:
            parse_usd(bad)
        assert err.value.error == "validation_failed", bad

    store = seams.aes_secret_store(KEY)
    svc = seams.connection_service(env, FakeProviderOAuth(), store)
    begun = svc.begin_oauth(auth, "gmail", ("gmail.send",), "Work mailbox")
    connection = svc.complete_oauth(auth, parse_qs(urlparse(begun["authorization_url"]).query)["state"][0],
                                    "fake-code-ok")
    ops.attach_connection(auth, inst.id, version, "gmail.send", connection.id)
    gate = seams.work_gate(env, FakeWorkExecutor(), None)
    done = gate.authorize_and_dispatch(auth, WorkRequest(
        instance_id=inst.id, work_id=work_id(1), capability="inference", estimate=Estimate(0, 0, 2),
        payload={"sim": {"compute_minutes": 2}, "note": BODY_MARKER}))
    assert done.outcome == "succeeded"

    workspace = projections.workspace(auth)
    assert [s.name for s in workspace.instances] == ["Default"] and workspace.instances[0].id == inst.id
    assert projections.workspace(other_auth).instances[0].id == other.id  # each tenant sees only its own row

    detail = projections.instance_detail(auth, inst.id)
    assert detail.snapshot == read_instance_snapshot(auth, inst.id, clock=env.clock)  # composed unchanged
    assert detail.snapshot.attachments[0].connection_id == connection.id
    assert detail.budget == env.budget.read_budget(inst.id)
    assert len(detail.usage_history) == 1 and detail.usage_history[0].compute_micro_usd == 10_000
    kinds = {e.event_type for e in detail.audit}
    assert {"budget.reserved", "budget.settled"} <= kinds  # allow-listed budget.* events are shown
    assert all(set(e.details) <= DETAILS_ALLOW_LIST for e in detail.audit)
    assert BODY_MARKER not in repr(detail) and "secret" not in repr(detail).lower()
    with pytest.raises(AiclError) as foreign:
        projections.instance_detail(other_auth, inst.id)
    assert foreign.value.error == "not_found"

    view = projections.connections(auth)
    assert [(c.id, c.provider, c.display_name, c.status) for c in view.connections] == [
        (connection.id, "gmail", "Work mailbox", "active")]
    assert [(a.connection_id, a.instance_id, a.capability) for a in view.attachments] == [
        (connection.id, inst.id, "gmail.send")]
    assert "secret_ref" not in repr(view) and "scope" not in repr(view).lower()
    assert projections.connections(other_auth) == type(view)((), ())  # another tenant sees no connections


def page_form(client, **fields):
    return {"csrf_token": FIXTURE_CSRF_TOKEN, **{k: str(v) for k, v in fields.items()}}


@pytest.mark.ac("E11-5.AC1", code="backend/aicl/web/manage.py:manage_router")
def test_owner_pages_post_expected_version_and_csrf_and_show_the_committed_result_or_the_structured_denial(web):
    a, b = web.owner_a, web.owner_b
    made = web.tool(a, "create_instance", {"idempotency_key": "wiz_" + "c" * 32, "template_id": "default",
                                           "name": "Pages Helper", "instructions": "", "enabled_capabilities": ["inference"]}
                    ).json()["instance"]
    iid = made["id"]
    origin = web.app.state.ctx.settings.public_base_url
    headers = {"x-csrf-token": FIXTURE_CSRF_TOKEN, "origin": origin}

    def version() -> int:
        return read_instance_snapshot(web.auth_a, iid).version

    def post(path: str, **fields):
        return a.post(f"/instances/{iid}{path}", data=page_form(a, expected_version=version(), **fields),
                      follow_redirects=True)

    # unauthenticated visitors are redirected, another tenant gets not_found, and every POST needs CSRF
    anonymous = a.__class__(web.app)
    assert anonymous.get(f"/instances/{iid}", follow_redirects=False).status_code in (302, 303, 307)
    assert anonymous.get("/connections", follow_redirects=False).status_code in (302, 303, 307)
    assert b.get(f"/instances/{iid}").status_code == 404
    assert a.post(f"/instances/{iid}/lifecycle", data={"expected_version": 1, "action": "activate"}).status_code == 403
    assert b.post(f"/instances/{iid}/lifecycle", data=page_form(b, expected_version=1, action="activate")).status_code == 404
    assert read_instance_snapshot(web.auth_a, iid).lifecycle == "draft"

    page = a.get(f"/instances/{iid}")
    assert page.status_code == 200 and "Pages Helper" in page.text and "draft" in page.text
    assert "0.000000" in page.text  # budget rendered as USD with six decimals
    assert "secret_ref" not in page.text and "real provider adapters are not enabled" in page.text.lower()

    stale = a.post(f"/instances/{iid}/lifecycle", data=page_form(a, expected_version=99, action="activate"))
    assert stale.status_code == 409 and "conflict" in stale.text and read_instance_snapshot(web.auth_a, iid).version == 1
    assert "active" in post("/lifecycle", action="activate").text
    assert read_instance_snapshot(web.auth_a, iid).lifecycle == "active"
    assert "invalid_transition" in post("/lifecycle", action="activate").text  # active cannot be activated again

    post("/capabilities", capability="gmail.send", enabled="true")
    post("/domains", host="Example.COM")
    snapshot = read_instance_snapshot(web.auth_a, iid)
    assert snapshot.capabilities["gmail.send"] is True and snapshot.network_domains == ("example.com",)
    post("/domains/remove", host="example.com")
    assert read_instance_snapshot(web.auth_a, iid).network_domains == ()
    assert "limit" in post("/limits", inference_daily_usd="-1", inference_monthly_usd="1", compute_daily_usd="1",
                           compute_monthly_usd="1").text.lower()  # field error, nothing committed
    assert read_instance_snapshot(web.auth_a, iid).limits == Limits()

    # zero limits: a simulated work request is denied and gates; re-check keeps the gate with gate_unresolved
    url = f"/instances/{iid}/work-requests"
    body = {"work_id": "work_" + "1" * 32, "capability": "inference", "payload": {"sim": {"compute_minutes": 2}},
            "estimate": {"inference_input_tokens": 0, "inference_output_tokens": 0, "compute_minutes": 2}}
    denied = a.post(url, json=body, headers=headers)
    assert denied.status_code == 403 and denied.json()["reason"] == "budget_exhausted"
    assert "budget_exhausted" in a.get("/workspace").text and "budget_exhausted" in a.get(f"/instances/{iid}").text
    unresolved = post("/resolve-gate")
    assert "gate_unresolved" in unresolved.text and read_instance_snapshot(web.auth_a, iid).gated_reason == "budget_exhausted"

    raised = post("/limits", inference_daily_usd="1", inference_monthly_usd="10", compute_daily_usd="1",
                  compute_monthly_usd="10")
    assert raised.status_code == 200 and read_instance_snapshot(web.auth_a, iid).limits == GENEROUS
    assert "gate_unresolved" not in post("/resolve-gate").text
    assert read_instance_snapshot(web.auth_a, iid).gated_reason is None

    ok = a.post(url, json={**body, "work_id": "work_" + "2" * 32, "payload": {"sim": {"compute_minutes": 2},
                                                                            "note": BODY_MARKER}}, headers=headers)
    assert ok.status_code == 200 and ok.json()["outcome"] == "succeeded"
    detail = a.get(f"/instances/{iid}").text
    assert "0.010000" in detail  # settled usage in USD
    assert "budget.settled" in detail  # allow-listed budget.* audit event is shown
    for hidden in (BODY_MARKER, "secret_ref", "access_token", "refresh_token", "fake-code"):
        assert hidden not in detail, hidden
    assert b.get("/workspace").text.count("Pages Helper") == 0  # another tenant never sees it
