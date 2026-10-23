"""Owner responses exercise real routes, CSRF, saved state and checkout return."""
from dataclasses import replace

from fastapi.testclient import TestClient

from aicl.app import FIXTURE_CSRF_TOKEN, create_app
from aicl.owner_requests.service import OwnerRequestService
from aicl.ports import build_ports
from aicl.settings import Settings
from test_owner_requests import request_env, ask
from test_pocketplan_workflow import prepared, tick


def application(env, auth, base_env):
    settings = Settings.from_env({**base_env, "AICL_ENVIRONMENT": "test", "AICL_TEST_MODE": "1",
                                  "AICL_DATABASE_URL": env.db.database_url})
    ports = build_ports(settings).model_copy(update={"clock": env.clock})
    app = create_app(settings, ports)
    app.state.ctx.auth_provider.contexts["owner"] = auth
    app.state.ctx.auth_provider.contexts["other"] = replace(auth, owner_id="other", tenant_id="other", session_id="other")
    app.state.ctx.csrf_verifier.fixture_session_ids |= {auth.session_id, "other"}
    return app, {"origin": settings.public_base_url}


def test_inbox_response_is_scoped_csrf_protected_and_persists_in_same_job(build_env, base_env):
    env, _, _, auth, inst, service, job = request_env(build_env)
    item = ask(service, auth, inst, job)
    app, headers = application(env, auth, base_env)
    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/requests").status_code == 303
        client.cookies.set("aicl_session", "owner")
        page = client.get("/requests", params={"selected": item["id"]})
        assert page.status_code == 200 and "Who should this campaign reach?" in page.text
        assert job["id"] in page.text and "Choose the audience" in client.get("/workspace").text
        assert client.get("/requests/summary").json() == {"pending_count": 1}
        path = f"/requests/{item['id']}/respond"
        fields = {"expected_version": "1", "answer": "Puzzle players", "decision": "answer", "continuation": "schedule"}
        assert client.post(path, data=fields, headers=headers).status_code == 403
        fields["csrf_token"] = FIXTURE_CSRF_TOKEN
        client.cookies.set("aicl_session", "other")
        assert client.post(path, data=fields, headers=headers).status_code == 404
        assert client.get("/requests", params={"selected": item["id"]}).status_code == 404
        client.cookies.set("aicl_session", "owner")
        saved = client.post(path, data=fields, headers=headers)
        assert saved.status_code == 303
        history = client.get(saved.headers["location"])
        assert history.status_code == 200 and "Puzzle players" in history.text
        assert client.get("/requests/summary").json() == {"pending_count": 0}
        stale = client.post(path, data={**fields, "answer": "Changed answer"}, headers=headers)
        assert "error=" in stale.headers["location"]
        assert service.get(auth, item["id"])["response"]["answer"] == "Puzzle players"


def test_purchase_stays_one_request_through_approval_checkout_and_verified_return(build_env, base_env):
    env, workflow, commerce, auth, inst, _ = prepared(build_env)
    purchase = tick(workflow, auth, inst.id)["purchases"][0]
    requests = OwnerRequestService(workflow)
    item = requests.get(auth, "purchase:" + purchase["id"])
    app, headers = application(env, auth, base_env)
    with TestClient(app, follow_redirects=False) as client:
        client.cookies.set("aicl_session", "owner")
        page = client.get("/requests", params={"selected": item["id"]})
        assert page.status_code == 200 and 'name="expected_version"' in page.text
        assert "Changes need a new approval." in page.text
        for source in purchase["source_work"]:
            assert f'/audit/deliverables/{source["deliverable_id"]}' in page.text
        fields = {"csrf_token": FIXTURE_CSRF_TOKEN, "expected_version": item["version"],
                  "quote_digest": purchase["quote_digest"], "decision": "approve", "continuation": "schedule"}
        path = f"/requests/{item['id']}/decision"
        approved = client.post(path, data=fields, headers=headers)
        assert approved.status_code == 303 and approved.headers["location"].startswith("/commerce/orders/")
        assert requests.get(auth, item["id"])["status"] == "pending"
        assert requests.get(auth, item["id"])["stage"] == "awaiting_checkout"
        assert "error=" in client.post(path, data={**fields, "continuation": "now"}, headers=headers).headers["location"]
        order = commerce.purchase(auth, purchase["id"])["order_id"]
        checkout = client.get(f"/commerce/orders/{order}")
        assert "Back to this request" in checkout.text
        result = client.post(f"/commerce/orders/{order}/checkout", headers=headers,
                             data={"csrf_token": FIXTURE_CSRF_TOKEN, "outcome": "complete", "buyer_id": "demo-buyer"})
        assert result.status_code == 303 and result.headers["location"].startswith("/requests?")
        assert requests.get(auth, item["id"])["status"] == "resolved"
        receipt = client.get(result.headers["location"])
        assert receipt.status_code == 200 and "Payment completed" in receipt.text


def test_authentication_is_visible_without_credential_collection_or_false_success(build_env, base_env):
    env, _, _, auth, inst, service, job = request_env(build_env)
    item = service.create(auth, inst.id, job["id"], "authentication", "Sign-in required", "Prepare an ad draft",
                          details={"domain": "ads.snapchat.com", "requested_access": "Prepare drafts"}, dedupe_key="login")
    app, headers = application(env, auth, base_env)
    with TestClient(app, follow_redirects=False) as client:
        client.cookies.set("aicl_session", "owner")
        page = client.get("/requests", params={"selected": item["id"]})
        assert page.status_code == 200 and "ads.snapchat.com" in page.text
        assert 'disabled aria-describedby="requests-signin-unavailable"' in page.text
        assert 'type="password"' not in page.text
        result = client.post(f"/requests/{item['id']}/respond", headers=headers,
                             data={"csrf_token": FIXTURE_CSRF_TOKEN, "expected_version": "1", "decision": "approve"})
        assert "error=" in result.headers["location"]
        assert service.get(auth, item["id"])["status"] == "pending"
