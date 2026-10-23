"""Purchase evidence remains connected across Requests, source job and Audit."""
import json

from fastapi.testclient import TestClient

from test_browser_purchase_proposals import setup, payload
from test_owner_request_pages import application


def test_browser_proposal_is_visible_in_source_job_audit_and_deliverable(build_env, base_env):
    env, workflow, _, auth, inst, job, proposals = setup(build_env)
    with env.db.transaction() as conn:
        raw = conn.execute("SELECT config_json FROM mock_workflow_run WHERE id=?", (job["id"],)).fetchone()[0]
        snapshot = json.loads(raw)
        snapshot["scenario"] = "browser_purchase"
        conn.execute("UPDATE mock_workflow_run SET config_json=? WHERE id=?", (json.dumps(snapshot), job["id"]))
    proposal = proposals.propose(auth, job["id"], payload())
    source = workflow.job(auth, job["id"])
    item, = source["purchases"]
    assert item["kind"] == "browser_proposal" and item["id"] == proposal["id"]
    assert item["source_job"]["id"] == source["id"]
    overview = workflow.overview(auth, inst.id)
    assert overview["agents"][0]["pending_purchase_count"] == 1
    assert overview["purchases"][0]["id"] == proposal["id"]
    assert overview["totals"]["purchase_held_minor"] == 0
    app, _ = application(env, auth, base_env)
    with TestClient(app) as client:
        client.cookies.set("aicl_session", "owner")
        page = client.get("/audit/jobs/" + job["id"])
        assert page.status_code == 200
        assert "This job has no purchase requests" not in page.text
        assert "1 request" in page.text and "Proposed budget" in page.text
        assert "browser-purchase%3A" + proposal["id"] in page.text
        assert "/commerce/orders/" not in page.text
        audit = client.get("/audit", params={"view": "purchases", "instance_id": inst.id, "status": "pending"})
        assert audit.status_code == 200
        assert payload()["description"] in audit.text and "No purchase requests" not in audit.text
        assert "View source job" in audit.text and "No checkout" in audit.text
        output = client.get("/audit/deliverables/" + source["deliverables"][0]["id"])
        assert output.status_code == 200
        assert "Browser evidence informs this proposal" in output.text
        assert "Advertising delivery and metrics remain scenario data" not in output.text
        assert "browser-purchase%3A" + proposal["id"] in output.text
    proposals.decide(auth, proposal["id"], "approve", 1)
    assert workflow.overview(auth, inst.id)["agents"][0]["pending_purchase_count"] == 0
    assert workflow.job(auth, job["id"])["purchases"][0]["proposal_state"] == "approved"
