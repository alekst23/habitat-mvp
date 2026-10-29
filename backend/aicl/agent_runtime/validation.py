"""Small, non-sensitive diagnostics for rejected decision envelopes.

These codes describe validation only. They contain no model text, submitted
values, arbitrary property names, exception strings, or new authority.
"""
from __future__ import annotations

import re


_STAGES = frozenset({"wire_schema", "tool_arguments", "decision_contract"})
_CODES = frozenset({
    "invalid_json", "invalid_response_shape", "invalid_type", "invalid_format", "invalid_value",
    "required_field", "unknown_fields", "out_of_bounds", "invalid_variant", "invalid_arguments",
    "invalid_decision", "actions_required", "artifacts_required", "actions_not_allowed",
    "observation_evidence_required", "memory_text_required", "memory_remove_conflict", "duplicate_values",
    "invalid_plan_patch", "artifact_too_large", "envelope_too_large",
})
_CHILDREN = {
    "": {"schema_version", "output", "memory_updates", "plan_patch", "actions", "control"},
    "output": {"message", "artifacts"},
    "output.artifacts[]": {"local_ref", "content", "evidence_refs"},
    "memory_updates[]": {"op", "key", "kind", "text", "evidence_refs"},
    "plan_patch": {"upsert", "remove"},
    "plan_patch.upsert[]": {"id", "title", "requirement_ids", "criteria", "dependency_ids", "state",
                           "evidence_refs", "summary"},
    "actions[]": {"name", "arguments", "plan_item_id"},
    "control": {"next", "requirement_ids", "reason", "question", "options", "artifact_refs",
                "criterion_assessments", "partial_artifact_refs"},
    "control.criterion_assessments[]": {"requirement_id", "status", "explanation", "evidence_refs"},
}
_ARRAYS = frozenset({
    "output.artifacts", "output.artifacts[].evidence_refs", "memory_updates", "memory_updates[].evidence_refs",
    "plan_patch.upsert", "plan_patch.remove", "plan_patch.upsert[].requirement_ids", "plan_patch.upsert[].criteria",
    "plan_patch.upsert[].dependency_ids", "plan_patch.upsert[].evidence_refs", "actions", "control.requirement_ids",
    "control.options", "control.artifact_refs", "control.criterion_assessments",
    "control.criterion_assessments[].evidence_refs", "control.partial_artifact_refs",
})
_CONTROL_BRANCHES = frozenset({"continue", "continue_draft", "wait_owner", "blocked", "complete"})
_DECISION_BRANCH_REFS = {
    "continue": "#/$defs/ContinueDecision",
    "continue_draft": "#/$defs/ContinueDraftDecision",
    "wait_owner": "#/$defs/WaitOwnerDecision",
    "complete": "#/$defs/CompleteDecision",
    "blocked": "#/$defs/BlockedDecision",
}


def _safe_path(location) -> str:
    """Stop at unknown fields, including dynamic tool arguments and union tags."""
    path = shape = ""
    for part in location:
        if shape == "control" and type(part) is str and part in _CONTROL_BRANCHES:
            continue
        if type(part) is int and 0 <= part < 10000 and shape in _ARRAYS:
            path += f"[{part}]"
            shape += "[]"
        elif type(part) is str and part in _CHILDREN.get(shape, ()):
            path += ("." if path else "") + part
            shape += ("." if shape else "") + part
        else:
            break
    return path or "$"


def sanitize_validation_error(value) -> dict | None:
    """Revalidate diagnostics read from persisted adapter or checkpoint data."""
    if (type(value) is not dict or set(value) != {"stage", "code", "path"}
            or type(value["stage"]) is not str or value["stage"] not in _STAGES
            or type(value["code"]) is not str or value["code"] not in _CODES
            or type(value["path"]) is not str or len(value["path"]) > 240):
        return None
    path = value["path"]
    if path != "$":
        if not re.fullmatch(r"[a-z_]+(?:\[[0-9]{1,4}\]|\.[a-z_]+)*", path):
            return None
        parts = [int(index) if index else name for name, index in
                 re.findall(r"([a-z_]+)|\[([0-9]+)\]", path)]
        if _safe_path(parts) != path:
            return None
    return dict(value)


def wire_validation_error(error, *, stage="wire_schema", prefix=()) -> dict:
    # anyOf wraps useful leaf errors. Select only an unambiguous declared
    # branch (especially the action's registered name), never an unrelated
    # tool's enum failure. Submitted values are used for selection, not output.
    for _ in range(16):
        branches = error.schema.get(error.validator) if error.validator in {"anyOf", "oneOf"} else None
        if type(branches) is not list or not error.context:
            break
        indexes = []
        # The provider-only wrapper discriminates full decision envelopes by
        # fixed refs. Never choose the first control variant merely because
        # all variants have object type, or expose a submitted control value.
        decision_variants = all(type(branch) is dict and set(branch) == {"$ref"}
                                and branch["$ref"] in _DECISION_BRANCH_REFS.values()
                                for branch in branches)
        control = error.instance.get("control") if type(error.instance) is dict else None
        if decision_variants and type(control) is dict and "next" in control:
            selected = _DECISION_BRANCH_REFS.get(control["next"]) if type(control["next"]) is str else None
            indexes = [index for index, branch in enumerate(branches) if branch["$ref"] == selected]
            if not indexes:
                location = (*prefix, *error.absolute_path, "control", "next")
                if stage == "wire_schema" and not prefix and location[:1] == ("decision",):
                    location = location[1:]
                result = {"stage": stage, "code": "invalid_value", "path": _safe_path(location)}
                return sanitize_validation_error(result) or {"stage": "wire_schema", "code": "invalid_value", "path": "$"}
        elif len(branches) == 1:
            indexes = [0]
        elif type(error.instance) is dict and type(error.instance.get("name")) is str:
            indexes = [index for index, branch in enumerate(branches) if type(branch) is dict
                       and branch.get("properties", {}).get("name", {}).get("enum") == [error.instance["name"]]]
        if not indexes:
            json_type = {str: "string", int: "integer", float: "number", bool: "boolean",
                         dict: "object", list: "array", type(None): "null"}.get(type(error.instance))
            indexes = [index for index, branch in enumerate(branches) if type(branch) is dict
                       and branch.get("type") == json_type]
        if len(indexes) != 1:
            break
        nested = [item for item in error.context if item.schema_path and item.schema_path[0] == indexes[0]]
        if not nested:
            break
        error = nested[0]
    codes = {"required": "required_field", "type": "invalid_type", "anyOf": "invalid_variant",
             "oneOf": "invalid_variant", "enum": "invalid_value", "const": "invalid_value",
             "pattern": "invalid_format", "additionalProperties": "unknown_fields"}
    bounds = {"minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength"}
    validator = error.validator
    code = "out_of_bounds" if validator in bounds else codes.get(validator, "invalid_value")
    location = (*prefix, *error.absolute_path)
    if stage == "wire_schema" and not prefix and location[:1] == ("decision",):
        location = location[1:]
    result = {"stage": stage, "code": code, "path": _safe_path(location)}
    return sanitize_validation_error(result) or {"stage": "wire_schema", "code": "invalid_value", "path": "$"}


def contract_validation_error(error) -> dict:
    """Map known contract errors to fixed codes; never return exception text."""
    semantic = {
        "continue requires actions": "actions_required",
        "continue_draft requires an artifact write": "artifacts_required",
        "only continue can contain tool actions": "actions_not_allowed",
        "observations require evidence references": "observation_evidence_required",
        "upsert requires text": "memory_text_required",
        "removal cannot also write text or evidence": "memory_remove_conflict",
        "duplicate values are not allowed": "duplicate_values",
        "cannot upsert and remove the same plan item": "invalid_plan_patch",
        "plan patch contains a dependency cycle": "invalid_plan_patch",
        "plan item depends on a removed item": "invalid_plan_patch",
        "a plan item cannot depend on itself": "invalid_plan_patch",
        "an action cannot target a removed plan item": "invalid_plan_patch",
        "artifact content exceeds byte limit": "artifact_too_large",
        "decision envelope exceeds byte limit": "envelope_too_large",
    }
    try:
        entry = error.errors(include_input=False, include_context=False, include_url=False)[0]
    except (AttributeError, IndexError, TypeError):
        return {"stage": "decision_contract", "code": "invalid_decision", "path": "$"}
    kind = entry.get("type")
    if kind == "value_error":
        code = semantic.get(entry.get("msg", "").removeprefix("Value error, "), "invalid_decision")
    elif kind == "missing":
        code = "required_field"
    elif kind == "extra_forbidden":
        code = "unknown_fields"
    elif kind == "string_pattern_mismatch":
        code = "invalid_format"
    elif kind in {"too_short", "too_long", "string_too_short", "string_too_long", "greater_than_equal", "less_than_equal"}:
        code = "out_of_bounds"
    elif kind in {"int_type", "string_type", "list_type", "dict_type", "model_type", "bool_type"}:
        code = "invalid_type"
    elif kind in {"union_tag_invalid", "union_tag_not_found"}:
        code = "invalid_variant"
    else:
        code = "invalid_value"
    return {"stage": "decision_contract", "code": code, "path": _safe_path(entry.get("loc", ()))}
