"""Slice 4: dispatch gate order, denials, atomic step 9, confirmations, executor (F1-S5/S6/S9/S16, F2-S6/S9)."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest

import seams
from aicl.connections.ports import FakeProviderOAuth
from aicl.control.budget import Estimate, MeasuredUsage
from aicl.control.confirmation import payload_digest
from aicl.control.errors import AiclError
from aicl.control.instances import Limits
from aicl.network.policy import FakeResolver
from aicl.work.gate import GATE_CHECK_ORDER
from aicl.work.models import AuthorizedWork, WorkRequest, WorkResult
from aicl.work.ports import FakeWorkExecutor
from support import work_id

GENEROUS = Limits(1_000_000, 10_000_000, 1_000_000, 10_000_000)
EST = Estimate(0, 0, 1)  # 5000 micro-USD of compute with the example price table
RESOLVER = FakeResolver({"gmail.googleapis.com": ["142.250.0.1"], "example.com": ["93.184.216.34"]})
KEY = bytes(range(32))


def req(inst, n, cap="inference", payload=None, estimate=EST, url=None):
    return WorkRequest(instance_id=inst.id, work_id=work_id(n), capability=cap, payload=payload or {},
                       estimate=estimate, destination_url=url)


def active(env, caps=(), limits=GENEROUS):
    ops = seams.instance_operations(env)
    auth, inst = env.new_instance(limits=limits, capabilities=caps)
    ops.set_lifecycle(auth, inst.id, 1, "activate")
    return auth, env.instances.get(auth, inst.id), ops


def build_gate(env, executor=None, resolver=RESOLVER):
    executor = executor or FakeWorkExecutor()
    return seams.work_gate(env, executor, resolver), executor


def denial(gate, auth, request) -> str:
    result = gate.authorize_and_dispatch(auth, request)
    assert isinstance(result, WorkResult) and result.outcome == "denied", result
    return result.denial_reason


def holds(env, inst) -> int:
    with env.db.reader() as conn:
        return conn.execute("SELECT count(*) FROM budget_hold WHERE instance_id = ?", (inst.id,)).fetchone()[0]


def confirmation_used(env, inst) -> list:
    with env.db.reader() as conn:
        return [r["used_at"] is not None for r in conn.execute(
            "SELECT used_at FROM action_confirmation WHERE instance_id = ?", (inst.id,))]


def audit_types(env, auth, inst):
    return [e.event_type for e in reversed(env.audit.list_for_instance(auth, inst.id))]


def attach_gmail(env, ops, auth, inst, caps=("gmail.send",)):
    svc = seams.connection_service(env, FakeProviderOAuth(), seams.aes_secret_store(KEY))
    from urllib.parse import parse_qs, urlparse
    begun = svc.begin_oauth(auth, "gmail", caps)
    url = begun["authorization_url"] if isinstance(begun, dict) else begun
    conn = svc.complete_oauth(auth, parse_qs(urlparse(url).query)["state"][0], "fake-code-ok")
    version = env.instances.get(auth, inst.id).version
    for cap in caps:
        version = ops.attach_connection(auth, inst.id, version, cap, conn.id).instance.version
    return svc, conn


def test_unknown_network_policy_cannot_silently_dispatch_search(build_env):
    env = build_env()
    resolver = FakeResolver({"api.search.example": ["93.184.216.34"]})
    gate, executor = build_gate(env, resolver=resolver)
    auth, inst, _ = active(env, caps=("network.search",))
    attempted = req(inst, 900, "network.search", {"query": "private-canary"},
                    url="https://api.search.example/search")
    assert denial(gate, auth, attempted) == "network_denied"
    assert resolver.calls == []
    assert executor.started == frozenset()
    assert holds(env, inst) == 0
    assert "private-canary" not in repr(env.audit.list_for_owner(auth))


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/work/ports.py:FakeWorkExecutor")
def test_fake_executor_records_started_first_is_deterministic_and_looks_up_honestly(build_env):
    env = build_env()
    auth, inst = env.new_instance()
    ex = FakeWorkExecutor(db=env.db)
    assert ex.lookup("never-seen-hold-id").status == "not_started"

    def work(n, payload, capability="inference"):
        with env.db.transaction() as conn:
            hold = env.budget.reserve(conn, inst.id, work_id(n), EST)
        return AuthorizedWork(work_id(n), inst.id, capability, payload, hold.id, None, None)

    first = work(1, {"sim": {"input_tokens": 10, "output_tokens": 20, "compute_minutes": 3}})
    out = ex.execute(first)
    assert out.status == "succeeded" and out.measured_usage == MeasuredUsage(10, 20, 3)
    assert first.hold_id in ex.started and ex.lookup(first.hold_id) == out
    assert FakeWorkExecutor(db=env.db).execute(first) == out  # durable idempotency after restart
    assert ex.execute(work(2, {})).measured_usage == MeasuredUsage(0, 0, 0)
    assert ex.execute(work(3, {"sim": {"outcome": "failed", "compute_minutes": 1}})).status == "failed"
    assert ex.execute(work(4, {"sim": {"outcome": "unknown"}})).status == "unknown"
    assert ex.execute(work(5, {"sim": {"outcome": "not_started"}})).status == "not_started"

    seen = []

    class CrashBroker:
        def call(self, authorized, operation):
            # A separate executor sees the committed start before a provider side effect.
            seen.append(FakeWorkExecutor(db=env.db).lookup(authorized.hold_id).__class__.__name__)
            raise TimeoutError("interrupted before outcome storage")

    crash = FakeWorkExecutor(CrashBroker(), env.db)
    sixth = work(6, {}, "gmail.read")
    with pytest.raises(TimeoutError):
        crash.execute(sixth)
    assert seen == ["StillUnknown"]
    assert FakeWorkExecutor(db=env.db).lookup(sixth.hold_id).__class__.__name__ == "StillUnknown"

    # An unseen stale hold can be released, but the recorded not-started verdict fences delayed execution.
    seventh = work(7, {}, "gmail.read")
    assert ex.lookup(seventh.hold_id).status == "not_started"
    assert crash.execute(seventh).status == "not_started"
    assert seen == ["StillUnknown"]  # no provider call after the not-started verdict


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/work/gate.py:WorkAuthorization")
def test_gate_runs_fixed_order_denies_at_first_failure_and_reserves_last(build_env):
    assert GATE_CHECK_ORDER == ("identity", "instance", "lifecycle", "capability", "estimate", "confirmation",
                                "connection", "network", "reserve_and_consume", "dispatch")
    env = build_env()
    ex = FakeWorkExecutor()
    resolver = FakeResolver({"gmail.googleapis.com": ["142.250.0.1"]})
    gate = seams.work_gate(env, ex, resolver)
    ops = seams.instance_operations(env)
    auth, inst = env.new_instance(limits=Limits(), capabilities=())
    stranger, _ = env.new_instance()
    payload = {"to": "a@example.com", "body": "SECRET-BODY"}
    send = lambda n, estimate=EST: req(inst, n, "gmail.send", payload, estimate, None)

    with pytest.raises(AiclError) as e:  # 2: another tenant's instance is not_found, never denied
        gate.authorize_and_dispatch(stranger, send(1))
    assert e.value.error == "not_found"
    assert denial(gate, auth, send(1)) == "instance_not_active"  # 3: draft; nothing persisted
    assert env.instances.get(auth, inst.id).gated_reason is None
    ops.set_lifecycle(auth, inst.id, 1, "activate")
    assert denial(gate, auth, send(1, None)) == "capability_disabled"  # 4 before 5 (estimate missing too)
    gated = env.instances.get(auth, inst.id)
    assert gated.gated_reason == "capability_disabled" and gated.gate_context.capabilities == ("gmail.send",)
    ops.set_capability(auth, inst.id, 2, "gmail.send", True)  # fixing mutation clears the persisted gate
    assert env.instances.get(auth, inst.id).gated_reason is None
    assert denial(gate, auth, send(1, None)) == "estimate_missing"  # 5 before 6
    pending = gate.authorize_and_dispatch(auth, send(1))  # 6 before 7 (no connection yet)
    assert pending.denial_reason == "confirmation_required" and pending.pending_action_id
    assert env.instances.get(auth, inst.id).gated_reason is None  # confirmation denials never gate
    with env.db.transaction() as conn:
        env.confirmations.create_confirmation(conn, auth, pending.pending_action_id)
    assert denial(gate, auth, send(1)) == "connection_unavailable"  # 7 before 8/9; persists connection gate
    assert env.instances.get(auth, inst.id).gated_reason in ("connection_revoked", "connection_reauthorization_required")
    assert resolver.calls == [] and holds(env, inst) == 0 and confirmation_used(env, inst) == [False]  # 8 and 9 never ran
    _, conn = attach_gmail(env, ops, auth, inst)
    assert env.instances.get(auth, inst.id).gated_reason is None  # attach cleared the connection gate
    assert denial(gate, auth, send(1)) == "budget_exhausted"  # 9: zero limits; network (8) passed first
    assert resolver.calls == ["gmail.googleapis.com"] and holds(env, inst) == 0
    assert confirmation_used(env, inst) == [False]  # a failed reservation does not burn the confirmation
    assert env.instances.get(auth, inst.id).gated_reason == "budget_exhausted"  # budget reasons persist
    version = env.instances.get(auth, inst.id).version
    ops.set_limits(auth, inst.id, version, GENEROUS)
    assert env.instances.get(auth, inst.id).gated_reason is None
    done = gate.authorize_and_dispatch(auth, send(1))  # same work_id: denials were not stored under it
    assert done.outcome == "succeeded" and done.hold_state == "settled" and done.usage is not None
    assert confirmation_used(env, inst) == [True] and holds(env, inst) == 1
    types = audit_types(env, auth, inst)
    assert types.count("work.denied") >= 6 and "work.dispatched" in types
    assert "SECRET-BODY" not in repr(env.audit.list_for_owner(auth)) and "a@example.com" not in repr(env.audit.list_for_owner(auth))
    # list_for_instance is newest first (control-plane technical.md audit readers), so the latest denial is [0]
    assert [e.details.get("denial_reason") for e in env.audit.list_for_instance(auth, inst.id)
            if e.event_type == "work.denied"][0] == "budget_exhausted"


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/work/gate.py:WorkAuthorization")
def test_confirmation_is_single_use_bound_to_payload_expires_and_consumption_is_atomic(build_env):
    env = build_env(ttl_seconds=300)
    gate, ex = build_gate(env)
    auth, inst, ops = active(env, caps=("gmail.send",))
    attach_gmail(env, ops, auth, inst)
    a, b = {"to": "a@example.com"}, {"to": "b@example.com"}
    send = lambda n, payload, estimate=EST: req(inst, n, "gmail.send", payload, estimate)

    def confirm(result):
        with env.db.transaction() as conn:
            return env.confirmations.create_confirmation(conn, auth, result.pending_action_id)

    first = gate.authorize_and_dispatch(auth, send(1, a))
    assert first.denial_reason == "confirmation_required" and holds(env, inst) == 0
    again = gate.authorize_and_dispatch(auth, send(1, a))
    assert again.pending_action_id == first.pending_action_id  # PendingAction created or reused
    confirmation = confirm(first)
    assert denial(gate, auth, send(2, b)) == "confirmation_mismatch"  # changed payload
    assert holds(env, inst) == 0 and confirmation_used(env, inst) == [False]
    ok = gate.authorize_and_dispatch(auth, send(1, a))  # confirmed resubmission with the same work_id
    assert ok.outcome == "succeeded" and confirmation_used(env, inst) == [True]
    assert denial(gate, auth, send(3, a)) == "confirmation_used"  # replay with a new work_id: single use
    assert holds(env, inst) == 1

    second = gate.authorize_and_dispatch(auth, send(4, b))  # expiry
    c2 = confirm(second)
    env.clock.advance(timedelta(seconds=301))
    assert denial(gate, auth, send(4, b)) == "confirmation_expired" and holds(env, inst) == 1
    assert c2.id != confirmation.id

    third = gate.authorize_and_dispatch(auth, send(5, a))  # reverse atomicity: a lost consume race is confirmation_used
    c3 = confirm(third)
    with env.db.transaction() as conn:  # a concurrent dispatch consumed it between the read and step 9
        assert env.confirmations.consume_confirmation(conn, c3.id, payload_digest(inst.id, "gmail.send", a), env.clock.now())
    assert denial(gate, auth, send(5, a)) == "confirmation_used"
    assert holds(env, inst) == 1  # the failed consumption left no reservation behind

    fourth = gate.authorize_and_dispatch(auth, send(6, b, Estimate(0, 0, 10_000_000)))  # reservation fails => confirmation kept
    confirm(fourth)
    assert denial(gate, auth, send(6, b, Estimate(0, 0, 10_000_000))) == "budget_exhausted"
    assert confirmation_used(env, inst)[-1] is False and holds(env, inst) == 1
    # the executor ran only for the one successful dispatch
    assert len(ex.started) == 1


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/work/gate.py:WorkAuthorization")
def test_network_denials_gate_only_for_owner_resolvable_allow_list_miss(build_env):
    env = build_env()
    gate, ex = build_gate(env)
    auth, inst, ops = active(env, caps=("network.fetch",))
    fetch = lambda n, url: req(inst, n, "network.fetch", {}, EST, url)
    assert denial(gate, auth, fetch(1, "https://example.com/a")) == "network_denied"  # host not in the allow-list
    gated = env.instances.get(auth, inst.id)
    assert gated.gated_reason == "network_denied" and gated.gate_context.host_hash12 == hashlib.sha256(b"example.com").hexdigest()[:12]
    assert "example.com" not in repr(gated.gate_context)  # only a hash prefix is persisted
    version = gated.version
    ops.add_network_domain(auth, inst.id, version, "example.com")  # fixing mutation clears and permits
    assert env.instances.get(auth, inst.id).gated_reason is None
    ok = gate.authorize_and_dispatch(auth, fetch(1, "https://example.com/a"))
    assert ok.outcome == "succeeded"

    for n, url in enumerate(("http://example.com/", "https://example.com:8443/", "https://u:p@example.com/",
                             "https://127.0.0.1/", "https://[::1]/"), start=10):
        assert denial(gate, auth, fetch(n, url)) == "network_denied"
        assert env.instances.get(auth, inst.id).gated_reason is None  # structural denials persist no gate
    denied = [e for e in env.audit.list_for_instance(auth, inst.id) if e.event_type == "work.denied"]
    assert len(denied) == 6 and all(e.reason for e in denied[:5])  # audited with the rule
    assert not any("example.com/" in repr(e.details) or "127.0.0.1" in repr(e.details) for e in denied)
    ops.add_network_domain(auth, inst.id, env.instances.get(auth, inst.id).version, "rebind.example.com")
    rebinding = FakeResolver({"rebind.example.com": ["10.0.0.5"]})
    private_gate, _ = build_gate(env, resolver=rebinding)
    assert denial(private_gate, auth, fetch(20, "https://rebind.example.com/")) == "network_denied"
    assert env.instances.get(auth, inst.id).gated_reason is None  # address_not_public is not owner-resolvable
    assert holds(env, inst) == 1 and len(ex.started) == 1  # only the one allowed request reserved and dispatched


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/work/gate.py:WorkAuthorization")
def test_pause_and_archive_deny_new_work_but_history_stays_visible(build_env):
    env = build_env()
    gate, _ = build_gate(env)
    auth, inst, ops = active(env)
    assert gate.authorize_and_dispatch(auth, req(inst, 1)).outcome == "denied"  # inference not enabled yet
    ops.set_capability(auth, inst.id, 2, "inference", True)
    assert gate.authorize_and_dispatch(auth, req(inst, 2)).outcome == "succeeded"
    paused = ops.set_lifecycle(auth, inst.id, 3, "pause").instance
    assert paused.status == "paused" and denial(gate, auth, req(inst, 3)) == "instance_not_active"
    assert env.instances.get(auth, inst.id).gated_reason is None  # an owner pause is never `gated`
    resumed = ops.set_lifecycle(auth, inst.id, paused.version, "resume").instance
    archived = ops.set_lifecycle(auth, inst.id, resumed.version, "archive").instance
    assert archived.status == "archived" and denial(gate, auth, req(inst, 4)) == "instance_not_active"
    assert env.budget.read_budget(inst.id).windows["compute"]["day"].settled == 5000  # usage history remains
    assert "work.dispatched" in audit_types(env, auth, inst)
