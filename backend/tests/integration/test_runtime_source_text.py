"""Saved public page bodies are usable without paging through discovery links."""
import httpx
import pytest

from aicl.agent_runtime.contracts import RunDefinition, canonical_json
from aicl.agent_runtime.openai_model import OpenAIDecisionModel
from aicl.agent_runtime.research_context import public_source_preview, source_overview
from aicl.control.errors import AiclError
from aicl.workflow.openai_inference import InferenceNoChargeError
from test_runtime_research_prelude import rows, setup


TOKEN_LINK = "https://news.example/sk-" + "a" * 40
DATE = [{"value": "2026-10-27", "kind": "published", "source": "meta", "scope": "page"}]


def page_handler(body):
    def page(request):
        links = "".join(f'<a href="https://news.example/{index}-{"long-path-" * 20}">Menu {index}</a>' for index in range(25))
        html = ('<title>Primary report</title><meta property="article:published_time" content="2026-10-27">'
                f'<main><h1>Primary report</h1><p>{body}</p>'
                f'{links}<a href="{TOKEN_LINK}">Unrelated link</a></main>').encode()
        return httpx.Response(200, headers={"content-type": "text/html"}, stream=httpx.ByteStream(html))
    return page


def saved_page(build_env, body):
    env, auth, instance, runtime, _, _, run, outbound, _, _ = setup(
        build_env, queries=(), handler=page_handler(body))
    runtime.advance_slice(auth, run["id"], max_operations=1)
    step = rows(env, "agent_step")[0]
    with env.db.reader() as conn:
        receipt = runtime.repo.get_content(conn, auth, run["id"], step["output_ref"])
    return env, auth, instance, runtime, run, outbound, step, receipt


def test_text_reads_skip_link_lists_preserve_dates_and_continue_after_the_overview(build_env):
    env, auth, _, runtime, run, outbound, step, original = saved_page(
        build_env, "Evidence starts here.\n  Specific finding.\t" + "Additional public detail. " * 300)
    source = original["evidence"][0]
    normalized = " ".join(source["text"].split())
    overview = source_overview([(source, step["output_ref"], 0)], text_chars=61)["evidence"][0]
    args = overview["retrieval"]["arguments"]
    assert args["field"] == "text" and args["public_preview"] is True and args["offset"] == 61
    reader = runtime.tools.get("artifact.read")
    chunk = reader.execute_scoped(args, "body-continuation", auth, run["id"]).payload
    assert chunk["projection"] == "public_page_text"
    assert overview["text"] + chunk["text"] == normalized[:4061]
    assert chunk["offset"] == 61 and chunk["next_offset"] == 4061
    assert chunk["total_chars"] == len(normalized) and chunk["truncated"] is True
    assert chunk["source"] == {"source_kind": "public_page", "url": "https://news.example/article",
        "title": "Primary report", "date_candidates": DATE, "instruction_authority": "untrusted_evidence"}
    assert "links" not in chunk["source"] and TOKEN_LINK not in canonical_json(chunk)

    chunks = []
    for offset in range(0, len(normalized), 399):
        part = reader.execute_scoped({**args, "offset": offset, "max_chars": 399}, "body-page", auth, run["id"]).payload
        chunks.append(part["text"])
        assert part["offset"] == offset
        assert part["next_offset"] == (offset + 399 if offset + 399 < len(normalized) else None)
    assert "".join(chunks) == normalized
    assert part["truncated"] is False and part["source_truncated"] is False
    projected = reader.execute_scoped({"ref": step["output_ref"], "source_index": 0}, "default", auth, run["id"]).payload
    assert projected["text"] == canonical_json(public_source_preview(source))[:4000]
    assert projected["projection"] == "public_evidence_preview" and projected["reader_version"] == "artifact-v5"
    for hint in ({"public_preview": False}, {}):
        same_body = reader.execute_scoped({**{key: value for key, value in args.items() if key != "public_preview"},
                                          **hint}, "body-default", auth, run["id"]).payload
        assert same_body == chunk
    with env.db.reader() as conn:
        assert runtime.repo.get_content(conn, auth, run["id"], step["output_ref"]) == original
    assert len(outbound) == 1 and len(rows(env, "agent_step")) == 1


def test_text_reads_require_public_provenance_and_run_scope(build_env):
    env, auth, instance, runtime, run, outbound, step, original = saved_page(build_env, "Public evidence.")
    reader = runtime.tools.get("artifact.read")
    args = {"ref": step["output_ref"], "source_index": 0, "field": "text", "public_preview": True}
    with env.db.transaction() as conn:
        private_ref = runtime.repo.put_content(conn, auth, run["id"], "artifact", original["evidence"][0])
        public_ref = runtime.repo.put_content(conn, auth, run["id"], "public_research_source", original["evidence"][0])
        search_ref = runtime.repo.put_content(conn, auth, run["id"], "public_research_source",
            {"source_kind": "public_search", "instruction_authority": "untrusted_evidence", "sources": []})
        truncated = {**original["evidence"][0], "truncated": True}
        truncated_ref = runtime.repo.put_content(conn, auth, run["id"], "public_research_source", truncated)
    direct = reader.execute_scoped({"ref": public_ref, "field": "text", "public_preview": True}, "direct", auth, run["id"]).payload
    assert "Public evidence." in direct["text"]
    last = reader.execute_scoped({"ref": truncated_ref, "field": "text", "public_preview": True}, "truncated", auth, run["id"]).payload
    assert last["next_offset"] is None and last["truncated"] is True and last["source_truncated"] is True
    bad_args = [{**args, "field": "links"}, {**args, "field": True},
                *({"ref": private_ref, "field": "text", **hint} for hint in
                  ({"public_preview": True}, {"public_preview": False}, {}))]
    for bad in bad_args:
        with pytest.raises(AiclError):
            reader.execute_scoped(bad, "invalid", auth, run["id"])
    for ref in (search_ref, step["output_ref"]):
        result = reader.execute_scoped({"ref": ref, "field": "text", "public_preview": True},
                                       "unsupported-text", auth, run["id"]).payload
        assert result["error"] == "public_page_text_required" and result["text"] == ""
    other = runtime.create_run(auth, instance.id, "other-body-run", RunDefinition(
        objective="Other task", requirements=[{"id": "other", "text": "Use only its own evidence"}], allowed_tools=[]))
    with pytest.raises(AiclError):
        reader.execute_scoped(args, "cross-run", auth, other["id"])
    assert len(outbound) == 1


@pytest.mark.parametrize("secret", ["sk-" + "b" * 40, "actual-private-provider-credential"])
def test_text_projection_never_filters_body_secrets_or_weakens_final_guard(build_env, secret):
    _, auth, _, runtime, run, _, step, _ = saved_page(build_env, "Public evidence " + secret)
    result = runtime.tools.get("artifact.read").execute_scoped(
        {"ref": step["output_ref"], "source_index": 0, "field": "text", "public_preview": True},
        "secret-in-body", auth, run["id"]).payload
    assert secret in result["text"]  # Never silently reinterpret source evidence.
    validator = OpenAIDecisionModel("actual-private-provider-credential", tool_specs=runtime.tools.specs())
    context = {"definition": RunDefinition(objective="Read saved evidence",
        requirements=[{"id": "report", "text": "Report evidence"}], allowed_tools=[]).model_dump(mode="json"),
        "observations": [{"tool": "artifact.read", "result": result}]}
    with pytest.raises(InferenceNoChargeError, match="sensitive_or_invalid_input"):
        validator.validate_context(context)
