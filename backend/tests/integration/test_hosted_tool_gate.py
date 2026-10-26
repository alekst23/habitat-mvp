"""The shared estimate extension preserves old work identities without replay gaps."""
from dataclasses import replace
import hashlib
import json

import pytest

from aicl.control.budget import Estimate
from aicl.control.errors import AiclError
from aicl.work.gate import request_digest
from test_work_gate import active, build_gate, req


def test_legacy_work_digest_stays_stable_but_new_call_counts_cannot_replay(build_env):
    env = build_env()
    auth, inst, _ = active(env, caps=("inference",))
    gate, _ = build_gate(env)
    original = req(inst, 101, estimate=Estimate(1, 2, 0))
    legacy_payload = {"instance_id": inst.id, "capability": original.capability,
                      "payload": original.payload, "destination_url": original.destination_url,
                      "estimate": {"inference_input_tokens": 1, "inference_output_tokens": 2, "compute_minutes": 0}}
    legacy_digest = hashlib.sha256(json.dumps(legacy_payload, sort_keys=True, separators=(",", ":"),
                                              ensure_ascii=False).encode()).hexdigest()
    assert request_digest(original) == legacy_digest
    result = gate.authorize_and_dispatch(auth, original)
    assert result.outcome == "succeeded"
    assert gate.authorize_and_dispatch(auth, original) == result
    for count in (1, False, 0.0):
        changed = original.model_copy(update={"estimate": replace(original.estimate, web_search_calls=count)})
        with pytest.raises(AiclError) as conflict:
            gate.authorize_and_dispatch(auth, changed)
        assert conflict.value.error == "conflict"


def test_legacy_work_gate_validates_the_full_estimate_before_budget_or_dispatch(build_env):
    env = build_env()
    auth, inst, _ = active(env, caps=("inference",))
    gate, executor = build_gate(env)
    for index, count in enumerate((-1, False, 0.0, 10**12 + 1), start=201):
        result = gate.authorize_and_dispatch(auth, req(inst, index, estimate=Estimate(1, 2, 0, count)))
        assert result.outcome == "denied" and result.denial_reason == "estimate_missing"
    assert executor.started == frozenset()
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM budget_hold").fetchone()[0] == 0
