"""Integration fixtures for E11-2: the real create_app + TestClient with seeded fixture sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from aicl.app import FIXTURE_CSRF_TOKEN, FIXTURE_OWNERS, create_app
from aicl.control.auth import AuthContext
from aicl.settings import Settings


def owner_auth(fixture: str) -> AuthContext:
    owner = FIXTURE_OWNERS[fixture]
    return AuthContext(owner, owner, f"s-{fixture}", datetime(2100, 1, 1, tzinfo=timezone.utc))


@dataclass
class Web:
    app: object
    owner_a: TestClient
    owner_b: TestClient
    auth_a: AuthContext
    auth_b: AuthContext

    def tool(self, client: TestClient, name: str, body: dict):
        origin = self.app.state.ctx.settings.public_base_url
        return client.post(f"/app-tools/{name}", json=body,
                           headers={"x-csrf-token": FIXTURE_CSRF_TOKEN, "origin": origin})


@pytest.fixture
def web(base_env, tmp_path):
    settings = Settings.from_env({**base_env, "AICL_ENVIRONMENT": "test", "AICL_TEST_MODE": "1",
                                  "AICL_DATABASE_URL": f"sqlite:///{tmp_path / 'web.db'}"})
    app = create_app(settings)
    with TestClient(app) as a, TestClient(app) as b:
        assert a.post("/__test__/seed-session", json={"fixture": "owner-a"}).status_code == 200
        assert b.post("/__test__/seed-session", json={"fixture": "owner-b"}).status_code == 200
        yield Web(app, a, b, owner_auth("owner-a"), owner_auth("owner-b"))
