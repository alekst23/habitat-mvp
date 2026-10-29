"""Decision contracts reject ambiguous replay and impossible continuations offline."""

import copy
import json

import pytest
from pydantic import ValidationError

from aicl.agent_runtime.contracts import (
    MAX_ENVELOPE_BYTES, DecisionEnvelope, RunDefinition, RuntimeLimits,
    canonical_json, digest, parse_envelope,
)


def decision():
    return {
        "schema_version": 1,
        "output": {"message": "Comparing saved findings.", "artifacts": [
            {"local_ref": "draft", "content": "A provisional comparison.",
             "evidence_refs": ["source-1"]}]},
        "memory_updates": [{"op": "upsert", "key": "finding", "kind": "observation",
                            "text": "The source names two options.", "evidence_refs": ["source-1"]}],
        "plan_patch": {"upsert": [{"id": "compare", "title": "Compare options",
            "requirement_ids": ["answer"], "criteria": ["Explain the differences"],
            "dependency_ids": [], "state": "active", "evidence_refs": ["source-1"],
            "summary": None}], "remove": []},
        "actions": [{"name": "page_read", "arguments": {"url": "https://example.org/a"},
                     "plan_item_id": "compare"}],
        "control": {"next": "continue"},
    }


def test_combined_decision_round_trips_with_stable_replay_digest():
    payload = decision()
    parsed = parse_envelope(payload)
    assert parsed.output.artifacts[0].local_ref == "draft"
    assert parsed.memory_updates[0].kind == "observation"
    assert parsed.actions[0].plan_item_id == "compare"
    assert parse_envelope(canonical_json(parsed)) == parsed
    assert digest(parsed) == digest(parsed.model_dump(mode="json"))
    assert digest({"b": 2, "a": "é"}) == digest({"a": "é", "b": 2})
    assert digest(payload) != digest({**payload, "output": {"message": None, "artifacts": []}})


@pytest.mark.parametrize("control", [
    {"next": "continue_draft", "requirement_ids": ["answer"], "reason": "Finish the second section."},
    {"next": "wait_owner", "question": "Which option matters most?", "options": ["Cost", "Durability"]},
    {"next": "complete", "artifact_refs": ["draft"], "criterion_assessments": [
        {"requirement_id": "answer", "status": "met", "explanation": "The comparison is saved.",
         "evidence_refs": ["source-1"]}]},
    {"next": "blocked", "reason": "Source unavailable.", "partial_artifact_refs": ["draft"]},
])
def test_tool_free_outcomes_preserve_output_and_memory(control):
    payload = decision()
    payload.update(actions=[], control=control)
    assert parse_envelope(payload).control.next == control["next"]


def test_control_guards_prevent_dummy_continuations_and_premature_finalization():
    payloads = []
    empty_continue = decision()
    empty_continue["actions"] = []
    payloads.append(empty_continue)
    for control in [
        {"next": "wait_owner", "question": "Continue?", "options": []},
        {"next": "blocked", "reason": "Blocked", "partial_artifact_refs": []},
        {"next": "continue_draft", "requirement_ids": ["answer"], "reason": "More writing"},
        {"next": "complete", "artifact_refs": ["draft"], "criterion_assessments": [
            {"requirement_id": "answer", "status": "met", "explanation": "Done", "evidence_refs": []}]},
    ]:
        candidate = decision()
        candidate["control"] = control
        payloads.append(candidate)
    draft_without_progress = decision()
    draft_without_progress.update(actions=[], control={"next": "continue_draft",
        "requirement_ids": ["answer"], "reason": "More writing"})
    draft_without_progress["output"]["artifacts"] = []
    payloads.append(draft_without_progress)
    for payload in payloads:
        with pytest.raises(ValueError):
            parse_envelope(payload)


def test_duplicate_targets_and_conflicting_plan_patches_are_not_replayable():
    payloads = []
    for collection in ("artifacts", "memory_updates", "actions", "upsert"):
        payload = decision()
        target = (payload["output"][collection] if collection == "artifacts" else
                  payload["plan_patch"][collection] if collection == "upsert" else payload[collection])
        target.append(copy.deepcopy(target[0]))
        payloads.append(payload)
    conflict = decision()
    conflict["plan_patch"]["remove"] = ["compare"]
    payloads.append(conflict)
    cycle = decision()
    first = cycle["plan_patch"]["upsert"][0]
    first["dependency_ids"] = ["review"]
    cycle["plan_patch"]["upsert"].append({**first, "id": "review", "dependency_ids": ["compare"]})
    payloads.append(cycle)
    for payload in payloads:
        with pytest.raises(ValueError):
            parse_envelope(payload)
    # Existing plan dependencies are resolved against saved state by the runtime.
    existing = decision()
    existing["plan_patch"]["upsert"][0]["dependency_ids"] = ["earlier-plan-item"]
    assert parse_envelope(existing).plan_patch.upsert[0].dependency_ids == ["earlier-plan-item"]


def test_memory_requires_evidence_and_cannot_mutate_authority():
    for mutation in ({"evidence_refs": []}, {"text": None}, {"op": "remove"},
                     {"allowed_tools": ["publish"]}):
        payload = decision()
        payload["memory_updates"][0].update(mutation)
        with pytest.raises(ValueError):
            parse_envelope(payload)
    payload = decision()
    payload["memory_updates"] = [{"op": "remove", "key": "finding", "kind": "observation",
                                  "text": None, "evidence_refs": []}]
    assert parse_envelope(payload).memory_updates[0].op == "remove"
    payload["memory_updates"] = [{"op": "upsert", "key": "hypothesis", "kind": "assumption",
                                  "text": "This might be useful.", "evidence_refs": []}]
    assert parse_envelope(payload).memory_updates[0].kind == "assumption"


def test_json_boundary_rejects_coercion_non_json_and_ambiguous_objects():
    for value in (True, "1", 2):
        with pytest.raises(ValueError):
            parse_envelope({**decision(), "schema_version": value})
    for arguments in ({"cost": float("nan")}, {"tuple": (1, 2)}, {1: "non-string key"}):
        payload = decision()
        payload["actions"][0]["arguments"] = arguments
        with pytest.raises(ValueError):
            parse_envelope(payload)
    with pytest.raises(ValueError):
        parse_envelope(json.dumps(decision()).replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'))
    with pytest.raises(ValueError):
        parse_envelope({**decision(), "tenant_id": "forged"})
    with pytest.raises(ValueError):
        parse_envelope("[]")


def test_payload_caps_apply_to_dicts_json_and_direct_model_validation():
    too_large = decision()
    too_large["output"]["artifacts"] = [{"local_ref": f"part-{i}", "content": "x" * 20000,
                                         "evidence_refs": []} for i in range(8)]
    assert len(json.dumps(too_large).encode()) > MAX_ENVELOPE_BYTES
    for parse in (parse_envelope, DecisionEnvelope.model_validate):
        with pytest.raises(ValueError):
            parse(too_large)
    with pytest.raises(ValueError):
        parse_envelope(" " * MAX_ENVELOPE_BYTES + json.dumps(decision()))
    multibyte = decision()
    multibyte["output"]["artifacts"][0]["content"] = "😀" * 10000
    with pytest.raises(ValueError):
        parse_envelope(multibyte)


def test_owner_definition_and_runtime_limits_remain_strict_separate_contracts():
    definition = {"objective": "Compare alternatives", "requirements": [{"id": "answer", "text": "Explain tradeoffs"}],
                  "allowed_tools": ["page_read"]}
    assert RunDefinition.model_validate(definition).requirements[0].id == "answer"
    for changes in ({"requirements": definition["requirements"] * 2},
                    {"allowed_tools": ["page_read", "page_read"]}):
        with pytest.raises(ValueError):
            RunDefinition.model_validate({**definition, **changes})
    limits = RuntimeLimits()
    assert (limits.max_decisions, limits.max_actions, limits.max_draft_continuations,
            limits.max_invalid_decisions, limits.max_context_chars, limits.max_run_cost_micro_usd) == (
                20, 50, 3, 1, 24000, 1000000)
    for changes in ({"max_decisions": "20"}, {"max_actions": -1}, {"max_run_cost_micro_usd": True},
                    {"max_run_cost_micro_usd": 0}):
        with pytest.raises(ValidationError):
            RuntimeLimits(**changes)
