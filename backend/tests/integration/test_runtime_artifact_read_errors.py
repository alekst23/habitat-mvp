"""Unsupported local evidence selections are known empty results, not paid unknowns."""
import json
from dataclasses import asdict

import pytest

from aicl.agent_runtime.contracts import canonical_json
from aicl.agent_runtime.openai_model import OpenAIDecisionModel
from test_agent_runtime_session import envelope
from test_runtime_research_prelude import rows, setup


def test_search_text_mismatch_returns_observation_and_model_can_correct_without_more_research(build_env):
    def read_search_as_page(context):
        return envelope(actions=[{"name": "artifact.read", "arguments": {
            "ref": context["public_research"]["evidence_ref"], "source_index": 0,
            "field": "text", "public_preview": True, "offset": 0, "max_chars": 4000}}])

    def correct_selection(context):
        result = next(item["result"] for item in context["observations"] if item["tool"] == "artifact.read")
        assert result["error"] == "public_page_text_required"
        assert result["text"] == "" and result["next_offset"] is None and result["total_chars"] == 0
        assert "omit field" in result["message"]
        return envelope(actions=[{"name": "artifact.read", "arguments": {
            "ref": result["ref"], "source_index": result["source_index"], "public_preview": True}}])

    def finish(context):
        saved = next(item for item in context["observations"]
                     if item["tool"] == "artifact.read" and item["result"]["error"] is None)
        evidence = json.loads(saved["result"]["text"])
        assert evidence["source_kind"] == "public_search" and evidence["sources"]
        return envelope(artifacts=[{"local_ref": "report", "content": "Saved public search evidence reviewed.",
                                    "evidence_refs": [saved["ref"]]}],
            control={"next": "complete", "artifact_refs": ["report"], "criterion_assessments": [{
                "requirement_id": "report", "status": "met", "explanation": "Reviewed the saved public search evidence.",
                "evidence_refs": [saved["ref"]]}]})

    env, auth, _, runtime, model, _, run, outbound, _, _ = setup(
        build_env, sources=(), responses=[read_search_as_page, correct_selection, finish])
    model.validate_context = OpenAIDecisionModel("offline-context-fixture", tool_specs=runtime.tools.specs()).validate_context
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "completed" and result["reason"] is None
    assert len(model.calls) == 3 and len(outbound) == 1
    steps = rows(env, "agent_step")
    assert [step["tool_name"] for step in steps] == [
        "public.research", "model", "artifact.read", "model", "artifact.read", "model"]
    assert all(step["state"] == "applied" for step in steps)
    assert all(hold["state"] == "settled" for hold in rows(env, "budget_hold"))
    assert sum(usage["inference_micro_usd"] for usage in rows(env, "budget_usage")) == 5000
    for step in steps:
        if step["tool_name"] == "artifact.read":
            assert set(json.loads(step["usage_json"]).values()) == {0}


@pytest.mark.parametrize("source,arguments,code", [
    ({"source_kind": "public_search", "instruction_authority": "untrusted_evidence", "sources": []},
     {"field": "text"}, "public_page_text_required"),
    ({"source_kind": "public_page", "instruction_authority": "untrusted_evidence"},
     {"field": "text"}, "public_page_text_required"),
    ({"source_kind": "public_page", "instruction_authority": "untrusted_evidence", "text": {"private": "malformed"}},
     {"field": "text"}, "public_page_text_required"),
    ({"source_kind": "public_page", "instruction_authority": "untrusted_evidence", "text": "not available", "unavailable": True},
     {"field": "text"}, "public_page_text_required"),
    ({"source_kind": "unsupported", "text": "DO-NOT-ECHO-SOURCE"}, {}, "public_preview_unavailable"),
    ({"error": None, "evidence": []}, {"source_index": 0}, "research_source_not_found"),
])
def test_unsupported_public_selections_have_only_fixed_bounded_zero_usage_feedback(build_env, source, arguments, code):
    env, auth, _, runtime, _, _, run, outbound, _, _ = setup(build_env, sources=())
    with env.db.transaction() as conn:
        ref = runtime.repo.put_content(conn, auth, run["id"], "public_research_source", source)
    reader = runtime.tools.get("artifact.read")
    result = reader.execute_scoped({"ref": ref, "public_preview": True, **arguments}, "known-local-rejection", auth, run["id"])
    assert result.payload["error"] == code
    assert result.payload["ref"] == ref and result.payload["text"] == ""
    assert result.payload["next_offset"] is None and result.payload["total_chars"] == 0
    assert set(result.payload) <= {"error", "message", "ref", "source_index", "text", "next_offset", "total_chars"}
    assert "DO-NOT-ECHO-SOURCE" not in canonical_json(result.payload) and "malformed" not in canonical_json(result.payload)
    assert len(canonical_json(result.payload)) < 600 and set(asdict(result.usage).values()) == {0}
    assert result.response_id is None and result.model is None and not result.bounds_exceeded
    with env.db.reader() as conn:
        assert runtime.repo.get_content(conn, auth, run["id"], ref) == source
    assert outbound == [] and rows(env, "agent_step") == []
