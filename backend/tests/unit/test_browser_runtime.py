"""Private browser contract and lifecycle checks with no external website calls."""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from browser_service.app import create_app
from browser_service.runtime import BrowserError, PlaywrightEngine, SessionManager, Settings

TOKEN = "browser-test-service-token-" + "x" * 32
HEADERS = {"Authorization": "Bearer " + TOKEN}


class Handle:
    def __init__(self, url, state):
        self.url, self.state, self.closed, self.inputs = url, state or {"cookies": [], "origins": []}, False, []

    async def metadata(self):
        return {"url": self.url, "title": "Login", "width": 1280, "height": 720}

    async def frame(self):
        return {**await self.metadata(), "image": "anBlZw=="}

    async def input(self, action):
        self.inputs.append(action)
        return await self.metadata()

    async def navigate(self, url):
        self.url = url
        return await self.metadata()

    async def text(self):
        return {"url": self.url, "title": "Account", "text": "Protected content"}

    async def snapshot(self):
        return {"storage_state": self.state, "url": self.url}

    async def close(self):
        self.closed = True


class Engine:
    def __init__(self):
        self.handles = []

    async def start(self):
        pass

    async def close(self):
        pass

    async def open(self, url, state):
        handle = Handle(url, state)
        self.handles.append(handle)
        return handle


def new_session(client, **overrides):
    return client.post("/sessions", headers=HEADERS,
                       json={"idempotency_key": "request:1", "url": "https://accounts.example.com/", **overrides})


def test_private_api_requires_bearer_and_never_echoes_rejected_login_input():
    with TestClient(create_app(Settings(TOKEN), engine=Engine())) as client:
        assert client.get("/sessions/unknown/frame").status_code == 401
        response = new_session(client)
        assert response.status_code == 200
        sid = response.json()["session_id"]
        response = client.post(f"/sessions/{sid}/input", headers=HEADERS,
                               json={"type": "key", "key": "password-secret", "text": "credential-secret"})
        assert response.status_code == 422
        assert "secret" not in response.text
        assert response.headers["cache-control"] == "no-store"


def test_owner_handoff_blocks_worker_read_and_navigation_and_worker_blocks_owner_input():
    with TestClient(create_app(Settings(TOKEN), engine=Engine())) as client:
        sid = new_session(client).json()["session_id"]
        assert client.get(f"/sessions/{sid}/page", headers=HEADERS).status_code == 403
        assert client.post(f"/sessions/{sid}/navigate", headers=HEADERS, json={"url": "https://example.com/"}).status_code == 403
        assert client.get(f"/sessions/{sid}/frame", headers=HEADERS).status_code == 200
        assert client.post(f"/sessions/{sid}/input", headers=HEADERS, json={"type": "key", "key": "Shift+PageDown"}).status_code == 200
        assert client.delete(f"/sessions/{sid}", headers=HEADERS).json() == {"closed": True}
        sid = new_session(client, mode="worker").json()["session_id"]
        assert client.get(f"/sessions/{sid}/page", headers=HEADERS).status_code == 200
        assert client.get(f"/sessions/{sid}/frame", headers=HEADERS).status_code == 403
        assert client.post(f"/sessions/{sid}/input", headers=HEADERS, json={"type": "text", "text": "password"}).status_code == 403


def test_idempotency_capacity_expiry_and_idempotent_close():
    now = [datetime(2026, 10, 23, tzinfo=timezone.utc)]
    engine = Engine()
    with TestClient(create_app(Settings(TOKEN), engine=engine, clock=lambda: now[0])) as client:
        first = new_session(client).json()
        assert new_session(client).json()["session_id"] == first["session_id"]
        assert len(engine.handles) == 1
        assert new_session(client, url="https://different.example/").status_code == 409
        assert new_session(client, idempotency_key="request:2").status_code == 503
        now[0] += timedelta(seconds=601)
        assert client.get(f"/sessions/{first['session_id']}/frame", headers=HEADERS).status_code == 410
        assert engine.handles[0].closed
        assert new_session(client, idempotency_key="request:2").status_code == 200
        assert client.delete(f"/sessions/{first['session_id']}", headers=HEADERS).status_code == 200


@pytest.mark.parametrize("url", ["http://example.com", "https://127.0.0.1", "https://[::1]", "https://metadata.google.internal", "https://user:pass@example.com", "https://example.com:8443"])
def test_api_rejects_unsafe_initial_urls(url):
    engine = Engine()
    with TestClient(create_app(Settings(TOKEN), engine=engine)) as client:
        assert new_session(client, url=url).status_code == 400
        assert not engine.handles


def test_fixture_transport_cannot_be_enabled_in_production():
    with pytest.raises(ValueError, match="BROWSER_ENVIRONMENT=test"):
        Settings(TOKEN, test_mode=True, fixture_origin="http://127.0.0.1:9999")
    with pytest.raises(ValueError, match="outside test"):
        Settings(TOKEN, fixture_origin="http://127.0.0.1:9999")
    with TestClient(create_app(Settings(TOKEN, test_mode=True, environment="test", fixture_origin="http://127.0.0.1:9999"), engine=Engine())) as client:
        assert new_session(client, url="http://127.0.0.1:9999/login").status_code == 200
        assert new_session(client, url="http://127.0.0.1:9998/login").status_code == 400


def test_launch_requires_sandbox_and_strips_service_secret(monkeypatch):
    monkeypatch.setenv("BROWSER_SERVICE_TOKEN", "must-not-reach-chromium")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-chromium-either")
    captured = {}
    class Driver:
        chromium = None
        async def launch(self, **kwargs):
            captured.update(kwargs)
    driver = Driver()
    driver.chromium = driver
    engine = PlaywrightEngine(Settings(TOKEN, test_mode=True, environment="test", fixture_origin="http://127.0.0.1:9999"))
    engine.driver = driver
    asyncio.run(engine._launch())
    assert captured["chromium_sandbox"] is True
    assert "--no-sandbox" not in captured["args"]
    assert "BROWSER_SERVICE_TOKEN" not in captured["env"]
    assert "OPENAI_API_KEY" not in captured["env"]


def test_snapshot_is_trusted_only_and_preserves_state_for_broker():
    state = {"cookies": [{"name": "auth", "value": "secret", "domain": "example.com", "path": "/"}], "origins": []}
    with TestClient(create_app(Settings(TOKEN), engine=Engine())) as client:
        sid = new_session(client, storage_state=state).json()["session_id"]
        assert client.post(f"/sessions/{sid}/snapshot").status_code == 401
        snapshot = client.post(f"/sessions/{sid}/snapshot", headers=HEADERS)
        assert snapshot.json()["storage_state"] == state
        assert "secret" not in client.get(f"/sessions/{sid}/frame", headers=HEADERS).text


def test_concurrent_close_waits_for_browser_exit_before_releasing_capacity():
    async def exercise():
        engine = Engine()
        manager = SessionManager(Settings(TOKEN), engine=engine)
        created = await manager.create(idempotency_key="one", url="https://example.com")
        handle = engine.handles[0]
        entered, finished = asyncio.Event(), asyncio.Event()
        async def slow_close():
            entered.set()
            await finished.wait()
            handle.closed = True
        handle.close = slow_close
        first = asyncio.create_task(manager.delete(created["session_id"]))
        await entered.wait()
        second = asyncio.create_task(manager.delete(created["session_id"]))
        await asyncio.sleep(0)
        assert not first.done() and not second.done()
        with pytest.raises(BrowserError, match="browser_busy"):
            await manager.create(idempotency_key="two", url="https://example.com")
        finished.set()
        await asyncio.gather(first, second)
        assert handle.closed and not manager.sessions
    asyncio.run(exercise())


def test_failed_close_retains_capacity_and_can_retry():
    async def exercise():
        engine = Engine()
        manager = SessionManager(Settings(TOKEN), engine=engine)
        created = await manager.create(idempotency_key="one", url="https://example.com")
        handle = engine.handles[0]
        original = handle.close
        async def fail_close():
            raise OSError("secret raw browser failure")
        handle.close = fail_close
        with pytest.raises(BrowserError, match="close_failed"):
            await manager.delete(created["session_id"])
        assert created["session_id"] in manager.sessions
        with pytest.raises(BrowserError, match="browser_busy"):
            await manager.create(idempotency_key="two", url="https://example.com")
        handle.close = original
        await manager.delete(created["session_id"])
        assert handle.closed and not manager.sessions
    asyncio.run(exercise())


def test_expiry_retries_failed_close_and_still_closes_other_sessions():
    async def exercise():
        now = [datetime(2026, 10, 23, tzinfo=timezone.utc)]
        engine = Engine()
        manager = SessionManager(Settings(TOKEN, max_sessions=2), engine=engine, clock=lambda: now[0])
        first = await manager.create(idempotency_key="one", url="https://example.com")
        second = await manager.create(idempotency_key="two", url="https://example.com")
        original = engine.handles[0].close
        async def fail_close():
            raise OSError("browser close failed")
        engine.handles[0].close = fail_close
        now[0] += timedelta(seconds=601)
        await manager.expire()
        assert first["session_id"] in manager.sessions
        assert second["session_id"] not in manager.sessions and engine.handles[1].closed
        engine.handles[0].close = original
        await manager.expire()
        assert not manager.sessions and engine.handles[0].closed
    asyncio.run(exercise())


def test_cancel_unknown_key_fences_delayed_creation_and_requires_authentication():
    engine = Engine()
    with TestClient(create_app(Settings(TOKEN), engine=engine)) as client:
        assert client.delete("/session-keys/request:1").status_code == 401
        assert client.delete("/session-keys/request:1", headers=HEADERS).json() == {"closed": True}
        response = new_session(client)
        assert response.status_code == 409 and response.json()["error"] == "session_cancelled"
        assert not engine.handles
        assert client.delete("/session-keys/request:1", headers=HEADERS).json() == {"closed": True}


def test_cancel_inflight_creation_closes_browser_before_acknowledging():
    async def exercise():
        opened, release = asyncio.Event(), asyncio.Event()
        class SlowEngine(Engine):
            async def open(self, url, state):
                handle = await super().open(url, state)
                opened.set()
                await release.wait()
                return handle
        engine = SlowEngine()
        manager = SessionManager(Settings(TOKEN), engine=engine)
        creation = asyncio.create_task(manager.create(idempotency_key="one", url="https://example.com"))
        await opened.wait()
        cancellation = asyncio.create_task(manager.cancel_key("one"))
        await asyncio.sleep(0)
        assert not cancellation.done() and not engine.handles[0].closed
        release.set()
        with pytest.raises(BrowserError, match="session_cancelled"):
            await creation
        await cancellation
        assert engine.handles[0].closed and not manager.sessions
        with pytest.raises(BrowserError, match="session_cancelled"):
            await manager.create(idempotency_key="one", url="https://example.com")
    asyncio.run(exercise())
