"""HTTPS CONNECT transport that pins each connection to a validated public IP.

The browser never resolves the destination for these connections. Rejecting all
mixed public/private DNS answers avoids choosing an accidentally unsafe address;
opening the selected numeric address prevents a second, rebinding DNS lookup.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class NetworkDenied(ValueError):
    pass


def public_ip(value: str) -> bool:
    if "%" in value:
        return False
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return public_ip(str(address.ipv4_mapped))
    if isinstance(address, ipaddress.IPv6Address) and any(address in network for network in (
        ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"),
        ipaddress.ip_network("2002::/16"), ipaddress.ip_network("2001::/32"),
    )):
        # Transition/translation addresses can encode a private IPv4 endpoint.
        return False
    return address.is_global and not (address.is_multicast or address.is_reserved or address.is_unspecified)


def validate_url(url: str, fixture_origin: str = "") -> str:
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 32 for c in url) or "\\" in url:
        raise NetworkDenied("A valid website URL is required.")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise NetworkDenied("A valid website URL is required.") from exc
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise NetworkDenied("Website URLs cannot contain credentials.")
    if fixture_origin:
        if origin(url) != fixture_origin:
            raise NetworkDenied("Only the configured test fixture is available.")
        return url
    if parsed.scheme != "https" or port not in (None, 443):
        raise NetworkDenied("Only public HTTPS websites on port 443 are available.")
    host = parsed.hostname.lower().rstrip(".")
    if host in ("localhost", "metadata.google.internal") or host.endswith((".localhost", ".local", ".internal")):
        raise NetworkDenied("Private network destinations are unavailable.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if "." not in host or any(not part or len(part) > 63 for part in host.split(".")):
            raise NetworkDenied("A public website hostname is required.")
    else:
        if not public_ip(host):
            raise NetworkDenied("Private network destinations are unavailable.")
    return url


def origin(url: str) -> str:
    parsed = urlsplit(url)
    port = parsed.port
    host = parsed.hostname or ""
    host = f"[{host}]" if ":" in host else host
    port_part = f":{port}" if port and port != {"https": 443, "http": 80}.get(parsed.scheme) else ""
    return f"{parsed.scheme}://{host}{port_part}"


async def resolve_public(host: str, port: int = 443, *, resolver=None) -> list[tuple[int, str]]:
    if port != 443:
        raise NetworkDenied("Only HTTPS is available.")
    lookup = resolver or asyncio.get_running_loop().getaddrinfo
    records = await lookup(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    addresses = list(dict.fromkeys((record[0], record[4][0]) for record in records))
    if not addresses or any(not public_ip(address) for _, address in addresses):
        raise NetworkDenied("Private or mixed network destinations are unavailable.")
    return addresses


class PublicConnectProxy:
    """Local-only proxy. No HTTP requests, private addresses or arbitrary ports."""

    def __init__(self, *, resolver=None, connector=None):
        self.resolver = resolver
        self.connector = connector or asyncio.open_connection
        self.server = None
        self.connections: set[asyncio.Task] = set()

    async def start(self):
        self.server = await asyncio.start_server(self._accept, "127.0.0.1", 0, limit=16384)
        return self.url

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for task in list(self.connections):
            task.cancel()
        await asyncio.gather(*self.connections, return_exceptions=True)

    async def _accept(self, reader, writer):
        task = asyncio.current_task()
        self.connections.add(task)
        upstream = None
        try:
            headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            line = headers.split(b"\r\n", 1)[0].decode("ascii")
            method, authority, version = line.split(" ")
            if method != "CONNECT" or version not in ("HTTP/1.0", "HTTP/1.1"):
                raise NetworkDenied("HTTPS CONNECT required.")
            target = urlsplit("https://" + authority)
            if target.path or target.query or target.fragment or target.username is not None or target.password is not None:
                raise NetworkDenied("Invalid destination.")
            if target.port != 443 or not target.hostname:
                raise NetworkDenied("Only HTTPS is available.")
            validate_url("https://" + authority)
            addresses = await asyncio.wait_for(resolve_public(target.hostname, target.port, resolver=self.resolver), 10)
            for family, address in addresses:
                try:
                    remote, upstream = await asyncio.wait_for(self.connector(address, 443, family=family), 10)
                    break
                except (OSError, asyncio.TimeoutError):
                    continue
            if upstream is None:
                raise NetworkDenied("Destination unavailable.")
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

            async def copy(source, destination):
                while data := await source.read(65536):
                    destination.write(data)
                    await destination.drain()

            pipes = [asyncio.create_task(copy(reader, upstream)), asyncio.create_task(copy(remote, writer))]
            try:
                await asyncio.wait(pipes, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for pipe in pipes:
                    pipe.cancel()
                await asyncio.gather(*pipes, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never log request lines, URLs, TLS payloads or exception details.
            if upstream is None:
                writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                try:
                    await writer.drain()
                except (ConnectionError, OSError):
                    pass
        finally:
            for connection in (upstream, writer):
                if connection:
                    connection.close()
                    try:
                        await connection.wait_closed()
                    except (ConnectionError, OSError):
                        pass
            self.connections.discard(task)
