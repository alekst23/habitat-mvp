"""Browser handoff lifecycle with the real database, encryption and request controls."""
import base64
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace

import pytest

from aicl.browser.client import BrowserClient
from aicl.browser.service import BrowserBroker
from aicl.connections.ports import AesGcmSecretStore, SecretUnavailable
from aicl.control.errors import AiclError
from aicl.owner_requests.service import OwnerRequestService
from aicl.settings import Settings, SettingsError
from support import historical_budget_fixture
from test_owner_requests import request_env, rejection


COOKIE = "private-account-cookie-do-not-log"


class Runtime:
    def __init__(self, db):
        self.db, self.sessions, self.closed, self.creates = db, {}, [], []
        self.fail_close = False
        self.on_page = None

    def outside_transaction(self):
        assert getattr(self.db._local, "conn", None) is None, "HTTP while holding the SQLite transaction"

    def create(self, **payload):
        self.outside_transaction()
        self.creates.append(payload)
        session_id = payload["idempotency_key"]
        self.sessions[session_id] = payload
        return {"session_id": session_id, "url": payload["url"]}

    def frame(self, session_id):
        self.outside_transaction()
        return {"image": base64.b64encode(b"fixture JPEG").decode(), "width": 1280, "height": 720,
                "url": "https://login.example/account/secret-code?code=oauth-secret#fragment", "title": "Sensitive title"}

    def input(self, session_id, payload):
        self.outside_transaction()
        return {"ok": True}

    def snapshot(self, session_id):
        self.outside_transaction()
        return {"storage_state": {"cookies": [{"name": "session", "value": COOKIE, "domain": "login.example", "path": "/"}], "origins": []},
                "url": "https://login.example/private?code=oauth-secret"}

    def page(self, session_id):
        self.outside_transaction()
        if self.on_page:
            self.on_page()
        return {"url": "https://login.example/ads?auth=private", "title": "Campaign drafts", "text": "Your saved campaign"}

    def close(self, session_id):
        self.outside_transaction()
        if self.fail_close:
            raise AiclError("unavailable", "Temporary private service failure")
        self.closed.append(session_id)

    def cancel_key(self, idempotency_key):
        self.close(idempotency_key)
        return {"closed": True}


def prepared_browser(build_env, base_env):
    env, workflow, _, auth, inst, _, job = request_env(build_env)
    settings = Settings.from_env({**base_env, "AICL_BROWSER_SERVICE_URL": "http://habitat-browser:3001",
                                  "AICL_BROWSER_SERVICE_TOKEN": "browser-only-token-" + "x" * 32})
    requests = OwnerRequestService(workflow, browser_enabled=True)
    login = requests.create(auth, inst.id, job["id"], "authentication", "Sign in to prepare a draft", "The website requires the owner's account.",
                            details={"domain": "login.example", "requested_access": "Prepare campaign drafts"}, dedupe_key="site-login", continuation="schedule")
    store = AesGcmSecretStore(bytes(range(32)), env.db)
    ctx = SimpleNamespace(settings=settings, db=env.db, clock=env.clock, ports=SimpleNamespace(secret_store=store))
    runtime = Runtime(env.db)
    broker = BrowserBroker(ctx, requests, runtime)
    requests.browser_cancel = broker.cancel
    return env, workflow, auth, inst, job, requests, login, store, runtime, broker


def test_handoff_encrypts_state_and_returns_session_not_authentication(build_env, base_env):
    env, workflow, auth, inst, job, requests, login, store, runtime, broker = prepared_browser(build_env, base_env)
    resumed = []
    workflow.owner_request_resolved = lambda *args: resumed.append(args)
    opened = broker.start(auth, login["id"], 1)
    assert opened["state"] == "active" and not opened["access_verified"]
    assert broker.start(auth, login["id"], 1)["id"] == opened["id"]
    assert len(runtime.creates) == 1
    frame = broker.frame(auth, login["id"])
    assert frame["url"] == "https://login.example" and frame["title"] == "Secure sign-in"
    broker.input(auth, login["id"], {"type": "text", "text": "fixture password never persisted"})
    resolved = broker.complete(auth, login["id"], 1, "schedule")
    assert resolved["status"] == "resolved" and resolved["browser_state"] == "complete"
    assert resolved["response"] == {"decision": "session_provided", "browser_session_id": opened["id"], "domain": "login.example", "access_verified": False}
    assert len(resumed) == 1 and runtime.closed == [opened["id"]]
    assert broker.complete(auth, login["id"], 1, "now")["continuation"] == "schedule"  # replay cannot change consent
    assert len(resumed) == 1
    with env.db.reader() as conn:
        saved = dict(conn.execute("SELECT * FROM browser_session WHERE id=?", (opened["id"],)).fetchone())
        assert COOKIE not in json.dumps(saved)
        assert COOKIE in store.get(saved["secret_ref"], auth.owner_id, opened["id"]).decode()
        audit = " ".join(str(tuple(row)) for row in conn.execute("SELECT * FROM audit_event"))
        assert COOKIE not in audit and "oauth-secret" not in audit and "fixture password" not in audit
        assert requests.answers_for_job(conn, job["id"]) == []
    assert "secret_ref" not in json.dumps(broker.status(auth, login["id"]))


def test_auth_tenant_scope_forged_completion_and_stale_tabs_fail_closed(build_env, base_env):
    env, _, auth, _, _, requests, login, _, runtime, broker = prepared_browser(build_env, base_env)
    stranger, _ = env.new_instance()
    for identity in (stranger, replace(auth, tenant_id=stranger.tenant_id)):
        rejection("not_found", lambda: broker.start(identity, login["id"], 1))
        rejection("not_found", lambda: broker.status(identity, login["id"]))
        rejection("not_found", lambda: broker.cancel(identity, login["id"]))
    rejection("conflict", lambda: broker.start(auth, login["id"], True))
    rejection("conflict", lambda: broker.start(auth, login["id"], 2))
    rejection("conflict", lambda: broker.complete(auth, login["id"], 1))
    rejection("denied", lambda: requests.complete_browser_session(auth, login["id"], "made-up", 1))
    rejection("unavailable", lambda: requests.respond(auth, login["id"], 1, decision="approve", answer="Already logged in"))
    assert runtime.creates == [] and requests.get(auth, login["id"])["status"] == "pending"
    opened = broker.start(auth, login["id"], 1)
    rejection("not_found", lambda: broker.revoke(stranger, opened["id"]))
    requests.respond(auth, login["id"], 1, decision="decline")
    assert broker.status(auth, login["id"])["state"] == "cancelled"
    assert opened["id"] in runtime.closed
    rejection("conflict", lambda: broker.frame(auth, login["id"]))


def test_expiry_cancel_and_reopen_keep_original_request_pending(build_env, base_env):
    env, _, auth, _, _, requests, login, _, runtime, broker = prepared_browser(build_env, base_env)
    first = broker.start(auth, login["id"], 1)
    env.clock.advance(timedelta(minutes=11))
    assert broker.status(auth, login["id"])["state"] == "expired"
    rejection("conflict", lambda: broker.complete(auth, login["id"], 1))
    second = broker.start(auth, login["id"], 1)
    assert first["id"] != second["id"]
    assert broker.cancel(auth, login["id"])["state"] == "cancelled"
    assert requests.get(auth, login["id"])["status"] == "pending"
    assert second["id"] in runtime.closed
    third = broker.start(auth, login["id"], 1)
    assert third["state"] == "active" and third["id"] != second["id"]


def test_close_failure_keeps_request_pending_and_encrypted_snapshot_retriable(build_env, base_env):
    env, _, auth, _, _, requests, login, _, runtime, broker = prepared_browser(build_env, base_env)
    opened = broker.start(auth, login["id"], 1)
    runtime.fail_close = True
    rejection("unavailable", lambda: broker.complete(auth, login["id"], 1, "schedule"))
    assert requests.get(auth, login["id"])["status"] == "pending"
    assert broker.status(auth, login["id"])["state"] == "saving"
    with env.db.reader() as conn:
        assert conn.execute("SELECT secret_ref FROM browser_session WHERE id=?", (opened["id"],)).fetchone()[0]
    runtime.fail_close = False
    assert broker.complete(auth, login["id"], 1, "schedule")["status"] == "resolved"


def test_saved_state_is_worker_only_scoped_and_revocable(build_env, base_env):
    env, _, auth, _, job, _, login, store, runtime, broker = prepared_browser(build_env, base_env)
    opened = broker.start(auth, login["id"], 1)
    broker.complete(auth, login["id"], 1)
    for url in ("http://login.example/", "https://other.example/", "https://login.example@other.example/", "https://login.example:8443/", "https://login.example/#token"):
        rejection("denied", lambda: broker.worker_page(auth, login["id"], job["id"], url))
    rejection("not_found", lambda: broker.worker_page(auth, login["id"], "different-job", "https://login.example/"))
    page = broker.worker_page(auth, login["id"], job["id"], "https://login.example/ads")
    assert page["text"] == "Your saved campaign" and page["url"] == "https://login.example"
    assert COOKIE not in json.dumps(page) and page["access_verified"] is False
    assert runtime.creates[-1]["storage_state"]["cookies"][0]["value"] == COOKIE
    with env.db.reader() as conn:
        ref = conn.execute("SELECT secret_ref FROM browser_session WHERE id=?", (opened["id"],)).fetchone()[0]
    assert broker.revoke(auth, opened["id"])["state"] == "revoked"
    with pytest.raises(SecretUnavailable):
        store.get(ref, auth.owner_id, opened["id"])
    rejection("denied", lambda: broker.worker_page(auth, login["id"], job["id"], "https://login.example/"))


def test_owner_and_worker_lease_are_exclusive_and_read_rechecks_expiry(build_env, base_env):
    env, _, auth, inst, job, requests, login, _, runtime, broker = prepared_browser(build_env, base_env)
    broker.start(auth, login["id"], 1)
    broker.complete(auth, login["id"], 1)
    second = requests.create(auth, inst.id, job["id"], "authentication", "Sign in again", "The website needs another sign-in.", details={"domain": "login.example"}, dedupe_key="again")
    broker.start(auth, second["id"], 1)
    rejection("denied", lambda: broker.worker_page(auth, login["id"], job["id"], "https://login.example/"))
    broker.cancel(auth, second["id"])
    broker.start(auth, second["id"], 1)
    broker.complete(auth, second["id"], 1)
    assert broker.status(auth, login["id"])["state"] == "revoked"
    runtime.on_page = lambda: env.clock.advance(timedelta(hours=25))
    rejection("denied", lambda: broker.worker_page(auth, second["id"], job["id"], "https://login.example/"))


def test_saved_access_reused_by_later_jobs_only_for_same_owner_and_agent(build_env, base_env):
    env, _, auth, inst, job, _, login, _, runtime, broker = prepared_browser(build_env, base_env)
    broker.start(auth, login["id"], 1)
    broker.complete(auth, login["id"], 1)
    later_id, other_id = str(uuid.uuid4()), str(uuid.uuid4())
    stranger, _ = env.new_instance()
    with env.db.transaction() as conn:
        other_inst = env.instances.insert_draft(conn, auth, replace(inst, id=str(uuid.uuid4()), name="Another owned agent"), ())
        source = dict(conn.execute("SELECT * FROM mock_workflow_run WHERE id=?", (job["id"],)).fetchone())
        for new_id, instance_id in ((later_id, source["instance_id"]), (other_id, other_inst.id)):
            fixture = {**source, "id": new_id, "instance_id": instance_id}
            conn.execute("INSERT INTO mock_workflow_run(" + ",".join(fixture) + ") VALUES(" + ",".join("?" for _ in fixture) + ")", tuple(fixture.values()))
    page = broker.worker_page(auth, login["id"], later_id, "https://login.example/ads")
    assert page["text"] == "Your saved campaign"
    rejection("not_found", lambda: broker.worker_page(auth, login["id"], other_id, "https://login.example/"))
    rejection("not_found", lambda: broker.worker_page(stranger, login["id"], other_id, "https://login.example/"))
    with env.db.reader() as conn:
        assert conn.execute("SELECT workflow_run_id FROM browser_session WHERE mode='worker'").fetchone()[0] == later_id


def test_worker_refreshes_encrypted_state_for_later_job_without_extending_owner_grant(build_env, base_env):
    env, _, auth, _, job, requests, login, store, runtime, broker = prepared_browser(build_env, base_env)
    owner = broker.start(auth, login["id"], 1)
    broker.complete(auth, login["id"], 1)
    with env.db.reader() as conn:
        original = dict(conn.execute("SELECT * FROM browser_session WHERE id=?", (owner["id"],)).fetchone())
    refreshed = {
        "cookies": [{"name": "session", "value": "rotated-private-cookie", "domain": "login.example", "path": "/"}],
        "origins": [{"origin": "https://login.example", "localStorage": [{"name": "account", "value": "private-local-value"}],
                     "indexedDB": [{"name": "authentication", "version": 1, "stores": [{"name": "tokens", "autoIncrement": False,
                                      "records": [{"key": "access", "value": "private-indexeddb-value"}], "indexes": []}]}]}],
    }
    def snapshot(session_id):
        runtime.outside_transaction()
        # A second worker may not start while the first refresh is in flight.
        rejection("conflict", lambda: broker.worker_page(auth, login["id"], job["id"], "https://login.example/"))
        return {"storage_state": refreshed}
    runtime.snapshot = snapshot
    env.clock.advance(timedelta(hours=1))
    page = broker.worker_page(auth, login["id"], job["id"], "https://login.example/ads")
    assert page["text"] == "Your saved campaign" and "rotated-private-cookie" not in json.dumps(page)
    with env.db.reader() as conn:
        saved = dict(conn.execute("SELECT * FROM browser_session WHERE id=?", (owner["id"],)).fetchone())
        assert saved["secret_ref"] != original["secret_ref"]
        assert saved["credential_expires_at"] == original["credential_expires_at"]
        blob = conn.execute("SELECT ciphertext FROM secret_blob WHERE ref=?", (saved["secret_ref"],)).fetchone()[0]
        assert b"rotated-private-cookie" not in bytes(blob)
    assert json.loads(store.get(saved["secret_ref"], auth.owner_id, owner["id"])) == refreshed
    with pytest.raises(SecretUnavailable):
        store.get(original["secret_ref"], auth.owner_id, owner["id"])
    assert runtime.creates[-1]["idempotency_key"] in runtime.closed

    later_id = str(uuid.uuid4())
    with env.db.transaction() as conn:
        source = dict(conn.execute("SELECT * FROM mock_workflow_run WHERE id=?", (job["id"],)).fetchone())
        later = {**source, "id": later_id}
        conn.execute("INSERT INTO mock_workflow_run(" + ",".join(later) + ") VALUES(" + ",".join("?" for _ in later) + ")", tuple(later.values()))
    env.clock.advance(timedelta(hours=1))
    # Rebuilding both the broker and cipher adapter proves reuse comes from the
    # durable database, not the first job's in-memory browser context.
    next_ctx = SimpleNamespace(settings=broker.ctx.settings, db=env.db, clock=env.clock,
                               ports=SimpleNamespace(secret_store=AesGcmSecretStore(bytes(range(32)), env.db)))
    next_runtime = Runtime(env.db)
    next_runtime.snapshot = lambda _: {"storage_state": refreshed}
    BrowserBroker(next_ctx, requests, next_runtime).worker_page(auth, login["id"], later_id, "https://login.example/ads")
    assert next_runtime.creates[0]["storage_state"] == refreshed


@pytest.mark.parametrize("failure", ["unavailable", "malformed", "store_write"])
def test_failed_worker_snapshot_preserves_previous_state_and_closes_runtime(build_env, base_env, failure):
    env, _, auth, _, job, _, login, store, runtime, broker = prepared_browser(build_env, base_env)
    owner = broker.start(auth, login["id"], 1)
    broker.complete(auth, login["id"], 1)
    with env.db.reader() as conn:
        original = dict(conn.execute("SELECT * FROM browser_session WHERE id=?", (owner["id"],)).fetchone())
    previous = store.get(original["secret_ref"], auth.owner_id, owner["id"])
    normal_snapshot = runtime.snapshot
    def snapshot(_):
        runtime.outside_transaction()
        if failure == "unavailable":
            raise AiclError("unavailable", "The browser snapshot was unavailable.")
        if failure == "store_write":
            return normal_snapshot(_)
        return {"storage_state": {"cookies": "invalid", "origins": []}}
    runtime.snapshot = snapshot
    if failure == "store_write":
        destroy = store.destroy
        def interrupted_destroy(ref):
            # Fail after the replacement was inserted, its reference changed,
            # and old ciphertext overwritten: all three changes must roll back.
            destroy(ref)
            raise SecretUnavailable("Interrupted session rotation")
        store.destroy = interrupted_destroy
    rejection("unavailable", lambda: broker.worker_page(auth, login["id"], job["id"], "https://login.example/ads"))
    with env.db.reader() as conn:
        saved = dict(conn.execute("SELECT * FROM browser_session WHERE id=?", (owner["id"],)).fetchone())
        assert saved["secret_ref"] == original["secret_ref"]
        assert saved["credential_expires_at"] == original["credential_expires_at"]
        assert conn.execute("SELECT COUNT(*) FROM secret_blob").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM secret_blob WHERE destroyed_at IS NULL").fetchone()[0] == 1
    assert store.get(saved["secret_ref"], auth.owner_id, owner["id"]) == previous
    assert runtime.creates[-1]["idempotency_key"] in runtime.closed


@pytest.mark.parametrize("invalidation", ["revoke", "expire", "pending_request"])
def test_worker_snapshot_cannot_resurrect_invalidated_access(build_env, base_env, invalidation):
    env, _, auth, inst, job, requests, login, store, runtime, broker = prepared_browser(build_env, base_env)
    owner = broker.start(auth, login["id"], 1)
    broker.complete(auth, login["id"], 1)
    with env.db.reader() as conn:
        original_ref = conn.execute("SELECT secret_ref FROM browser_session WHERE id=?", (owner["id"],)).fetchone()[0]
    snapshot = runtime.snapshot
    def invalidated_snapshot(session_id):
        value = snapshot(session_id)
        if invalidation == "revoke":
            broker.revoke(auth, owner["id"])
        elif invalidation == "expire":
            env.clock.advance(timedelta(hours=25))
        else:
            requests.create(auth, inst.id, job["id"], "authentication", "Sign in again", "The current account must be reconnected.",
                            details={"domain": "login.example"}, dedupe_key="refresh-login")
        return value
    runtime.snapshot = invalidated_snapshot
    rejection("denied", lambda: broker.worker_page(auth, login["id"], job["id"], "https://login.example/ads"))
    # Final status applies expiry cleanup even if an earlier denied transaction
    # rolled back, and must never leave a replacement credential available.
    status = broker.status(auth, login["id"])
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM secret_blob").fetchone()[0] == 1
        ref = conn.execute("SELECT secret_ref FROM browser_session WHERE id=?", (owner["id"],)).fetchone()[0]
    if invalidation in ("revoke", "expire"):
        assert ref is None and status["state"] in ("revoked", "expired")
        with pytest.raises(SecretUnavailable):
            store.get(original_ref, auth.owner_id, owner["id"])
    else:
        assert ref == original_ref
    assert runtime.creates[-1]["idempotency_key"] in runtime.closed


def test_job_authority_is_rechecked_before_committing_worker_state(build_env, base_env):
    env, _, auth, _, job, _, login, store, runtime, broker = prepared_browser(build_env, base_env)
    owner = broker.start(auth, login["id"], 1)
    broker.complete(auth, login["id"], 1)
    with env.db.reader() as conn:
        original_ref = conn.execute("SELECT secret_ref FROM browser_session WHERE id=?", (owner["id"],)).fetchone()[0]
    authority_lost = []
    def authorize(conn):
        assert conn is getattr(env.db._local, "conn", None)
        if authority_lost:
            raise AiclError("denied", "The owner paused this agent.")
    snapshot = runtime.snapshot
    def paused_snapshot(session_id):
        value = snapshot(session_id)
        authority_lost.append(True)
        return value
    runtime.snapshot = paused_snapshot
    rejection("denied", lambda: broker.worker_page(auth, login["id"], job["id"], "https://login.example/ads", authorize=authorize))
    with env.db.reader() as conn:
        assert conn.execute("SELECT secret_ref FROM browser_session WHERE id=?", (owner["id"],)).fetchone()[0] == original_ref
        assert conn.execute("SELECT COUNT(*) FROM secret_blob").fetchone()[0] == 1
    assert COOKIE in store.get(original_ref, auth.owner_id, owner["id"]).decode()
    assert runtime.creates[-1]["idempotency_key"] in runtime.closed


def test_cancellation_during_snapshot_cannot_save_credentials_or_resolve_request(build_env, base_env):
    env, _, auth, _, _, requests, login, _, runtime, broker = prepared_browser(build_env, base_env)
    broker.start(auth, login["id"], 1)
    snapshot = runtime.snapshot
    def cancelled_snapshot(session_id):
        value = snapshot(session_id)
        broker.cancel(auth, login["id"])
        return value
    runtime.snapshot = cancelled_snapshot
    rejection("conflict", lambda: broker.complete(auth, login["id"], 1))
    assert requests.get(auth, login["id"])["status"] == "pending"
    assert broker.status(auth, login["id"])["state"] == "cancelled"
    with env.db.reader() as conn:
        assert conn.execute("SELECT secret_ref FROM browser_session").fetchone()[0] is None


def test_revocation_during_worker_read_discards_page(build_env, base_env):
    _, _, auth, _, job, _, login, _, runtime, broker = prepared_browser(build_env, base_env)
    opened = broker.start(auth, login["id"], 1)
    broker.complete(auth, login["id"], 1)
    runtime.on_page = lambda: broker.revoke(auth, opened["id"])
    rejection("denied", lambda: broker.worker_page(auth, login["id"], job["id"], "https://login.example/"))


def test_saved_credentials_can_be_revoked_when_browser_service_disabled(build_env, base_env):
    env, _, auth, _, _, _, login, store, _, broker = prepared_browser(build_env, base_env)
    opened = broker.start(auth, login["id"], 1)
    broker.complete(auth, login["id"], 1)
    disabled = BrowserBroker(SimpleNamespace(settings=Settings.from_env(base_env), db=env.db, clock=env.clock,
                                            ports=SimpleNamespace(secret_store=store)), broker.requests)
    assert disabled.revoke(auth, opened["id"])["state"] == "revoked"


def test_unknown_start_retries_same_key_and_storage_expiry_destroys_saved_state(build_env, base_env):
    env, _, auth, _, job, requests, login, store, runtime, broker = prepared_browser(build_env, base_env)
    create = runtime.create
    def lost_start(**payload):
        create(**payload)
        raise AiclError("unavailable", "Temporary private service failure")
    runtime.create = lost_start
    rejection("unavailable", lambda: broker.start(auth, login["id"], 1))
    first_key = runtime.creates[0]["idempotency_key"]
    assert broker.status(auth, login["id"])["state"] == "starting"
    assert requests.get(auth, login["id"])["status"] == "pending"
    runtime.create = create
    opened = broker.start(auth, login["id"], 1)
    assert opened["id"] == first_key
    broker.complete(auth, login["id"], 1)
    with env.db.reader() as conn:
        ref = conn.execute("SELECT secret_ref FROM browser_session WHERE id=?", (opened["id"],)).fetchone()[0]
    env.clock.advance(timedelta(hours=25))
    assert broker.status(auth, login["id"])["state"] == "expired"
    with pytest.raises(SecretUnavailable):
        store.get(ref, auth.owner_id, opened["id"])
    rejection("denied", lambda: broker.worker_page(auth, login["id"], job["id"], "https://login.example/"))


def test_failed_cancel_keeps_exclusive_lease_even_after_ttl_until_close_confirmed(build_env, base_env):
    env, _, auth, inst, job, requests, login, _, runtime, broker = prepared_browser(build_env, base_env)
    first = broker.start(auth, login["id"], 1)
    runtime.fail_close = True
    rejection("unavailable", lambda: broker.cancel(auth, login["id"]))
    assert broker.status(auth, login["id"])["state"] == "closing"
    rejection("conflict", lambda: broker.frame(auth, login["id"]))
    rejection("unavailable", lambda: broker.start(auth, login["id"], 1))
    env.clock.advance(timedelta(minutes=11))
    assert broker.status(auth, login["id"])["state"] == "closing"
    second = requests.create(auth, inst.id, job["id"], "authentication", "Another sign-in", "Account access is needed.",
                             details={"domain": "login.example"}, dedupe_key="second-sign-in")
    rejection("unavailable", lambda: broker.start(auth, second["id"], 1))
    assert len(runtime.creates) == 1  # Runtime capacity may exceed one; the broker still forbids overlap.
    with env.db.reader() as conn:
        lease = conn.execute("SELECT state,close_target FROM browser_session WHERE id=?", (first["id"],)).fetchone()
        assert tuple(lease) == ("closing", "cancelled")
    runtime.fail_close = False
    assert broker.cancel(auth, login["id"])["state"] == "cancelled"
    opened = broker.start(auth, second["id"], 1)
    assert opened["state"] == "active" and first["id"] in runtime.closed
    assert len({p["idempotency_key"] for p in runtime.creates} - set(runtime.closed)) == 1


def test_failed_worker_close_blocks_reuse_and_revocation_keeps_child_lease(build_env, base_env):
    env, _, auth, _, job, _, login, store, runtime, broker = prepared_browser(build_env, base_env)
    owner = broker.start(auth, login["id"], 1)
    broker.complete(auth, login["id"], 1)
    with env.db.reader() as conn:
        ref = conn.execute("SELECT secret_ref FROM browser_session WHERE id=?", (owner["id"],)).fetchone()[0]
    runtime.fail_close = True
    rejection("unavailable", lambda: broker.worker_page(auth, login["id"], job["id"], "https://login.example/"))
    assert broker.status(auth, login["id"])["state"] == "closing"
    rejection("conflict", lambda: broker.worker_page(auth, login["id"], job["id"], "https://login.example/"))
    assert len(runtime.creates) == 2
    rejection("unavailable", lambda: broker.revoke(auth, owner["id"]))
    with pytest.raises(SecretUnavailable):
        store.get(ref, auth.owner_id, owner["id"])
    rejection("denied", lambda: broker.worker_page(auth, login["id"], job["id"], "https://login.example/"))
    env.clock.advance(timedelta(minutes=20))
    with env.db.reader() as conn:
        assert conn.execute("SELECT state,close_target FROM browser_session WHERE mode='worker'").fetchone()["state"] == "closing"
    assert broker.status(auth, login["id"])["state"] == "closing"
    runtime.fail_close = False
    assert broker.revoke(auth, owner["id"])["state"] == "revoked"
    with env.db.reader() as conn:
        assert conn.execute("SELECT state FROM browser_session WHERE mode='worker'").fetchone()[0] == "revoked"


def test_expiry_requires_runtime_shutdown_before_releasing_owner_lease(build_env, base_env):
    env, _, auth, _, _, _, login, _, runtime, broker = prepared_browser(build_env, base_env)
    first = broker.start(auth, login["id"], 1)
    runtime.fail_close = True
    env.clock.advance(timedelta(minutes=11))
    status = broker.status(auth, login["id"])
    assert status["state"] == "closing" and status["close_target"] == "expired"
    rejection("unavailable", lambda: broker.start(auth, login["id"], 1))
    assert len(runtime.creates) == 1
    runtime.fail_close = False
    assert broker.start(auth, login["id"], 1)["id"] != first["id"]
    assert first["id"] in runtime.closed


def test_successful_http_without_closed_confirmation_does_not_release_lease(build_env, base_env):
    _, _, auth, _, _, _, login, _, runtime, broker = prepared_browser(build_env, base_env)
    broker.start(auth, login["id"], 1)
    runtime.cancel_key = lambda key: {"closed": False, "status": "queued"}
    rejection("unavailable", lambda: broker.cancel(auth, login["id"]))
    assert broker.status(auth, login["id"])["state"] == "closing"
    rejection("unavailable", lambda: broker.start(auth, login["id"], 1))
    assert len(runtime.creates) == 1


def test_unknown_create_cancellation_tombstones_key_before_allowing_new_session(build_env, base_env):
    _, _, auth, _, _, _, login, _, runtime, broker = prepared_browser(build_env, base_env)
    create = runtime.create
    def lost_start(**payload):
        create(**payload)
        raise AiclError("unavailable", "Response lost")
    runtime.create = lost_start
    rejection("unavailable", lambda: broker.start(auth, login["id"], 1))
    key = runtime.creates[0]["idempotency_key"]
    runtime.fail_close = True
    rejection("unavailable", lambda: broker.cancel(auth, login["id"]))
    assert broker.status(auth, login["id"])["state"] == "closing"
    runtime.fail_close = False
    assert broker.cancel(auth, login["id"])["state"] == "cancelled"
    assert key in runtime.closed


def test_close_lease_migration_preserves_existing_parent_child_and_encrypted_state(build_env, base_env, tmp_path, monkeypatch):
    import shutil
    import aicl.db as db_module
    migrations = db_module.MIGRATIONS_DIR
    old_migrations = tmp_path / "old-browser-schema"
    old_migrations.mkdir()
    for path in migrations.glob("*.sql"):
        if path.name < "0025":
            shutil.copyfile(path, old_migrations / path.name)
    from aicl.workflow.service import MockWorkflowService
    # Historical setup needs only the old job projection. Current UI projections
    # intentionally query the new proposal table after all migrations have run.
    def historical_overview(self, auth, instance_id):
        with self.db.reader() as conn:
            return {"runs": [dict(row) for row in conn.execute(
                "SELECT * FROM mock_workflow_run WHERE instance_id=?", (instance_id,))]}
    with monkeypatch.context() as historical:
        historical.setattr(db_module, "MIGRATIONS_DIR", old_migrations)
        historical.setattr(MockWorkflowService, "overview", historical_overview)
        with historical_budget_fixture(build_env) as historical_build:
            env, _, auth, inst, job, _, login, store, _, _ = prepared_browser(historical_build, base_env)
    secret_ref = store.put(auth.owner_id, "old-owner", "browser_storage_state", COOKIE.encode())
    now = db_module.to_iso(env.clock.now())
    with env.db.transaction() as conn:
        owner = {"id": "old-owner", "tenant_id": auth.tenant_id, "owner_id": auth.owner_id,
                 "instance_id": inst.id, "request_id": login["id"], "workflow_run_id": job["id"],
                 "request_version": 1, "domain": "login.example", "mode": "owner", "parent_session_id": None,
                 "state": "complete", "runtime_id": "old-runtime", "secret_ref": secret_ref,
                 "expires_at": now, "credential_expires_at": now, "created_at": now, "updated_at": now}
        child = {**owner, "id": "old-worker", "mode": "worker", "parent_session_id": "old-owner", "state": "active", "secret_ref": None}
        for item in (owner, child):
            conn.execute("INSERT INTO browser_session(" + ",".join(item) + ") VALUES(" + ",".join("?" for _ in item) + ")", tuple(item.values()))
    monkeypatch.setattr(db_module, "MIGRATIONS_DIR", migrations)
    env.db.migrate()
    with env.db.reader() as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        rows = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM browser_session")}
        assert rows["old-owner"] == {**owner, "close_target": None}
        assert rows["old-worker"] == {**child, "close_target": None}
    assert store.get(secret_ref, auth.owner_id, "old-owner") == COOKIE.encode()


def test_concurrent_start_uses_one_durable_lease(build_env, base_env):
    env, _, auth, _, _, _, login, _, runtime, broker = prepared_browser(build_env, base_env)
    barrier = Barrier(2)
    def start(_):
        barrier.wait()
        return broker.start(auth, login["id"], 1)["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(start, (1, 2)))
    assert ids[0] == ids[1]
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM browser_session").fetchone()[0] == 1


def test_browser_settings_reject_public_origins_bad_tokens_and_shared_credentials(base_env):
    valid = {**base_env, "AICL_BROWSER_SERVICE_URL": "http://habitat-browser:3001", "AICL_BROWSER_SERVICE_TOKEN": "b" * 40}
    assert Settings.from_env(valid).browser_service_url == "http://habitat-browser:3001"
    for url in ("http://public.example", "http://user:pass@habitat-browser", "http://habitat-browser/path", "http://habitat-browser?secret=x", "http://169.254.169.254"):
        with pytest.raises(SettingsError):
            Settings.from_env({**valid, "AICL_BROWSER_SERVICE_URL": url})
    for token in ("short", base_env["AICL_SESSION_SECRET"], "CHANGE_ME" + "x" * 40):
        with pytest.raises(SettingsError):
            Settings.from_env({**valid, "AICL_BROWSER_SERVICE_TOKEN": token})


def test_runtime_transport_does_not_follow_redirects_or_expose_response_secrets():
    import httpx
    def handle(request):
        assert request.headers["authorization"] == "Bearer " + "b" * 40
        return httpx.Response(302, headers={"Location": "http://evil.example"}, text=COOKIE)
    client = BrowserClient("http://habitat-browser", "b" * 40, transport=httpx.MockTransport(handle))
    error = rejection("unavailable", lambda: client.create(idempotency_key="fixture", url="https://login.example", mode="owner", ttl_seconds=600))
    assert COOKIE not in error.message
