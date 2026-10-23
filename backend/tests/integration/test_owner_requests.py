"""Durable owner inbox: isolation, exact decisions and canonical purchase state."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier

import pytest

from aicl.control.errors import AiclError
from aicl.owner_requests.service import OwnerRequestService
from test_scheduled_owner_workflow import prepared, spec, tick


def request_env(build_env):
    env, workflow, commerce, auth, inst, ops = prepared(build_env, spec(validation="needs_work_once"))
    view, _ = tick(workflow, auth, inst.id)
    return env, workflow, commerce, auth, inst, OwnerRequestService(workflow), view["runs"][0]


def ask(service, auth, inst, job, key="audience", **kwargs):
    return service.create(auth, inst.id, job["id"], "clarification", "Choose the audience", "A focused audience is needed before preparing the campaign.",
                          details={"question": "Who should this campaign reach?", "options": ["Puzzle players", "Strategy players"]}, dedupe_key=key, **kwargs)


def rejection(code, action):
    with pytest.raises(AiclError) as caught:
        action()
    assert caught.value.error == code
    return caught.value


def test_request_survives_reconstruction_and_deduplicates_without_reopening(build_env):
    env, workflow, _, auth, inst, service, job = request_env(build_env)
    first = ask(service, auth, inst, job, continuation="schedule")
    assert first["status"] == "pending" and first["version"] == 1
    assert first["job_state"] == "waiting_owner" and first["paused_state"] == "needs_work"
    assert ask(service, auth, inst, job)["id"] == first["id"]
    restored = OwnerRequestService(workflow)
    assert restored.pending_count(auth) == 1
    answered = restored.respond(auth, first["id"], 1, decision="answer", answer="Casual puzzle players", continuation="schedule")
    assert answered["status"] == "resolved" and answered["version"] == 2
    assert restored.pending_count(auth) == 0
    replay = ask(service, auth, inst, job)
    assert replay["status"] == "resolved" and replay["version"] == 2
    assert len(restored.list(auth, status="all")) == 1
    with env.db.reader() as conn:
        answers = service.answers_for_job(conn, job["id"])
        assert answers[0]["answer"] == "Casual puzzle players"
        assert len(conn.execute("SELECT * FROM audit_event WHERE json_extract(details,'$.confirmation_id')=?", (first["id"],)).fetchall()) == 2
    assert "Casual puzzle players" not in workflow.config(auth, inst.id)["inputs"]


def test_requests_reject_wrong_owner_tenant_and_instance_and_expired_session(build_env):
    env, _, _, auth, inst, service, job = request_env(build_env)
    first = ask(service, auth, inst, job)
    stranger, other_inst = env.new_instance()
    assert service.list(stranger, status="all") == []
    for identity in (stranger, replace(auth, tenant_id=stranger.tenant_id)):
        rejection("not_found", lambda: service.get(identity, first["id"]))
        rejection("not_found", lambda: service.respond(identity, first["id"], 1, answer="Private answer"))
    rejection("not_found", lambda: service.create(stranger, other_inst.id, job["id"], "clarification", "Title", "Reason", dedupe_key="cross-job"))
    expired = replace(auth, expires_at=env.clock.now() - timedelta(seconds=1))
    rejection("unauthenticated", lambda: service.list(expired))
    rejection("unauthenticated", lambda: service.get(expired, first["id"]))
    assert service.get(auth, first["id"])["status"] == "pending"


def test_conflicting_replay_blank_answer_and_stale_concurrent_response_fail_closed(build_env):
    env, _, _, auth, inst, service, job = request_env(build_env)
    first = ask(service, auth, inst, job)
    rejection("conflict", lambda: service.create(auth, inst.id, job["id"], "clarification", "Different question", "Different reason", dedupe_key="audience"))
    rejection("validation_failed", lambda: service.respond(auth, first["id"], 1, answer="   "))
    rejection("validation_failed", lambda: service.respond(auth, first["id"], True, answer="Answer"))
    barrier = Barrier(2)
    def respond(answer):
        barrier.wait()
        try:
            return service.respond(auth, first["id"], 1, answer=answer, continuation="schedule")["status"]
        except AiclError as error:
            return error.error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(respond, ("Puzzle players", "Strategy players")))
    assert sorted(results) == ["conflict", "resolved"]
    with env.db.reader() as conn:
        assert len(service.answers_for_job(conn, job["id"])) == 1


def test_authentication_has_no_owner_success_path_or_external_redirect(build_env):
    _, _, _, auth, inst, service, job = request_env(build_env)
    for details in ({"domain": "https://evil.example/?token=secret"}, {"domain": "127.0.0.1"},
                    {"domain": "login.example", "login_url": "https://evil.example"}, {"domain": "foo.local"}):
        rejection("validation_failed", lambda: service.create(auth, inst.id, job["id"], "authentication", "Sign in", "Prepare a campaign", details=details, dedupe_key="login"))
    login = service.create(auth, inst.id, job["id"], "authentication", "Sign-in required", "Prepare a campaign draft", details={"domain": "ads.snapchat.com", "requested_access": "Prepare drafts"}, dedupe_key="login")
    assert login["capability"] == "unavailable" and login["details"]["domain"] == "ads.snapchat.com"
    for decision in ("approve", "complete", "answer"):
        rejection("unavailable", lambda: service.respond(auth, login["id"], 1, decision=decision, answer="I am signed in"))
    assert service.get(auth, login["id"])["status"] == "pending"
    declined = service.respond(auth, login["id"], 1, decision="decline")
    assert declined["status"] == "declined" and declined["job_state"] == "owner_declined"


def test_permission_response_is_scoped_and_does_not_change_instance_controls(build_env):
    env, workflow, _, auth, inst, service, job = request_env(build_env)
    with env.db.reader() as conn:
        before = dict(workflow._instance(conn, auth, inst.id))
    permission = service.create(auth, inst.id, job["id"], "permission", "May I prepare this draft?", "A draft supports the campaign proposal.",
                                details={"action": "Prepare an unpublished campaign draft", "scope": "This campaign proposal only; no publishing or spending"}, dedupe_key="draft")
    approved = service.respond(auth, permission["id"], 1, decision="approve", continuation="schedule")
    assert approved["response"]["scope"].endswith("no publishing or spending")
    with env.db.reader() as conn:
        assert dict(workflow._instance(conn, auth, inst.id)) == before


def test_purchase_is_one_read_through_request_through_approval_checkout_and_payment(build_env):
    env, workflow, commerce, auth, inst, _ = prepared(build_env, spec(purchase=True))
    view, _ = tick(workflow, auth, inst.id)
    purchase = view["purchases"][0]
    service = OwnerRequestService(workflow)
    first = service.get(auth, "purchase:" + purchase["id"])
    assert first["stage"] == "awaiting_approval" and first["job_id"]
    assert first["purchase"]["source_job"]["id"] == first["job_id"]
    approved = commerce.decide_purchase(auth, purchase["id"], "approve", purchase["quote_digest"])
    second = service.get(auth, first["id"])
    assert second["id"] == first["id"] and second["version"] != first["version"]
    assert second["status"] == "pending" and second["stage"] == "awaiting_checkout"
    commerce.checkout(auth, approved["order_id"], "complete")
    paid = service.get(auth, first["id"])
    assert paid["status"] == "resolved" and paid["stage"] == "paid"
    assert service.list(auth) == []
    assert len(service.list(auth, status="all", kind="purchase")) == 1
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM owner_request").fetchone()[0] == 0


def test_concurrent_creation_is_one_durable_request_and_one_audit_event(build_env):
    env, _, _, auth, inst, service, job = request_env(build_env)
    barrier = Barrier(2)
    def create(_):
        barrier.wait()
        return ask(service, auth, inst, job)["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(create, (1, 2)))
    assert ids[0] == ids[1] and service.pending_count(auth) == 1
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_event WHERE json_extract(details,'$.confirmation_id')=?", (ids[0],)).fetchone()[0] == 1


def test_multiple_requests_cannot_resume_until_all_responses_and_decline_stays_blocked(build_env):
    env, workflow, _, auth, inst, service, job = request_env(build_env)
    first = ask(service, auth, inst, job)
    second = ask(service, auth, inst, job, key="audience-second")
    assert second["paused_state"] == first["paused_state"] == "needs_work"
    resumed = []
    workflow.owner_request_resolved = lambda *args: resumed.append(args)
    service.respond(auth, first["id"], 1, answer="Puzzle players", continuation="now")
    assert resumed == []
    assert service.get(auth, second["id"])["job_state"] == "waiting_owner"
    service.respond(auth, second["id"], 1, decision="decline")
    assert resumed == []
    assert service.get(auth, first["id"])["job_state"] == "owner_declined"
    with env.db.reader() as conn:
        assert len(service.answers_for_job(conn, job["id"])) == 1


def test_answer_persists_when_current_schedule_control_prevents_continuation(build_env):
    _, workflow, _, auth, inst, service, job = request_env(build_env)
    first = ask(service, auth, inst, job)
    workflow.schedule(auth, inst.id, False)
    result = service.respond(auth, first["id"], 1, answer="Puzzle players", continuation="now")
    assert result["status"] == "resolved" and result["response"]["answer"] == "Puzzle players"
    job_view = workflow.job(auth, job["id"])
    assert job_view["state"] == "waiting_owner"
    assert "Enable the agent schedule" in job_view["blocked_reason"]
