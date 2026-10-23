"""Browser evidence reaches owner approval without payment authority or checkout."""
from dataclasses import replace
import uuid

import pytest
from fastapi.testclient import TestClient

from aicl.app import FIXTURE_CSRF_TOKEN
from aicl.browser.proposals import BrowserPurchaseProposalService
from aicl.control.errors import AiclError
from aicl.owner_requests.service import OwnerRequestService
from test_owner_request_pages import application
from test_owner_requests import request_env, rejection


def payload():
    return {"seller": "Example Ads", "domain": "ads.example.com", "amount_minor": 1500,
            "currency": "USD", "description": "A three-day mobile game advertising test",
            "rationale": "Compare puzzle-game creatives before expanding the campaign budget.",
            "evidence": [{"url": "https://ads.example.com/campaigns", "title": "Campaign workspace",
                          "excerpt": "Advertising workspace for the owner's mobile game."}]}


def setup(build_env):
    env, workflow, commerce, auth, inst, _, job = request_env(build_env)
    # The trusted inference settlement submits the source deliverable before
    # constructing its owner-reviewed purchase proposal.
    with env.db.transaction() as conn:
        conn.execute("UPDATE mock_workflow_deliverable SET state='submitted' WHERE workflow_run_id=?", (job["id"],))
        conn.execute("UPDATE mock_workflow_run SET state='submitted' WHERE id=?", (job["id"],))
    return env, workflow, commerce, auth, inst, job, BrowserPurchaseProposalService(workflow)


def test_browser_proposal_is_immutable_durable_owned_and_idempotent(build_env):
    env, workflow, _, auth, inst, job, service = setup(build_env)
    first = service.propose(auth, job["id"], payload())
    assert first["state"] == "pending" and first["version"] == 1
    restarted = BrowserPurchaseProposalService(workflow)
    assert restarted.propose(auth, job["id"], payload()) == first
    rejection("conflict", lambda: service.propose(auth, job["id"], {**payload(), "amount_minor": 1600}))
    stranger, _ = env.new_instance()
    for identity in (stranger, replace(auth, tenant_id=stranger.tenant_id)):
        assert service.list(identity) == []
        rejection("not_found", lambda: service.get(identity, first["id"]))
        rejection("not_found", lambda: service.decide(identity, first["id"], "approve", 1))
        rejection("not_found", lambda: service.propose(identity, job["id"], payload()))
    inbox = OwnerRequestService(workflow)
    item, = inbox.list(auth, kind="purchase")
    assert item["id"] == "browser-purchase:" + first["id"]
    assert item["job_id"] == job["id"] and item["proposal"]["evidence"] == payload()["evidence"]
    assert item["order_id"] is None and item["purchase_id"] is None


def test_proposal_decision_checks_current_controls_and_never_pays_or_resumes(build_env):
    env, workflow, _, auth, inst, job, service = setup(build_env)
    first = service.propose(auth, job["id"], payload())
    before = workflow.job(auth, job["id"])["state"]
    with env.db.transaction() as conn:
        conn.execute("UPDATE mock_commerce_account SET purchase_enabled=0 WHERE instance_id=?", (inst.id,))
    rejection("denied", lambda: service.decide(auth, first["id"], "approve", 1))
    assert service.get(auth, first["id"])["state"] == "pending"
    with env.db.transaction() as conn:
        conn.execute("UPDATE mock_commerce_account SET purchase_enabled=1 WHERE instance_id=?", (inst.id,))
        orders_before = conn.execute("SELECT COUNT(*) FROM mock_commerce_order").fetchone()[0]
    approved = service.decide(auth, first["id"], "approve", 1)
    assert approved["state"] == "approved" and approved["version"] == 2
    rejection("conflict", lambda: service.decide(auth, first["id"], "decline", 1))
    assert workflow.job(auth, job["id"])["state"] == before
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM mock_commerce_order").fetchone()[0] == orders_before
        assert conn.execute("SELECT COUNT(*) FROM mock_commerce_purchase").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM audit_event WHERE json_extract(details,'$.confirmation_id')=?", (first["id"],)).fetchone()[0] == 2
    assert OwnerRequestService(workflow).list(auth) == []


def test_invalid_or_over_allowance_proposals_fail_closed_and_decline_is_always_available(build_env):
    env, _, _, auth, inst, job, service = setup(build_env)
    for change in ({"amount_minor": True}, {"amount_minor": 2001}, {"currency": "EUR"},
                   {"evidence": []}, {"domain": "127.0.0.1"},
                   {"evidence": [{"url": "https://ads.example.com/?token=secret", "title": "X", "excerpt": "Y"}]}):
        with pytest.raises(AiclError):
            service.propose(auth, job["id"], {**payload(), **change})
    first = service.propose(auth, job["id"], payload())
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_instance SET lifecycle='paused' WHERE id=?", (inst.id,))
    assert service.decide(auth, first["id"], "decline", 1)["state"] == "declined"


def test_browser_proposal_inbox_uses_owner_csrf_version_and_has_no_checkout(build_env, base_env):
    env, workflow, _, auth, _, job, service = setup(build_env)
    proposal = service.propose(auth, job["id"], payload())
    request_id = "browser-purchase:" + proposal["id"]
    app, headers = application(env, auth, base_env)
    with TestClient(app, follow_redirects=False) as client:
        client.cookies.set("aicl_session", "owner")
        page = client.get("/requests", params={"selected": request_id})
        assert page.status_code == 200 and "Proposed purchase" in page.text
        assert "Proposed budget" in page.text and "Browser evidence" in page.text
        assert job["id"] in page.text and "Stops before checkout" in page.text
        assert "/commerce/orders/" not in page.text and "After verified payment" not in page.text
        fields = {"expected_version": "1", "decision": "approve"}
        path = f"/requests/{request_id}/decision"
        assert client.post(path, data=fields, headers=headers).status_code == 403
        fields["csrf_token"] = FIXTURE_CSRF_TOKEN
        client.cookies.set("aicl_session", "other")
        assert client.post(path, data=fields, headers=headers).status_code == 404
        client.cookies.set("aicl_session", "owner")
        saved = client.post(path, data=fields, headers=headers)
        assert saved.status_code == 303 and saved.headers["location"].startswith("/requests?")
        assert "No payment was made" in client.get(saved.headers["location"]).text
        assert "error=" in client.post(path, data=fields, headers=headers).headers["location"]
        assert OwnerRequestService(workflow).get(auth, request_id)["stage"] == "approved"


def test_revision_supersedes_old_proposal_and_approval_binds_exact_submitted_output(build_env):
    env, workflow, _, auth, _, job, service = setup(build_env)
    original = service.propose(auth, job["id"], payload())
    with env.db.transaction() as conn:
        source = conn.execute("SELECT * FROM mock_workflow_deliverable WHERE workflow_run_id=?", (job["id"],)).fetchone()
        conn.execute("UPDATE mock_workflow_deliverable SET state='changes_requested' WHERE id=?", (source["id"],))
    rejection("conflict", lambda: service.decide(auth, original["id"], "approve", 1))
    service.invalidate(auth, job["id"])
    assert service.get(auth, original["id"])["state"] == "superseded"
    next_id = str(uuid.uuid4())
    with env.db.transaction() as conn:
        conn.execute("INSERT INTO mock_workflow_deliverable(id,workflow_run_id,version,content,criteria_json,state,created_at) "
                     "VALUES (?,?,2,?,?,'submitted',?)", (next_id, job["id"], "Revised proposal", source["criteria_json"], source["created_at"]))
    revised = service.propose(auth, job["id"], {**payload(), "amount_minor": 1600})
    assert revised["id"] != original["id"] and revised["deliverable_id"] == next_id
    assert service.propose(auth, job["id"], {**payload(), "amount_minor": 1600})["id"] == revised["id"]
    inbox = OwnerRequestService(workflow)
    previous = inbox.get(auth, "browser-purchase:" + original["id"])
    assert previous["proposal"]["source_deliverable"]["id"] == source["id"]
    assert previous["status"] != "pending" and len(inbox.list(auth)) == 1
    service.decide(auth, revised["id"], "approve", 1)
    rejection("invalid_transition", lambda: service.invalidate(auth, job["id"]))
