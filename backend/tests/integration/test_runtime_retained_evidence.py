"""Old evidence remains identifiable and useful when full bodies no longer fit."""
import json

import httpx

from aicl.agent_runtime.contracts import canonical_json
from aicl.agent_runtime.openai_model import MAX_REQUEST_BYTES, OpenAIDecisionModel
from test_agent_runtime_session import envelope
from test_runtime_research_prelude import rows, setup


def test_overlapping_reads_keep_compact_old_sources_and_complete_latest_batch(build_env):
    urls = [f"https://news.example/report-{index}" for index in range(5)]

    def response(request):
        index = urls.index(str(request.url))
        text = (f"FINDING-{index}: published October 27, 2026. " + "Source evidence. " * 60
                + f" INTERIOR-{index}: supported detail at https://news.example/report-{index}. "
                + "Source evidence. " * 1940)
        body = f"<title>Source {index}</title><main><p>{text}</p></main>".encode()
        return httpx.Response(200, headers={"content-type": "text/html"}, stream=httpx.ByteStream(body))

    requests = {}

    def first(context):
        sources = json.loads(context["observations"][0]["text"])["evidence"]
        requests.update({source["url"]: {**source["retrieval"]["arguments"], "offset": 0}
                         for source in sources})
        return envelope(actions=[{"name": "artifact.read", "arguments": requests[url]} for url in urls[:3]])

    def second(context):
        read = next(item for item in context["observations"] if item["tool"] == "artifact.read")
        return envelope(memory=[{"op": "upsert", "key": "source-finding", "kind": "observation",
            "text": "INTERIOR-0: supported detail at https://news.example/report-0, dated October 27, 2026; page dates remain unverified.", "evidence_refs": [read["ref"]]}],
            actions=[{"name": "artifact.read", "arguments": {**requests[urls[0]], "offset": 2000}},
                     {"name": "artifact.read", "arguments": requests[urls[3]]}])

    def third(context):
        return envelope(actions=[{"name": "artifact.read", "arguments": {**requests[urls[0]], "offset": 6000}},
                                 {"name": "artifact.read", "arguments": requests[urls[4]]}])

    env, auth, _, runtime, model, _, run, outbound, _, _ = setup(build_env, queries=(), sources=urls,
        handler=response, responses=[first, second, third,
            envelope(control={"next": "wait_owner", "question": "Review these findings.", "options": []})])
    validator = OpenAIDecisionModel("offline-retention-fixture", tool_specs=runtime.tools.specs())
    model.validate_context = validator.validate_context
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "waiting_owner", result["reason"]
    assert len(model.calls) == 4 and len(outbound) == 5
    context = model.calls[-1]
    assert context["memory"]["source-finding"]["authority"] == "derived"
    assert "INTERIOR-0" in context["memory"]["source-finding"]["text"]
    overview = json.loads(next(item["text"] for item in context["observations"] if item["tool"] == "public.research"))
    assert [source["url"] for source in overview["evidence"]] == urls
    assert all(source["instruction_authority"] == "untrusted_evidence" for source in overview["evidence"])
    assert "not complete retained bodies" in context["read_coverage"]["body_retention"]
    coverage = {canonical_json(source["selector"]): source for source in context["read_coverage"]["sources"]}
    first_key = canonical_json({key: value for key, value in requests[urls[0]].items() if key not in {"offset", "max_chars"}})
    assert coverage[first_key]["returned_ranges"] == [[0, 10000]]
    reads = [step for step in rows(env, "agent_step") if step["tool_name"] == "artifact.read"]
    observations = {item["ref"]: item for item in context["observations"] if item["tool"] == "artifact.read"}
    assert any(item.get("omitted") for item in observations.values())
    with env.db.reader() as conn:
        # Every new requested result reaches the following call unchanged.
        for step in reads[-2:]:
            assert observations[step["output_ref"]]["result"] == runtime.repo.get_content(
                conn, auth, run["id"], step["output_ref"])
        # An old source whose complete body was evicted retains a verbatim,
        # sourced finding; no generated summary or new receipt is invented.
        retained = [excerpt for source in coverage.values() for excerpt in source["retained_excerpts"]]
        assert retained
        assert any("FINDING-" in excerpt["text"] for excerpt in retained)
        for excerpt in retained:
            saved = runtime.repo.get_content(conn, auth, run["id"], excerpt["receipt_ref"])
            start = excerpt["offset"] - saved.get("offset", 0)
            assert excerpt["text"] == saved["text"][start:start + len(excerpt["text"])]
    for context in model.calls:
        assert len(canonical_json(context)) <= 24000
        assert len(validator.build_request(context)) <= MAX_REQUEST_BYTES
