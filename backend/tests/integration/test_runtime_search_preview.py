"""Search discovery candidates cannot poison later bounded evidence views."""
from copy import deepcopy
import json

import httpx
import pytest

from aicl.agent_runtime.contracts import RunDefinition, canonical_json
from aicl.agent_runtime.openai_model import OpenAIDecisionModel
from aicl.control.errors import AiclError
from aicl.workflow.openai_inference import InferenceNoChargeError
from test_agent_runtime_session import envelope
from test_runtime_research_prelude import rows, setup


@pytest.mark.parametrize("include_safe", [True, False])
def test_search_candidates_are_omitted_from_scoped_views_without_changing_receipts(build_env, include_safe):
    marker = "sk-" + "c" * 40
    safe_url = "https://news.example/article?section=ai"
    results = [
        {"url": "https://news.example/" + marker, "title": "Unsafe URL", "description": "Public snippet"},
        {"url": "https://news.example/title", "title": marker, "description": "Public snippet"},
        {"url": "https://news.example/snippet", "title": "Unsafe snippet", "description": marker},
    ]
    if include_safe:
        results.append({"url": safe_url, "title": "Exact public title", "description": "Exact public snippet"})

    def search(request):
        assert request.url.host == "api.search.brave.com"
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=httpx.ByteStream(
            json.dumps({"web": {"results": results}}).encode()))

    env, auth, inst, runtime, model, _, run, outbound, _, _ = setup(build_env, sources=(), handler=search)
    validator = OpenAIDecisionModel("offline-private-credential", tool_specs=runtime.tools.specs())
    model.validate_context = validator.validate_context
    runtime.advance_slice(auth, run["id"], max_operations=1)
    step = rows(env, "agent_step")[0]
    with env.db.reader() as conn:
        original = runtime.repo.get_content(conn, auth, run["id"], step["output_ref"])
    assert marker in canonical_json(original)
    assert runtime.advance_slice(auth, run["id"])["status"] == "waiting_owner"
    assert len(model.calls) == len(outbound) == 1
    context = model.calls[0]
    assert marker not in canonical_json(context)
    validator.validate_context(context)
    source = json.loads(context["observations"][0]["text"])["evidence"][0]
    assert source["source_kind"] == "public_search" and source["sources_omitted_for_disclosure"] == 3
    assert [candidate["url"] for candidate in source["sources"]] == ([safe_url] if include_safe else [])
    if include_safe:
        assert source["sources"][0]["title"] == "Exact public title"
        assert source["sources"][0]["text"] == "Exact public snippet"
        assert source["sources"][0]["authorized_to_fetch"] is False

    reader = runtime.tools.get("artifact.read")
    args = source["retrieval"]["arguments"]
    preview = reader.execute_scoped(args, "saved-search-preview", auth, run["id"]).payload
    expected = deepcopy(original["evidence"][0])
    expected["sources"] = expected["sources"][3:]
    expected["sources_omitted_for_disclosure"] = 3
    assert preview["projection"] == "public_evidence_preview"
    assert preview["text"] == canonical_json(expected)
    chunks = []
    for offset in range(0, preview["total_chars"], 80):
        chunk = reader.execute_scoped({**args, "offset": offset, "max_chars": 80}, "chunk", auth, run["id"]).payload
        chunks.append(chunk["text"])
        assert chunk["total_chars"] == len(preview["text"])
        assert chunk["next_offset"] == (offset + 80 if offset + 80 < preview["total_chars"] else None)
    assert "".join(chunks) == preview["text"]
    # Disclosure projection is mandatory for genuine saved public evidence,
    # even when the model omits the hint or explicitly asks for a raw view.
    for selection in ({key: value for key, value in args.items() if key != "public_preview"},
                      {**args, "public_preview": False}):
        mandatory = reader.execute_scoped(selection, "mandatory-preview", auth, run["id"]).payload
        assert mandatory == preview
        validator.validate_context({**context, "observations": [*context["observations"],
                                                               {"tool": "artifact.read", "result": mandatory}]})
    assert preview["reader_version"] == "artifact-v5"
    whole = reader.execute_scoped({"ref": step["output_ref"]}, "whole-receipt", auth, run["id"]).payload
    assert whole["projection"] == "public_evidence_preview" and marker not in whole["text"]
    with env.db.reader() as conn:
        assert runtime.repo.get_content(conn, auth, run["id"], step["output_ref"]) == original
    with env.db.transaction() as conn:
        private_ref = runtime.repo.put_content(conn, auth, run["id"], "artifact", original["evidence"][0])
        public_ref = runtime.repo.put_content(conn, auth, run["id"], "public_research_source", original["evidence"][0])
    direct = reader.execute_scoped({"ref": public_ref}, "direct-source", auth, run["id"]).payload
    assert direct["text"] == canonical_json(expected) and direct["projection"] == "public_evidence_preview"
    private = reader.execute_scoped({"ref": private_ref}, "private", auth, run["id"]).payload
    assert private["text"] == canonical_json(original["evidence"][0]) and "projection" not in private
    with pytest.raises(InferenceNoChargeError, match="sensitive_or_invalid_input"):
        validator.validate_context({**context, "observations": [{"tool": "artifact.read", "result": private}]})
    with env.db.reader() as conn:
        assert reader.public_projection_selection(conn, args, auth, run["id"]) == expected
        assert reader.public_read_projection(conn, args, auth, run["id"]) == preview
        assert reader.public_projection_selection(conn, {"ref": private_ref}, auth, run["id"]) is None
        assert reader.public_read_projection(conn, {"ref": private_ref}, auth, run["id"]) is None
    with pytest.raises(AiclError, match="validation_failed"):
        reader.execute_scoped({"ref": private_ref, "public_preview": True}, "forged", auth, run["id"])
    other = runtime.create_run(auth, inst.id, "other-run", RunDefinition(
        objective="Other task", requirements=[{"id": "r", "text": "Use only its own evidence"}], allowed_tools=[]))
    with pytest.raises(AiclError):
        reader.execute_scoped(args, "cross-run", auth, other["id"])
    assert len(outbound) == 1
    assert [row["state"] for row in rows(env, "budget_hold")] == ["settled", "settled"]


def test_applied_read_wrappers_cannot_reexpose_nested_evidence(build_env):
    def read(context):
        return envelope(actions=[{"name": "artifact.read", "arguments": {
            "ref": context["observations"][0]["ref"], "source_index": 0}}])

    env, auth, _, runtime, _, _, run, outbound, _, _ = setup(build_env, sources=(), responses=[
        read, envelope(control={"next": "wait_owner", "question": "Use these findings?", "options": []})])
    assert runtime.advance_slice(auth, run["id"])["status"] == "waiting_owner"
    step = next(row for row in rows(env, "agent_step") if row["tool_name"] == "artifact.read")
    reader = runtime.tools.get("artifact.read")
    with env.db.reader() as conn:
        saved = runtime.repo.get_content(conn, auth, run["id"], step["output_ref"])
    for hint in ({}, {"public_preview": True}, {"public_preview": False}):
        result = reader.execute_scoped({"ref": step["output_ref"], **hint}, "wrapper", auth, run["id"]).payload
        assert result["error"] == "artifact_read_receipt_unavailable" and result["text"] == ""
        assert result["total_chars"] == 0 and result["next_offset"] is None
    with env.db.reader() as conn:
        assert runtime.repo.get_content(conn, auth, run["id"], step["output_ref"]) == saved
    assert len(outbound) == 1
