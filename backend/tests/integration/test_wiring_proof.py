"""E11-5 composition and cross-surface proof (F3-S3, F3-S9): the test composition registers every route factory,
port and startup hook, startup fails closed when a required port has no factory, and wizard, chat and a direct
canonical call create equivalent instances. Test-composition evidence only; leaf ports are the fakes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aicl import hooks, ports, routes
from aicl.app import FIXTURE_CSRF_TOKEN, create_app
from aicl.chat.ports import ScriptedChatModel
from aicl.chat.service import SqliteChatOrchestrator
from aicl.creation.models import CreateInstanceRequest
from aicl.creation.service import create_instance, read_instance_snapshot
from aicl.settings import Settings
from aicl.web.proof import (
    EQUIVALENCE_FIELDS, FINAL_REQUIRED_PORTS, FINAL_STARTUP_HOOKS, CompositionIncomplete, equivalent_surfaces,
    inspect_composition,
)

TEST_FLAGS = {"AICL_ENVIRONMENT": "test", "AICL_TEST_MODE": "1"}


@pytest.mark.ac("E11-5.AC1", code="backend/aicl/web/proof.py:inspect_composition")
def test_test_composition_registers_every_port_route_and_hook(base_env, tmp_path):
    app = create_app(Settings.from_env({**base_env, **TEST_FLAGS, "AICL_DATABASE_URL": f"sqlite:///{tmp_path / 'p.db'}"}))
    report = inspect_composition(app)
    assert report.port_names == FINAL_REQUIRED_PORTS == ports.REQUIRED_PORTS
    assert report.route_factory_names == tuple(f.__name__ for f in routes.ROUTE_FACTORIES)
    assert "manage_router" in report.route_factory_names and len(report.route_factory_names) == 5
    assert report.hook_names == FINAL_STARTUP_HOOKS == tuple(h.__name__ for h in hooks.STARTUP_HOOKS)
    assert {"/instances/{instance_id}", "/connections", "/instances/{instance_id}/resolve-gate", "/workspace",
            "/chat", "/agents/new", "/auth/verify", "/instances/{instance_id}/work-requests",
            "/pending-actions/{pending_action_id}/confirm", "/connections/oauth/begin"} <= report.route_paths
    assert report.test_only_paths and all(p.startswith("/__test__/") for p in report.test_only_paths)
    plain = create_app(Settings.from_env({**base_env, "AICL_DATABASE_URL": f"sqlite:///{tmp_path / 'q.db'}"}))
    assert inspect_composition(plain).test_only_paths == frozenset()



@pytest.mark.ac("E11-5.AC1", code="backend/aicl/ports.py:build_ports")
def test_startup_fails_closed_when_a_required_port_has_no_registered_factory(base_env, tmp_path):
    # F-1: a REQUIRED_PORTS name without a registered factory fails startup (`clock` keeps its SystemClock default)
    settings = Settings.from_env({**base_env, **TEST_FLAGS, "AICL_DATABASE_URL": f"sqlite:///{tmp_path / 'm.db'}"})
    for name in [n for n in FINAL_REQUIRED_PORTS if n != "clock"]:
        factory = ports.PORT_REGISTRY.pop(name)
        try:
            with pytest.raises(CompositionIncomplete, match=name):
                create_app(settings)
        finally:
            ports.PORT_REGISTRY[name] = factory
    assert ports.build_ports(settings).chat_model is not None  # the restored registry builds again


@pytest.mark.ac("E11-5.AC1", code="backend/aicl/web/proof.py:equivalent_surfaces")
def test_wizard_chat_and_direct_canonical_creation_are_equivalent_for_equal_input(web):
    wizard_form = {"csrf_token": FIXTURE_CSRF_TOKEN, "idempotency_key": "wiz_" + "d" * 32, "name": "Same Helper",
                   "instructions": "Answer politely", "capabilities": ["inference"]}
    assert web.owner_a.post("/agents/new", data=wizard_form).status_code == 200
    ctx = web.app.state.ctx
    chat = SqliteChatOrchestrator(ctx.db, ctx.clock, ScriptedChatModel())
    session, created = None, None
    for text in ("hello", "Same Helper", "Answer politely", "inference", "yes", "yes", "yes"):
        reply = chat.handle_message(web.auth_b, session, text)
        session, created = reply.chat_session_id, reply.instance_id or created
    assert created
    request = CreateInstanceRequest(idempotency_key="own_" + "e" * 32, template_id="default", name="Same Helper",
                                    instructions="Answer politely", enabled_capabilities=frozenset({"inference"}))
    direct = create_instance(web.auth_b, request, actor_kind="owner", surface="ui", clock=ctx.clock).instance
    chat_snapshot = read_instance_snapshot(web.auth_b, created, clock=ctx.clock)
    with ctx.db.reader() as conn:
        wizard_id = conn.execute("SELECT id FROM agent_instance WHERE tenant_id = ? AND name = 'Same Helper'",
                                 (web.auth_a.tenant_id,)).fetchone()["id"]
    wizard_snapshot = read_instance_snapshot(web.auth_a, wizard_id, clock=ctx.clock)
    assert "id" not in EQUIVALENCE_FIELDS
    assert equivalent_surfaces(wizard_snapshot, chat_snapshot) and equivalent_surfaces(chat_snapshot, direct)
    assert not equivalent_surfaces(wizard_snapshot, create_instance(
        web.auth_b, request.model_copy(update={"idempotency_key": "own_" + "f" * 32, "name": "Different"}),
        clock=ctx.clock).instance)
