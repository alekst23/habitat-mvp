import json

from jsonschema import Draft202012Validator
import pytest

from aicl.agent_runtime.validation import sanitize_validation_error, wire_validation_error


_CONTROLS = {
    "continue": "ContinueDecision",
    "continue_draft": "ContinueDraftDecision",
    "wait_owner": "WaitOwnerDecision",
    "complete": "CompleteDecision",
    "blocked": "BlockedDecision",
}


def wrapper_schema(*, disabled=()):
    schema = {"type": "object", "properties": {"decision": {"anyOf": []}},
              "required": ["decision"], "additionalProperties": False, "$defs": {}}
    for control, definition in _CONTROLS.items():
        variant = {"type": "object", "properties": {
            "control": {"type": "object", "properties": {"next": {"enum": [control]}},
                        "required": ["next"], "additionalProperties": False},
            "actions": {"type": "array", "items": {"anyOf": [
                {"type": "object", "properties": {
                    "name": {"enum": [name]},
                    "plan_item_id": {"anyOf": [{"type": "string", "pattern": "^[a-z]+$"}, {"type": "null"}]}},
                 "required": ["name", "plan_item_id"], "additionalProperties": False}
                for name in ("artifact.read", "memory.read")]}},
            "output": {"type": "object", "properties": {
                "artifacts": {"type": "array", "items": {"type": "string"}}},
                "required": ["artifacts"], "additionalProperties": False}},
            "required": ["control", "actions", "output"], "additionalProperties": False}
        variant["properties"]["actions"]["minItems" if control == "continue" else "maxItems"] = 1 if control == "continue" else 0
        if control == "continue_draft":
            variant["properties"]["output"]["properties"]["artifacts"]["minItems"] = 1
        schema["$defs"][definition] = variant
        if control not in disabled:
            schema["properties"]["decision"]["anyOf"].append({"$ref": f"#/$defs/{definition}"})
    return schema


def diagnostic(decision, *, disabled=()):
    error = next(Draft202012Validator(wrapper_schema(disabled=disabled)).iter_errors({"decision": decision}))
    return wire_validation_error(error)


@pytest.mark.parametrize(("control", "actions", "artifacts", "path"), [
    ("continue", [], [], "actions"),
    ("complete", [{"name": "artifact.read", "plan_item_id": None}], [], "actions"),
    ("continue_draft", [], [], "output.artifacts"),
])
def test_wrapped_control_constraints_report_the_matching_variant_and_canonical_path(control, actions, artifacts, path):
    result = diagnostic({"control": {"next": control}, "actions": actions, "output": {"artifacts": artifacts}})
    assert result == {"stage": "wire_schema", "code": "out_of_bounds", "path": path}
    assert sanitize_validation_error(result) == result


def test_nested_action_union_keeps_the_matching_tool_after_selecting_a_control_variant():
    result = diagnostic({"control": {"next": "continue"}, "actions": [
        {"name": "memory.read", "plan_item_id": "PRIVATE-CANARY"}], "output": {"artifacts": []}})
    assert result == {"stage": "wire_schema", "code": "invalid_format", "path": "actions[0].plan_item_id"}
    assert "PRIVATE-CANARY" not in json.dumps(result)


@pytest.mark.parametrize("value", ["continue_draft", "PRIVATE-CANARY", {"PRIVATE-CANARY": True}])
def test_disabled_or_unknown_control_feedback_does_not_echo_submitted_control(value):
    result = diagnostic({"control": {"next": value}, "actions": [], "output": {"artifacts": []}},
                        disabled=("continue_draft",))
    assert result == {"stage": "wire_schema", "code": "invalid_value", "path": "control.next"}
    assert "PRIVATE-CANARY" not in json.dumps(result)


def test_unknown_wrapped_properties_stop_at_the_known_parent_without_echoing_keys():
    result = diagnostic({"control": {"next": "complete"}, "actions": [], "output": {
        "artifacts": [], "PRIVATE-CANARY": "PRIVATE-CANARY"}})
    assert result == {"stage": "wire_schema", "code": "unknown_fields", "path": "output"}


def test_persisted_validation_paths_must_remain_canonical_without_provider_wrapper():
    assert sanitize_validation_error({"stage": "wire_schema", "code": "out_of_bounds", "path": "decision.actions"}) is None


def test_wrapper_normalization_does_not_treat_a_tool_argument_named_decision_as_a_contract_path():
    schema = {"type": "object", "properties": {"decision": {"type": "string"}}}
    error = next(Draft202012Validator(schema).iter_errors({"decision": False}))
    result = wire_validation_error(error, stage="tool_arguments", prefix=("actions", 0, "arguments"))
    assert result == {"stage": "tool_arguments", "code": "invalid_type", "path": "actions[0].arguments"}
