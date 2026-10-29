"""Every freshly requested read reaches the next decision within fixed bounds."""
from copy import deepcopy
import json

import httpx
import pytest

from aicl.agent_runtime.contracts import canonical_json
from aicl.agent_runtime.openai_model import MAX_REQUEST_BYTES, OpenAIDecisionModel
from test_agent_runtime_session import envelope
from test_runtime_research_prelude import rows, setup


@pytest.mark.parametrize("filler,chunk_chars", [("Public detail. ", 4000), ("界", 2000)])
def test_latest_four_read_batch_survives_overview_packing_and_duplicate_requests_are_suppressed(
        build_env, filler, chunk_chars):
    urls = [f"https://news.example/article-{index}" for index in range(2)]

    def response(request):
        if request.url.host == "api.search.brave.com":
            # Search discovery metadata must not crowd newly requested reads
            # out of the next decision, even before adding any snippet text.
            data = {"web": {"results": [{"url": f"https://news.example/discovery-{index}/" + "x" * 1200,
                "title": "Title " * 40, "description": "Public discovery snippet."} for index in range(5)]}}
            return httpx.Response(200, headers={"content-type": "application/json"},
                                  stream=httpx.ByteStream(json.dumps(data).encode()))
        index = urls.index(str(request.url))
        body = (f'<title>Source {index}</title><main><p>SOURCE-{index} {filler * 16000}</p></main>').encode()
        return httpx.Response(200, headers={"content-type": "text/html"}, stream=httpx.ByteStream(body))

    requested = []

    def batch(context):
        sources = json.loads(context["observations"][0]["text"])["evidence"]
        for source in sources:
            if source.get("url") in urls:
                for offset in (0, chunk_chars):
                    requested.append({**source["retrieval"]["arguments"], "offset": offset, "max_chars": chunk_chars})
        assert len(requested) == 4
        return envelope(actions=[{"name": "artifact.read", "arguments": args} for args in requested])

    def repeat_two(context):
        reads = [item for item in context["observations"] if item["tool"] == "artifact.read"]
        assert len(reads) == 4 and all(not item.get("omitted") for item in reads)
        assert all(len(item["result"]["text"]) == chunk_chars for item in reads)
        return envelope(actions=[{"name": "artifact.read", "arguments": deepcopy(args)} for args in requested[:2]])

    env, auth, _, runtime, model, _, run, outbound, _, _ = setup(build_env, sources=urls, handler=response,
        responses=[batch, repeat_two, envelope(control={"next": "wait_owner", "question": "Review the result.", "options": []})])
    validator = OpenAIDecisionModel("offline-batch-fixture", tool_specs=runtime.tools.specs())
    model.validate_context = validator.validate_context
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "waiting_owner" and len(model.calls) == 3 and len(outbound) == 3
    assert result["action_count"] == 7
    steps = rows(env, "agent_step")
    reads = [step for step in steps if step["tool_name"] == "artifact.read"]
    assert len(reads) == 4 and len(steps) == 8
    with env.db.reader() as conn:
        values = {step["output_ref"]: runtime.repo.get_content(conn, auth, run["id"], step["output_ref"]) for step in reads}
    first = {item["ref"]: item for item in model.calls[1]["observations"] if item["tool"] == "artifact.read"}
    assert set(first) == {step["output_ref"] for step in reads[:4]}
    assert all(first[ref]["result"] == values[ref] for ref in first)
    last = {item["ref"]: item for item in model.calls[2]["observations"] if item["tool"] == "artifact.read"}
    assert set(last) == set(first)
    assert all(last[ref].get("omitted") or last[ref]["result"] == values[ref] for ref in last)
    assert len(model.calls[2]["read_coverage"]["sources"]) == 2
    assert all(item["returned_ranges"] == [[0, chunk_chars * 2]] for item in model.calls[2]["read_coverage"]["sources"])
    assert model.calls[2]["progress_feedback"]["skipped_read_count"] == 2
    assert len([event for event in result["events"] if event["kind"] == "reads_suppressed"]) == 1
    for context in model.calls:
        assert len(canonical_json(context)) <= 24000
        assert len(validator.build_request(context)) <= MAX_REQUEST_BYTES
    # The original four read receipts remain immutable and retrievable.
    # Suppression neither fabricates read receipts nor erases paid decision audit.
    with env.db.reader() as conn:
        for ref, value in values.items():
            assert runtime.repo.get_content(conn, auth, run["id"], ref) == value


def test_recent_older_reads_take_priority_over_reexpanding_source_overview_bodies(build_env):
    urls = [f"https://news.example/report-{index}" for index in range(4)]

    def response(request):
        if request.url.host == "api.search.brave.com":
            data = {"web": {"results": [{"url": f"https://news.example/discovery-{index}/" + "x" * 1200,
                "title": "Public discovery " * 15, "description": "Background."} for index in range(5)]}}
            return httpx.Response(200, headers={"content-type": "application/json"},
                                  stream=httpx.ByteStream(json.dumps(data).encode()))
        index = urls.index(str(request.url))
        content = "Short source evidence." if index == 3 else f"SOURCE-{index} " + "Specific finding. " * 1200
        body = (f'<title>Source {index}</title><meta property="article:published_time" content="2026-10-27">'
                f'<main><p>{content}</p></main>').encode()
        return httpx.Response(200, headers={"content-type": "text/html"}, stream=httpx.ByteStream(body))

    arguments = {}

    def first_batch(context):
        sources = json.loads(context["observations"][0]["text"])["evidence"]
        for source in sources:
            if source.get("url") in urls:
                arguments[source["url"]] = {**source["retrieval"]["arguments"], "offset": 0, "max_chars": 4000}
        return envelope(actions=[{"name": "artifact.read", "arguments": arguments[url]} for url in urls[:3]])

    def second_batch(context):
        visible = [item for item in context["observations"] if item["tool"] == "artifact.read" and not item.get("omitted")]
        assert len(visible) == 3
        return envelope(actions=[{"name": "artifact.read", "arguments": arguments[urls[3]]},
                                 {"name": "artifact.read", "arguments": {**arguments[urls[0]], "offset": 4000}}])

    env, auth, _, runtime, model, _, run, outbound, _, _ = setup(build_env, sources=urls, handler=response,
        responses=[first_batch, second_batch, envelope(control={"next": "wait_owner", "question": "Review the findings.", "options": []})])
    validator = OpenAIDecisionModel("offline-retention-fixture", tool_specs=runtime.tools.specs())
    model.validate_context = validator.validate_context
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "waiting_owner" and len(model.calls) == 3
    assert len(outbound) == 5 and result["action_count"] == 10
    reads = [step for step in rows(env, "agent_step") if step["tool_name"] == "artifact.read"]
    visible = {item["ref"]: item for item in model.calls[2]["observations"] if item["tool"] == "artifact.read"}
    assert len(reads) == len(visible) == 5
    with env.db.reader() as conn:
        for step in reads:
            assert not visible[step["output_ref"]].get("omitted")
            assert visible[step["output_ref"]]["result"] == runtime.repo.get_content(conn, auth, run["id"], step["output_ref"])
    overview = json.loads(model.calls[2]["observations"][0]["text"])
    assert all(source["details_omitted"] for source in overview["evidence"])
    assert all(source["retrieval"] for source in overview["evidence"])
    for context in model.calls:
        assert len(canonical_json(context)) <= 24000
        assert len(validator.build_request(context)) <= MAX_REQUEST_BYTES
