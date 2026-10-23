"""Exercise actual CONNECT transport while substituting DNS and upstream sockets."""
import asyncio
import socket

import pytest

from browser_service.network import NetworkDenied, PublicConnectProxy, public_ip, resolve_public, validate_url


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.1", "100.64.0.1", "0.0.0.0", "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1", "224.0.0.1", "64:ff9b::7f00:1", "2002:7f00:1::", "2001:0::1", "2606:4700:4700::1111%lo0"])
def test_nonpublic_addresses_are_denied(address):
    assert not public_ip(address)


def test_mixed_dns_fails_closed_before_connection():
    async def mixed(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port)) for ip in ("8.8.8.8", "127.0.0.1")]
    with pytest.raises(NetworkDenied):
        asyncio.run(resolve_public("public.example", resolver=mixed))


def test_connect_pins_validated_numeric_ip_and_transports_bytes():
    async def exercise():
        calls = []
        async def echo(reader, writer):
            try:
                writer.write(await reader.readexactly(4))
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        local = await asyncio.start_server(echo, "127.0.0.1", 0)
        async def lookup(host, port, **kwargs):
            calls.append(("dns", host))
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443))]
        async def connect(host, port, **kwargs):
            calls.append(("connect", host, port))
            return await asyncio.open_connection("127.0.0.1", local.sockets[0].getsockname()[1])
        proxy = PublicConnectProxy(resolver=lookup, connector=connect)
        await proxy.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy.server.sockets[0].getsockname()[1])
            writer.write(b"CONNECT login.example:443 HTTP/1.1\r\nHost: login.example:443\r\n\r\n")
            await writer.drain()
            assert await reader.readuntil(b"\r\n\r\n") == b"HTTP/1.1 200 Connection Established\r\n\r\n"
            writer.write(b"test")
            await writer.drain()
            assert await reader.readexactly(4) == b"test"
            writer.close()
            await writer.wait_closed()
            assert calls == [("dns", "login.example"), ("connect", "8.8.8.8", 443)]
        finally:
            await proxy.close()
            local.close()
            await local.wait_closed()
    asyncio.run(exercise())


@pytest.mark.parametrize("wire_request", [b"GET http://169.254.169.254/ HTTP/1.1\r\n\r\n", b"CONNECT public.example:80 HTTP/1.1\r\n\r\n", b"CONNECT 127.0.0.1:443 HTTP/1.1\r\n\r\n"])
def test_proxy_denies_plain_http_wrong_ports_and_private_targets(wire_request):
    async def exercise():
        async def fail(*args, **kwargs):
            pytest.fail("Rejected destinations must never connect")
        proxy = PublicConnectProxy(connector=fail)
        await proxy.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy.server.sockets[0].getsockname()[1])
            writer.write(wire_request)
            await writer.drain()
            assert (await reader.read()).startswith(b"HTTP/1.1 403")
            writer.close()
            await writer.wait_closed()
        finally:
            await proxy.close()
    asyncio.run(exercise())
