"""Slice 1: canonical creation, web-app tools and owner operations (F1-S14, F1-S15 lifecycle/capability/limits,
F1-S5/S6/S9 gate rules for capability and budget reasons). Through create_app/TestClient and real SQLite."""

from __future__ import annotations

from datetime import timedelta

import pytest

import seams
from aicl.control.errors import AiclError
from aicl.control.instances import GateContext, Limits

KEY = "wiz_" + "a" * 32
BODY = {"idempotency_key": KEY, "template_id": "default", "name": "  Helper  ", "instructions": "be kind",
        "enabled_capabilities": ["inference"]}


def err(response, status, error):
    assert response.status_code == status, response.text
    assert response.json()["error"] == error
    return response.json()


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/creation/service.py:create_instance")
def test_create_instance_tool_is_idempotent_conflicts_and_validates(web):
    first = web.tool(web.owner_a, "create_instance", BODY)
    assert first.status_code == 200, first.text
    made = first.json()
    snap = made["instance"]
    assert made["created"] is True and made["audit_event_id"] > 0
    assert snap["lifecycle"] == "draft" and snap["version"] == 1 and snap["name"] == "Helper"
    assert snap["limits"] == {"inference_daily_micro_usd": 0, "inference_monthly_micro_usd": 0,
                              "compute_daily_micro_usd": 0, "compute_monthly_micro_usd": 0}
    assert [c for c, on in snap["capabilities"].items() if on] == ["inference"] and snap["attachments"] == []
    assert not {"tenant_id", "owner_id", "secret_ref"} & set(snap)

    replay = web.tool(web.owner_a, "create_instance", BODY).json()
    assert replay["created"] is False and replay["instance"]["id"] == snap["id"]
    conflict = err(web.tool(web.owner_a, "create_instance", {**BODY, "name": "Other"}), 409, "conflict")
    assert conflict["existing_result_id"]
    # the key is scoped to the tenant: another owner reusing it creates their own instance
    other = web.tool(web.owner_b, "create_instance", BODY).json()
    assert other["created"] is True and other["instance"]["id"] != snap["id"]

    from aicl.control.audit import SqliteAuditLog  # one instance.created event, redacted details only
    created = [e for e in SqliteAuditLog().list_for_instance(web.auth_a, snap["id"]) if e.event_type == "instance.created"]
    assert len(created) == 1 and created[0].details == {"template_id": "default", "surface": "ui"}
    assert "be kind" not in repr(created)

    bad = {
        "unknown template": {"template_id": "other"}, "empty name": {"name": "   "}, "long name": {"name": "x" * 81},
        "long instructions": {"instructions": "x" * 4001}, "control char": {"instructions": "a\x00b"},
        "unknown capability": {"enabled_capabilities": ["nope"]},
        "short key": {"idempotency_key": "short"}, "colon key": {"idempotency_key": "chat:" + "a" * 20},
        "long key": {"idempotency_key": "k" * 65},
    }
    for label, change in bad.items():
        body = {**BODY, "idempotency_key": "wiz_" + "b" * 32, **change}
        out = err(web.tool(web.owner_a, "create_instance", body), 422, "validation_failed")
        assert out["field_errors"], label
    ok_edge = {**BODY, "idempotency_key": "wiz_" + "c" * 32, "name": "x" * 80, "instructions": "x" * 4000}
    assert web.tool(web.owner_a, "create_instance", ok_edge).status_code == 200
    with web.app.state.ctx.db.reader() as conn:  # validation failures created nothing: 2 instances for owner A
        assert conn.execute("SELECT count(*) FROM agent_instance WHERE tenant_id = ?",
                            (web.auth_a.tenant_id,)).fetchone()[0] == 2


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/creation/tools.py:TOOL_REGISTRY")
def test_tool_registry_is_exactly_three_tools_and_rejects_authority_arguments(web):
    templates = web.tool(web.owner_a, "list_templates", {})
    assert templates.status_code == 200, templates.text
    assert "default" in templates.text and "gmail.send" in templates.text
    made = web.tool(web.owner_a, "create_instance", BODY).json()["instance"]
    read = web.tool(web.owner_a, "read_instance", {"instance_id": made["id"]})
    assert read.status_code == 200 and read.json()["id"] == made["id"]
    assert not {"tenant_id", "owner_id", "budget", "usage", "audit", "pending_actions", "secret_ref"} & set(read.json())
    err(web.tool(web.owner_b, "read_instance", {"instance_id": made["id"]}), 404, "not_found")  # other tenant

    forbidden = {"tenant_id": "x", "owner_id": "x", "session_id": "x", "access_token": "t", "secret": "s",
                 "credential": "c", "confirmation_id": "c", "confirmed": True}
    for field, value in forbidden.items():
        for name, body in (("create_instance", {**BODY, "idempotency_key": "wiz_" + "d" * 32, field: value}),
                           ("read_instance", {"instance_id": made["id"], field: value}),
                           ("list_templates", {field: value})):
            out = err(web.tool(web.owner_a, name, body), 422, "validation_failed")
            assert any(e["code"] == "unknown_argument" for e in out["field_errors"]), (name, field)
    for name in ("set_lifecycle", "set_capability", "set_limits", "add_network_domain", "resolve_gate",
                 "attach_connection", "create_confirmation", "reserve", "revoke_connection", "work_request"):
        assert web.tool(web.owner_a, name, {}).status_code == 404, name  # no other operation is a tool
    no_csrf = web.owner_a.post("/app-tools/list_templates", json={})
    assert no_csrf.status_code in (401, 403) and no_csrf.json()["error"] in ("denied", "unauthenticated")


@pytest.fixture
def ops(build_env):
    env = build_env()
    return env, seams.instance_operations(env)


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/creation/operations.py:InstanceOperations")
def test_owner_operations_bump_version_audit_conflict_noop_and_archived(ops):
    env, o = ops
    auth, inst = env.new_instance(limits=Limits())
    stranger_id = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(AiclError) as e:
        o.set_lifecycle(auth, stranger_id, 1, "activate")
    assert e.value.error == "not_found"

    with pytest.raises(AiclError) as e:  # stale version: conflict with current_version and no effect
        o.set_lifecycle(auth, inst.id, 7, "activate")
    assert e.value.error == "conflict" and e.value.extra["current_version"] == 1
    assert env.instances.get(auth, inst.id).lifecycle == "draft" and env.audit.list_for_instance(auth, inst.id) == []

    res = o.set_lifecycle(auth, inst.id, 1, "activate")
    assert res.changed and res.instance.lifecycle == "active" and res.instance.version == 2
    assert res.audit_event_id and [e.event_type for e in env.audit.list_for_instance(auth, inst.id)] == ["instance.lifecycle_changed"]
    with pytest.raises(AiclError) as e:
        o.set_lifecycle(auth, inst.id, 2, "activate")  # active -> activate is not in the table
    assert e.value.error == "invalid_transition" and e.value.extra["from"] == "active"

    cap = o.set_capability(auth, inst.id, 2, "gmail.read", True)
    assert cap.instance.capabilities["gmail.read"] is True and cap.instance.version == 3
    same = o.set_capability(auth, inst.id, 3, "gmail.read", True)  # no-op at the current version
    assert same.changed is False and same.instance.version == 3 and same.audit_event_id is None
    with pytest.raises(AiclError) as e:
        o.set_capability(auth, inst.id, 3, "not.a.capability", True)
    assert e.value.error == "validation_failed"

    limits = Limits(10, 20, 30, 40)
    assert o.set_limits(auth, inst.id, 3, limits).instance.limits == limits
    with pytest.raises(AiclError) as e:
        o.set_limits(auth, inst.id, 3, Limits(-1, 0, 0, 0))  # stale AND invalid: stale version wins or validation, never effect
    assert e.value.error in ("conflict", "validation_failed")
    assert env.instances.get(auth, inst.id).limits == limits

    o.set_lifecycle(auth, inst.id, 4, "archive")
    with pytest.raises(AiclError) as e:
        o.set_capability(auth, inst.id, 5, "gmail.read", False)
    assert e.value.error == "invalid_state" and e.value.extra["lifecycle"] == "archived"


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/creation/operations.py:evaluate_gate_control")
def test_resolve_gate_for_capability_and_budget_reasons_clears_only_when_control_permits(ops):
    env, o = ops
    full = Limits(1_000_000, 10_000_000, 1_000_000, 10_000_000)
    auth, inst = env.new_instance(limits=Limits(), capabilities=())
    o.set_lifecycle(auth, inst.id, 1, "activate")  # version 2
    with env.db.transaction() as conn:
        env.instances.set_gated(conn, auth, inst.id, "capability_disabled", GateContext(("gmail.read",), None))

    def resolve(version):
        return o.resolve_gate(auth, inst.id, version)

    no_gate_auth, no_gate = env.new_instance()
    assert o.resolve_gate(no_gate_auth, no_gate.id, 1).changed is False  # nothing persisted
    with pytest.raises(AiclError) as e:
        resolve(2)
    assert e.value.error == "denied" and e.value.extra["reason"] == "gate_unresolved"
    assert env.instances.get(auth, inst.id).gated_reason == "capability_disabled" and env.instances.get(auth, inst.id).version == 2
    denied = [x for x in env.audit.list_for_instance(auth, inst.id) if x.event_type == "instance.gate_resolved"]
    assert [x.outcome for x in denied] == ["denied"]

    fixed = o.set_capability(auth, inst.id, 2, "gmail.read", True)  # fixing mutation clears in the same transaction
    assert fixed.instance.gated_reason is None and fixed.instance.version == 3

    for reason in ("budget_exhausted", "budget_unavailable"):  # zero limits deny; a rollover never clears
        with env.db.transaction() as conn:
            env.instances.set_gated(conn, auth, inst.id, reason, GateContext())
        version = env.instances.get(auth, inst.id).version
        env.clock.advance(timedelta(days=40))
        with pytest.raises(AiclError) as e:
            resolve(version)
        assert e.value.extra["reason"] == "gate_unresolved"
        assert env.instances.get(auth, inst.id).gated_reason == reason
        env.clock.advance(timedelta(days=-40))
        cleared = o.set_limits(auth, inst.id, version, full)
        assert cleared.instance.gated_reason is None  # set_limits re-evaluates and clears
        o.set_limits(auth, inst.id, cleared.instance.version, Limits())
    with env.db.transaction() as conn:  # explicit resolve_gate once the control permits
        env.instances.set_gated(conn, auth, inst.id, "budget_exhausted", GateContext())
    version = env.instances.get(auth, inst.id).version
    o.set_limits(auth, inst.id, version, full)
    with env.db.transaction() as conn:
        env.instances.set_gated(conn, auth, inst.id, "budget_exhausted", GateContext())
    version = env.instances.get(auth, inst.id).version
    resolved = resolve(version)
    assert resolved.changed and resolved.instance.gated_reason is None and resolved.instance.version == version + 1
