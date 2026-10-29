"""Versioned decision shapes. Cross-record authorization belongs to the runtime."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_ENVELOPE_BYTES = 128 * 1024
MAX_ARTIFACT_BYTES = 32 * 1024
MAX_ARGUMENT_BYTES = 16 * 1024
MAX_ACTIONS_PER_DECISION = 8
MAX_JSON_DEPTH = 32


def _distinct(values: list) -> list:
    if len(set(values)) != len(values):
        raise ValueError("duplicate values are not allowed")
    return values


Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Reference = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^\S+$")]
NoteText = Annotated[str, Field(min_length=1, max_length=4000, pattern=r"[\s\S]*\S[\s\S]*")]
CriterionText = Annotated[str, Field(min_length=1, max_length=1000, pattern=r"[\s\S]*\S[\s\S]*")]
ReferenceList = Annotated[list[Reference], Field(max_length=64), AfterValidator(_distinct)]
IdentifierList = Annotated[list[Identifier], Field(max_length=64), AfterValidator(_distinct)]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class ArtifactWrite(_Contract):
    local_ref: Identifier
    content: Annotated[str, Field(min_length=1, max_length=MAX_ARTIFACT_BYTES,
                                  pattern=r"[\s\S]*\S[\s\S]*")]
    evidence_refs: ReferenceList = Field(default_factory=list)

    @field_validator("content")
    @classmethod
    def content_byte_bound(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_ARTIFACT_BYTES:
            raise ValueError("artifact content exceeds byte limit")
        return value


class DecisionOutput(_Contract):
    message: NoteText | None = None
    artifacts: list[ArtifactWrite] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def unique_writes(self) -> DecisionOutput:
        _distinct([artifact.local_ref for artifact in self.artifacts])
        return self


class MemoryUpdate(_Contract):
    op: Literal["upsert", "remove"]
    key: Identifier
    kind: Literal["observation", "interpretation", "assumption", "open_question"]
    text: NoteText | None = None
    evidence_refs: ReferenceList = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_mutation(self) -> MemoryUpdate:
        if self.op == "remove":
            if self.text is not None or self.evidence_refs:
                raise ValueError("removal cannot also write text or evidence")
        elif self.text is None:
            raise ValueError("upsert requires text")
        elif self.kind == "observation" and not self.evidence_refs:
            raise ValueError("observations require evidence references")
        return self


class PlanItem(_Contract):
    id: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200, pattern=r"[\s\S]*\S[\s\S]*")]
    requirement_ids: IdentifierList = Field(min_length=1)
    criteria: Annotated[list[CriterionText], Field(min_length=1, max_length=16), AfterValidator(_distinct)]
    dependency_ids: IdentifierList = Field(default_factory=list)
    state: Literal["pending", "active", "completed", "blocked", "failed", "superseded"]
    evidence_refs: ReferenceList = Field(default_factory=list)
    summary: NoteText | None = None

    @model_validator(mode="after")
    def no_self_dependency(self) -> PlanItem:
        if self.id in self.dependency_ids:
            raise ValueError("a plan item cannot depend on itself")
        return self


class PlanPatch(_Contract):
    upsert: list[PlanItem] = Field(default_factory=list, max_length=64)
    remove: IdentifierList = Field(default_factory=list)

    @model_validator(mode="after")
    def coherent_patch(self) -> PlanPatch:
        _distinct([item.id for item in self.upsert])
        items = {item.id: item for item in self.upsert}
        removed = set(self.remove)
        if removed.intersection(items):
            raise ValueError("cannot upsert and remove the same plan item")
        visited, active = set(), set()

        def visit(item_id: str) -> None:
            if item_id in active:
                raise ValueError("plan patch contains a dependency cycle")
            if item_id in visited or item_id not in items:
                return  # Existing-plan dependencies are checked by the runtime.
            active.add(item_id)
            for dependency in items[item_id].dependency_ids:
                if dependency in removed:
                    raise ValueError("plan item depends on a removed item")
                visit(dependency)
            active.remove(item_id)
            visited.add(item_id)

        for item_id in items:
            visit(item_id)
        return self


class ToolAction(_Contract):
    name: Identifier
    arguments: dict[str, Any]
    plan_item_id: Identifier | None = None

    @field_validator("arguments", mode="before")
    @classmethod
    def bounded_json_arguments(cls, value: Any) -> Any:
        if type(value) is not dict or len(canonical_json(value).encode("utf-8")) > MAX_ARGUMENT_BYTES:
            raise ValueError("tool arguments must be a bounded JSON object")
        return value


class CriterionAssessment(_Contract):
    requirement_id: Identifier
    status: Literal["met", "unmet"]
    explanation: NoteText
    evidence_refs: ReferenceList = Field(default_factory=list)


class ContinueControl(_Contract):
    next: Literal["continue"]


class ContinueDraftControl(_Contract):
    next: Literal["continue_draft"]
    requirement_ids: IdentifierList = Field(min_length=1)
    reason: NoteText


class WaitOwnerControl(_Contract):
    next: Literal["wait_owner"]
    question: NoteText
    options: Annotated[list[CriterionText], Field(max_length=8), AfterValidator(_distinct)] = Field(default_factory=list)


class CompleteControl(_Contract):
    next: Literal["complete"]
    artifact_refs: ReferenceList = Field(min_length=1)
    criterion_assessments: list[CriterionAssessment] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_assessments(self) -> CompleteControl:
        _distinct([assessment.requirement_id for assessment in self.criterion_assessments])
        return self


class BlockedControl(_Contract):
    next: Literal["blocked"]
    reason: NoteText
    partial_artifact_refs: ReferenceList = Field(default_factory=list)


Control = Annotated[ContinueControl | ContinueDraftControl | WaitOwnerControl | CompleteControl | BlockedControl,
                    Field(discriminator="next")]


class DecisionEnvelope(_Contract):
    schema_version: Literal[1]
    output: DecisionOutput = Field(default_factory=DecisionOutput)
    memory_updates: list[MemoryUpdate] = Field(default_factory=list, max_length=32)
    plan_patch: PlanPatch | None = None
    actions: list[ToolAction] = Field(default_factory=list, max_length=MAX_ACTIONS_PER_DECISION)
    control: Control

    @model_validator(mode="before")
    @classmethod
    def bounded_json_envelope(cls, value: Any) -> Any:
        if len(canonical_json(value).encode("utf-8")) > MAX_ENVELOPE_BYTES:
            raise ValueError("decision envelope exceeds byte limit")
        return value

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value

    @model_validator(mode="after")
    def coherent_decision(self) -> DecisionEnvelope:
        # Defaults are persisted too; accepted envelopes must fit on replay.
        if len(canonical_json(self).encode("utf-8")) > MAX_ENVELOPE_BYTES:
            raise ValueError("decision envelope exceeds byte limit")
        _distinct([update.key for update in self.memory_updates])
        _distinct([canonical_json({"name": action.name, "arguments": action.arguments})
                   for action in self.actions])
        if self.control.next == "continue":
            if not self.actions:
                raise ValueError("continue requires actions")
        elif self.actions:
            raise ValueError("only continue can contain tool actions")
        if self.control.next == "continue_draft" and not self.output.artifacts:
            raise ValueError("continue_draft requires an artifact write")
        if self.plan_patch and any(action.plan_item_id in self.plan_patch.remove for action in self.actions):
            raise ValueError("an action cannot target a removed plan item")
        return self


class Requirement(_Contract):
    id: Identifier
    text: NoteText


class RunDefinition(_Contract):
    objective: Annotated[str, Field(min_length=1, max_length=12000, pattern=r"[\s\S]*\S[\s\S]*")]
    requirements: list[Requirement] = Field(min_length=1, max_length=32)
    allowed_tools: IdentifierList = Field(default_factory=list)
    # Only publication may bind this immutable owner-approved disclosure. It is
    # never a model action or an editable conversation field.
    public_research_release_id: Identifier | None = None

    @model_validator(mode="after")
    def unique_requirements(self) -> RunDefinition:
        _distinct([requirement.id for requirement in self.requirements])
        return self


class RuntimeLimits(_Contract):
    max_decisions: int = Field(default=20, ge=1, le=1000)
    max_actions: int = Field(default=50, ge=0, le=10000)
    max_draft_continuations: int = Field(default=3, ge=0, le=100)
    max_invalid_decisions: int = Field(default=1, ge=0, le=10)
    max_context_chars: int = Field(default=24000, ge=1, le=1000000)
    max_run_cost_micro_usd: int = Field(default=1000000, ge=1, le=10**12)


def canonical_json(value: Any) -> str:
    """Stable UTF-8 JSON for local identity, without Python-to-JSON coercions."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")

    def check(item: Any, depth: int = 0) -> None:
        if depth > MAX_JSON_DEPTH:
            raise ValueError("JSON nesting exceeds limit")
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                check(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child, depth + 1)
            return
        raise ValueError("value is not finite JSON data")

    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_envelope(payload: dict | str) -> DecisionEnvelope:
    """Parse one complete response; never accept a partial or ambiguous object.

    The coordinator still validates references, owner requirements, plan changes
    against existing state, draft progress, registry eligibility and authority.
    """
    if isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_ENVELOPE_BYTES:
            raise ValueError("decision envelope exceeds byte limit")

        def unique_object(pairs: list[tuple[str, Any]]) -> dict:
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON object key")
                result[key] = value
            return result

        def reject_constant(_: str) -> None:
            raise ValueError("nonfinite JSON value")

        try:
            payload = json.loads(payload, object_pairs_hook=unique_object, parse_constant=reject_constant)
        except RecursionError as error:
            raise ValueError("JSON nesting exceeds limit") from error
    if type(payload) is not dict:
        raise ValueError("decision envelope must be a JSON object")
    return DecisionEnvelope.model_validate(payload)
