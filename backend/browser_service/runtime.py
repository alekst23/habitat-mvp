"""Ephemeral browser sessions. Browser state belongs to the AICL broker."""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import secrets
from urllib.parse import urlsplit

from browser_service.network import NetworkDenied, PublicConnectProxy, origin, validate_url


class BrowserError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Settings:
    token: str
    max_sessions: int = 1
    test_mode: bool = False
    fixture_origin: str = ""
    environment: str = "production"

    def __post_init__(self):
        if len(self.token) < 32:
            raise ValueError("BROWSER_SERVICE_TOKEN must contain at least 32 characters.")
        if not 1 <= self.max_sessions <= 8:
            raise ValueError("BROWSER_MAX_SESSIONS must be between 1 and 8.")
        if self.test_mode:
            if self.environment != "test" or not self.fixture_origin:
                raise ValueError("Fixture transport requires BROWSER_ENVIRONMENT=test and an exact fixture origin.")
            parsed = urlsplit(self.fixture_origin)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or origin(self.fixture_origin) != self.fixture_origin:
                raise ValueError("BROWSER_TEST_FIXTURE_ORIGIN must be an exact HTTP(S) origin.")
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("Fixture origin cannot contain credentials.")
        elif self.fixture_origin:
            raise ValueError("Fixture origin cannot be configured outside test mode.")

    @classmethod
    def from_env(cls):
        return cls(token=os.environ.get("BROWSER_SERVICE_TOKEN", ""),
                   max_sessions=int(os.environ.get("BROWSER_MAX_SESSIONS", "1")),
                   test_mode=os.environ.get("BROWSER_TEST_MODE", "0") == "1",
                   fixture_origin=os.environ.get("BROWSER_TEST_FIXTURE_ORIGIN", ""),
                   environment=os.environ.get("BROWSER_ENVIRONMENT", "production"))


class PlaywrightEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.driver = None
        self.proxy = PublicConnectProxy()

    async def start(self):
        from playwright.async_api import async_playwright
        if not self.settings.test_mode:
            await self.proxy.start()
        self.driver = await async_playwright().start()
        # Refuse readiness if this host cannot actually run a sandboxed browser.
        # In particular, never fall back to --no-sandbox on Render.
        try:
            browser = await self._launch()
            await browser.close()
        except Exception as exc:
            await self.close()
            raise BrowserError("browser_unavailable", "Sandboxed Chromium could not start on this host.", 503) from exc

    async def _launch(self):
        env = {name: os.environ[name] for name in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL") if name in os.environ}
        options = dict(headless=True, chromium_sandbox=True, env=env,
                       args=["--disable-quic", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                             "--disable-dev-shm-usage"])
        if not self.settings.test_mode:
            options["proxy"] = {"server": self.proxy.url, "bypass": "<-loopback>"}
        return await self.driver.chromium.launch(**options)

    async def open(self, url: str, state: dict | None):
        browser = await self._launch()
        try:
            context = await browser.new_context(viewport={"width": 1280, "height": 720},
                                                storage_state=state, service_workers="block",
                                                accept_downloads=False, permissions=[])
            async def guard(route):
                try:
                    validate_url(route.request.url, self.settings.fixture_origin)
                except (NetworkDenied, ValueError):
                    await route.abort("blockedbyclient")
                else:
                    await route.continue_()
            await context.route("**/*", guard)
            # Remote web sockets are not needed for the MVP sign-in handoff;
            # block them rather than adding another egress path.
            async def reject_websocket(socket):
                await socket.close()
            await context.route_web_socket("**/*", reject_websocket)
            page = await context.new_page()
            page.set_default_timeout(15000)
            page.set_default_navigation_timeout(30000)
            await page.goto(url, wait_until="domcontentloaded")
            return BrowserHandle(browser, context)
        except Exception:
            await browser.close()
            raise

    async def close(self):
        if self.driver:
            await self.driver.stop()
            self.driver = None
        await self.proxy.close()


class BrowserHandle:
    def __init__(self, browser, context):
        self.browser, self.context = browser, context

    def page(self):
        pages = [page for page in self.context.pages if not page.is_closed()]
        if not pages:
            raise BrowserError("session_closed", "This browser session has closed.", 410)
        return pages[-1]

    async def metadata(self):
        page = self.page()
        return {"url": page.url, "title": (await page.title())[:300], "width": 1280, "height": 720}

    async def frame(self):
        page = self.page()
        image = await page.screenshot(type="jpeg", quality=70, animations="disabled", timeout=15000)
        return {**await self.metadata(), "image": base64.b64encode(image).decode("ascii")}

    async def input(self, action: dict):
        page = self.page()
        kind = action["type"]
        if kind == "click":
            await page.mouse.click(action["x"], action["y"])
        elif kind == "text":
            # Never retain typed input or expose it to a model/trace.
            await page.keyboard.insert_text(action["text"])
        elif kind == "key":
            await page.keyboard.press(action["key"])
        elif kind == "scroll":
            await page.mouse.wheel(0, action["delta_y"])
        return await self.metadata()

    async def navigate(self, url):
        await self.page().goto(url, wait_until="domcontentloaded")
        return await self.metadata()

    async def text(self):
        page = self.page()
        # Excludes input values. No DOM, cookies, storage or network logs.
        text = await page.locator("body").inner_text(timeout=15000)
        return {"url": page.url, "title": (await page.title())[:300], "text": text[:24000]}

    async def snapshot(self):
        state = await self.context.storage_state(indexed_db=True)
        if len(json.dumps(state).encode()) > 2_000_000:
            raise BrowserError("state_too_large", "This website's session is too large to save.", 413)
        return {"storage_state": state, "url": self.page().url}

    async def close(self):
        await self.browser.close()


@dataclass
class Session:
    id: str
    mode: str
    expires_at: datetime
    fingerprint: str
    handle: object
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    closing: asyncio.Task | None = None


class SessionManager:
    def __init__(self, settings: Settings, *, engine=None, clock=None):
        self.settings = settings
        self.engine = engine or PlaywrightEngine(settings)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sessions: dict[str, Session] = {}
        self.keys: dict[str, str] = {}
        self.cancelled_keys: dict[str, datetime] = {}
        self.lock = asyncio.Lock()

    async def start(self):
        await self.engine.start()

    async def close(self):
        try:
            await asyncio.gather(*(self.delete(session.id) for session in list(self.sessions.values())), return_exceptions=True)
        finally:
            await self.engine.close()

    async def expire(self):
        for session in list(self.sessions.values()):
            if session.expires_at <= self.clock():
                try:
                    await self.delete(session.id)
                except BrowserError:
                    # Retain the slot and retry termination on the next reap.
                    pass

    async def create(self, *, idempotency_key, url, storage_state=None, mode="owner", ttl_seconds=600):
        validate_url(url, self.settings.fixture_origin)
        payload = json.dumps({"url": url, "state": storage_state, "mode": mode, "ttl": ttl_seconds}, sort_keys=True)
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        async with self.lock:
            self._prune_cancelled_keys()
            if idempotency_key in self.cancelled_keys:
                raise BrowserError("session_cancelled", "This browser handoff was cancelled.", 409)
            await self.expire()
            previous = self.sessions.get(self.keys.get(idempotency_key, ""))
            if previous:
                if not secrets.compare_digest(previous.fingerprint, fingerprint):
                    raise BrowserError("conflict", "This session request changed.", 409)
                async with previous.lock:
                    return self._identity(previous, await previous.handle.metadata())
            if len(self.sessions) >= self.settings.max_sessions:
                raise BrowserError("browser_busy", "The browser is busy. Try again shortly.", 503)
            try:
                handle = await self.engine.open(url, storage_state)
            except BrowserError:
                raise
            except Exception as exc:
                raise BrowserError("browser_unavailable", "The website could not be opened in the protected browser.", 503) from exc
            session = Session(secrets.token_urlsafe(32), mode, self.clock() + timedelta(seconds=ttl_seconds), fingerprint, handle)
            self.sessions[session.id] = session
            self.keys[idempotency_key] = session.id
            if idempotency_key in self.cancelled_keys:
                await self.delete(session.id)
                raise BrowserError("session_cancelled", "This browser handoff was cancelled.", 409)
            try:
                return self._identity(session, await handle.metadata())
            except Exception as exc:
                await self.delete(session.id)
                raise BrowserError("browser_unavailable", "The protected browser could not become ready.", 503) from exc

    @staticmethod
    def _identity(session, metadata):
        return {**metadata, "session_id": session.id, "expires_at": session.expires_at.isoformat()}

    async def get(self, session_id, mode=None):
        session = self.sessions.get(session_id)
        if session is None:
            raise BrowserError("session_not_found", "This browser session is no longer available.", 404)
        if session.expires_at <= self.clock():
            await self.delete(session_id)
            raise BrowserError("session_expired", "This browser session has expired.", 410)
        if mode and session.mode != mode:
            raise BrowserError("mode_denied", "This operation is unavailable during the current handoff.", 403)
        if session.closing:
            raise BrowserError("session_closing", "This browser session is closing.", 409)
        return session

    async def operate(self, session_id, operation, *, mode=None, argument=None):
        session = await self.get(session_id, mode)
        async with session.lock:
            if session_id not in self.sessions or session.closing:
                raise BrowserError("session_closed", "This browser session has closed.", 410)
            if session.expires_at <= self.clock():
                raise BrowserError("session_expired", "This browser session has expired.", 410)
            try:
                method = getattr(session.handle, operation)
                return await method() if argument is None else await method(argument)
            except BrowserError:
                raise
            except Exception as exc:
                raise BrowserError("browser_operation_failed", "The browser could not complete that operation.", 502) from exc

    async def delete(self, session_id):
        session = self.sessions.get(session_id)
        if session is None:
            return
        # Concurrent callers await one confirmed shutdown. Capacity remains
        # occupied until Chromium has exited; a failed shutdown cannot release
        # a still-live owner browser to a resumed worker.
        if session.closing is None or (session.closing.done() and session.closing.exception() is not None):
            async def terminate():
                async with session.lock:
                    try:
                        await session.handle.close()
                    except Exception as exc:
                        raise BrowserError("close_failed", "The browser could not be closed. Try again shortly.", 503) from exc
                    self.sessions.pop(session_id, None)
                    self.keys = {key: value for key, value in self.keys.items() if value != session_id}
            session.closing = asyncio.create_task(terminate())
        await asyncio.shield(session.closing)

    def _prune_cancelled_keys(self):
        now = self.clock()
        self.cancelled_keys = {key: expiry for key, expiry in self.cancelled_keys.items() if expiry > now}

    async def cancel_key(self, idempotency_key):
        # Install the fence before awaiting the creation lock: an in-flight
        # create must close its browser before publishing a usable session.
        # Thirty minutes exceeds both the broker lease and the runtime maximum
        # session TTL (15 minutes). Broker retries must stop at their lease.
        self._prune_cancelled_keys()
        self.cancelled_keys[idempotency_key] = self.clock() + timedelta(minutes=30)
        async with self.lock:
            session_id = self.keys.get(idempotency_key)
            if session_id:
                await self.delete(session_id)
