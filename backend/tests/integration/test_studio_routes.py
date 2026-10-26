"""Studio layouts are owner-scoped; reads and saves never dispatch work."""
from fastapi.testclient import TestClient

from aicl.app import create_app
from aicl.settings import Settings


def test_studio_auth_layout_conflicts_and_owner_isolation(base_env):
    settings = Settings.from_env({**base_env, "AICL_ENVIRONMENT": "test", "AICL_TEST_MODE": "1"})
    with TestClient(create_app(settings), base_url="http://127.0.0.1:4173") as client:
        assert client.get("/audit/studio", follow_redirects=False).status_code == 303
        assert client.get("/audit/studio/data").status_code == 401
        seed = client.post("/__test__/seed-session", json={"fixture": "owner-a"}).json()
        headers = {"X-CSRF-Token": seed["csrf_token"], "Origin": "http://127.0.0.1:4173"}
        assert client.get("/audit/studio").status_code == 200
        assert client.get("/audit/studio/state").json() == {"state": None, "version": 0}
        state = {"version": "3.0.0", "pages": []}
        body = {"state": state, "expected_version": 0}
        assert client.put("/audit/studio/state", json=body).status_code == 403
        saved = client.put("/audit/studio/state", json=body, headers=headers)
        assert saved.status_code == 200, saved.text
        assert saved.json()["version"] == 1
        assert client.put("/audit/studio/state", json=body, headers=headers).status_code == 409
        assert client.get("/audit/studio/state").json()["state"] == state
        client.post("/__test__/seed-session", json={"fixture": "owner-b"})
        assert client.get("/audit/studio/state").json() == {"state": None, "version": 0}
        assert client.get("/audit/studio/data").json()["costs"] == []
        assert client.post("/audit/studio/ai", json={}, headers=headers).status_code == 503
        with client.app.state.ctx.db.reader() as conn:
            assert conn.execute("SELECT count(*) FROM workflow_inference_attempt").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM mock_commerce_order").fetchone()[0] == 0


def test_studio_rejects_bad_state_and_query_before_saving(base_env):
    settings = Settings.from_env({**base_env, "AICL_ENVIRONMENT": "test", "AICL_TEST_MODE": "1"})
    with TestClient(create_app(settings), base_url="http://127.0.0.1:4173") as client:
        seed = client.post("/__test__/seed-session", json={"fixture": "owner-a"}).json()
        headers = {"X-CSRF-Token": seed["csrf_token"], "Origin": "http://127.0.0.1:4173"}
        for state in ([], {"nested": "x" * 262145}, {"__proto__": {"polluted": True}}):
            assert client.put("/audit/studio/state", json={"state": state, "expected_version": 0}, headers=headers).status_code == 422
        assert client.get("/audit/studio/data?date_from=2026-10-30&date_to=2026-10-01").status_code == 422
        assert client.get("/audit/studio/data?timezone=not-a-zone").status_code == 422
        assert client.get("/audit/studio/state").json()["version"] == 0
