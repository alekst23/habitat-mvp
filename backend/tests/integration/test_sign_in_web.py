"""E11-3 HTTP proofs through the real create_app (F3-S2, F3-S3 wizard half, F3-S5 wizard creation, F3-S8):
generic 202 for known/unknown emails, real magic-link sign-in with cookie flags, logout invalidation, wizard
creation through create_instance(surface="wizard"), ignored client tenant, cross-tenant not_found. Only the email
edge is fake (captured link); the session is the real one, not the seeded fixture session."""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from aicl.app import create_app
from aicl.settings import Settings

KEY = "wiz_" + "a" * 32
LINK_TOKEN = re.compile(r"token=([A-Za-z0-9_-]{20,})")


@pytest.fixture
def real_app(base_env, tmp_path):
    settings = Settings.from_env({**base_env, "AICL_ENVIRONMENT": "test", "AICL_TEST_MODE": "1",
                                  "AICL_DATABASE_URL": f"sqlite:///{tmp_path / 'auth.db'}"})
    return create_app(settings)


def sign_in(app, client: TestClient, email: str) -> None:
    sent = client.post("/auth/magic-link", data={"email": email})
    assert sent.status_code == 202, sent.text
    captured = client.get("/__test__/last-magic-link", params={"email": email})
    assert captured.status_code == 200, captured.text
    token = LINK_TOKEN.search(captured.text).group(1)
    client.get("/auth/verify", params={"token": token})  # GET only renders a form: it must not consume the link
    done = client.post("/auth/verify", data={"token": token}, follow_redirects=False)
    assert done.status_code in (200, 302, 303), done.text


def csrf_headers(app, client: TestClient) -> dict:
    ctx = app.state.ctx
    auth = ctx.auth_provider.resolve(dict(client.cookies))
    assert auth is not None
    return {"x-csrf-token": ctx.csrf_verifier.token_for(auth.session_id), "origin": ctx.settings.public_base_url}


@pytest.mark.ac("E11-3.AC1", code="backend/aicl/auth/session.py:SessionAuthProvider")
def test_real_sign_in_is_generic_sets_safe_cookie_and_logout_invalidates_it(real_app):
    with TestClient(real_app) as known, TestClient(real_app) as visitor:
        sign_in(real_app, known, "Known@Example.com")
        assert known.get("/workspace", follow_redirects=False).status_code == 200

        # identical status and body for a known and an unknown address (no existence leak)
        again = known.post("/auth/magic-link", data={"email": "known@example.com"})
        unknown = visitor.post("/auth/magic-link", data={"email": "nobody@example.com"})
        invalid = visitor.post("/auth/magic-link", data={"email": "not-an-email"})
        assert again.status_code == unknown.status_code == invalid.status_code == 202
        assert again.text == unknown.text == invalid.text
        assert "a link is on its way" in again.text

    with TestClient(real_app) as owner:
        owner.post("/auth/magic-link", data={"email": "cookie@example.com"})
        token = LINK_TOKEN.search(owner.get("/__test__/last-magic-link", params={"email": "cookie@example.com"}).text).group(1)
        signed = owner.post("/auth/verify", data={"token": token}, follow_redirects=False)
        header = " ".join(signed.headers.get_list("set-cookie")).lower()
        assert "aicl_session=" in header and "httponly" in header and "samesite=lax" in header
        assert "max-age=28800" in header and "path=/" in header and "secure" not in header  # test mode only
        cookie_value = owner.cookies.get("aicl_session")
        assert owner.post("/auth/logout", headers=csrf_headers(real_app, owner)).status_code in (200, 302, 303)
        with TestClient(real_app) as replay:  # the old cookie no longer resolves server-side
            replay.cookies.set("aicl_session", cookie_value)
            assert replay.get("/workspace", follow_redirects=False).status_code in (302, 303, 307)


@pytest.mark.ac("E11-3.AC1", code="backend/aicl/creation/service.py:create_instance")
def test_wizard_creates_a_draft_through_the_canonical_service_and_ignores_client_tenant(real_app):
    with TestClient(real_app) as owner_a, TestClient(real_app) as owner_b:
        sign_in(real_app, owner_a, "wizard-a@example.com")
        sign_in(real_app, owner_b, "wizard-b@example.com")
        form = {"idempotency_key": KEY, "name": "Helper", "instructions": "be kind", "capabilities": ["inference"],
                "tenant_id": "00000000-0000-4000-8000-00000000dead", "owner_id": "evil"}
        headers = csrf_headers(real_app, owner_a)
        assert owner_a.post("/agents/new", data=form, headers={"origin": headers["origin"]}).status_code == 403  # CSRF
        created = owner_a.post("/agents/new", data=form, headers=headers)
        assert created.status_code == 200 and "not active until you activate it" in created.text

        auth_a = real_app.state.ctx.auth_provider.resolve(dict(owner_a.cookies))
        with real_app.state.ctx.db.reader() as conn:
            inst = conn.execute("SELECT id, tenant_id, owner_id, lifecycle FROM agent_instance WHERE name = 'Helper'").fetchall()
            assert len(inst) == 1 and inst[0]["lifecycle"] == "draft"
            assert inst[0]["tenant_id"] == inst[0]["owner_id"] == auth_a.owner_id  # derived from the session, not the form
            surface = conn.execute("SELECT details FROM audit_event WHERE event_type = 'instance.created'").fetchone()
            assert json.loads(surface["details"])["surface"] == "wizard"

        denied = owner_a.post("/agents/new", data={**form, "idempotency_key": "wiz_" + "b" * 32, "name": "   "},
                              headers=headers)  # field error denial, nothing created
        assert denied.status_code in (200, 422) and "name" in denied.text
        with real_app.state.ctx.db.reader() as conn:
            assert conn.execute("SELECT count(*) FROM agent_instance").fetchone()[0] == 1

        origin = real_app.state.ctx.settings.public_base_url  # another tenant cannot read it: not_found
        read = owner_b.post("/app-tools/read_instance", json={"instance_id": inst[0]["id"]},
                            headers={**csrf_headers(real_app, owner_b), "origin": origin})
        assert read.status_code == 404 and read.json()["error"] == "not_found"
        assert "Helper" in owner_a.get("/workspace").text and "Helper" not in owner_b.get("/workspace").text
