"""Legacy raw discovery reads cannot poison a resumed run or change coordinates."""
from copy import deepcopy
import json

import httpx
import pytest

from aicl.agent_runtime.adapters import AdapterResult
from aicl.agent_runtime.contracts import canonical_json
from aicl.agent_runtime.openai_model import OpenAIDecisionModel
from test_agent_runtime_session import envelope
from test_runtime_research_prelude import rows, setup


@pytest.mark.parametrize("body_secret", [None, "sk-" + "x" * 40, "actual-private-provider-credential"])
def test_legacy_public_read_recovery_preserves_safe_coverage_and_body_denials(build_env, body_secret):
    marker = "https://news.example/sk-hynix-news"
    def response(request):
        if request.url.host == "api.search.brave.com":
            data = {"web": {"results": [
                {"url": marker, "title": "Public chip news", "description": "A public headline."},
                {"url": "https://news.example/clean", "title": "Clean source", "description": "Useful finding."}]}}
            return httpx.Response(200, headers={"content-type": "application/json"},
                                  stream=httpx.ByteStream(json.dumps(data).encode()))
        return httpx.Response(200, headers={"content-type": "text/html"},
                              stream=httpx.ByteStream(("<main>Public evidence " + (body_secret or "clean") + "</main>").encode()))

    def first(context):
        ref = context["observations"][0]["ref"]
        return envelope(actions=[
            {"name": "artifact.read", "arguments": {"ref": ref, "source_index": 0, "public_preview": True}},
            {"name": "artifact.read", "arguments": {"ref": ref}}])

    def after_upgrade(context):
        observed = [item["result"] for item in context["observations"] if item["tool"] == "artifact.read"]
        assert observed[1]["error"] == "legacy_public_read_unavailable"
        assert observed[1]["text"] == "" and observed[1]["next_offset"] is None
        assert marker not in canonical_json(context)
        sources = context["read_coverage"]["sources"]
        assert len(sources) == 1 and sources[0]["selector"]["public_preview"] is True
        assert sources[0]["returned_ranges"] == [[0, observed[0]["total_chars"]]]
        # Default/false/true all refer to the same mandatory projected range.
        request = {**sources[0]["selector"], "public_preview": False}
        return envelope(actions=[{"name": "artifact.read", "arguments": request}])

    env, auth, _, runtime, model, _, run, outbound, _, _ = setup(build_env, handler=response,
        responses=[first, after_upgrade, envelope(control={"next": "wait_owner", "question": "Review findings.", "options": []})])
    reader = runtime.tools.get("artifact.read")
    execute = reader.execute_scoped
    reader.version = "artifact-v4"
    def legacy(arguments, invocation_id, owner, run_id):
        if arguments.get("public_preview"):
            value = execute(arguments, invocation_id, owner, run_id).payload
            value.pop("reader_version", None)
            return AdapterResult(value)
        with runtime.db.reader() as conn:
            raw = canonical_json(runtime.repo.get_content(conn, owner, run_id, arguments["ref"]))
        return AdapterResult({"error": None, "ref": arguments["ref"], "text": raw[:4000],
                              "next_offset": 4000 if len(raw) > 4000 else None, "total_chars": len(raw)})
    reader.execute_scoped = legacy
    runtime.advance_slice(auth, run["id"], max_operations=4)
    reads = [step for step in rows(env, "agent_step") if step["tool_name"] == "artifact.read"]
    assert len(reads) == 2 and len(model.calls) == 1
    with env.db.reader() as conn:
        before = {step["output_ref"]: deepcopy(runtime.repo.get_content(conn, auth, run["id"], step["output_ref"])) for step in reads}
    assert marker in before[reads[1]["output_ref"]]["text"]
    reader.version = "artifact-v5"
    reader.execute_scoped = execute
    validator = OpenAIDecisionModel("actual-private-provider-credential", tool_specs=runtime.tools.specs())
    model.validate_context = validator.validate_context
    model.validate_disclosure = validator.validate_disclosure
    result = runtime.advance_slice(auth, run["id"])
    if body_secret:
        assert result["status"] == "blocked" and result["reason"] == "sensitive_or_invalid_input"
        assert len(model.calls) == 1
    else:
        assert result["status"] == "waiting_owner" and len(model.calls) == 3
        assert model.calls[-1]["progress_feedback"]["skipped_read_count"] == 1
    assert len(outbound) == 2  # Original research only; no replay or new disclosure.
    assert len([step for step in rows(env, "agent_step") if step["tool_name"] == "artifact.read"]) == 2
    with env.db.reader() as conn:
        assert {ref: runtime.repo.get_content(conn, auth, run["id"], ref) for ref in before} == before
