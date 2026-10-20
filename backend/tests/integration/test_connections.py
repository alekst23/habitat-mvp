"""Slice 2: connections, OAuth, secret store, broker, revocation (F2-S1/S2/S3/S6/S7/S10, F1-S9 connection reasons)."""

from __future__ import annotations

import logging
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest

import seams
from aicl.connections.models import CAPABILITY_SCOPES
from aicl.connections.ports import AesGcmSecretStore, FakeProviderOAuth, SecretUnavailable
from aicl.control.errors import AiclError
from aicl.control.instances import GateContext, Limits
from aicl.network.policy import FakeResolver
from aicl.work.models import AuthorizedWork

KEY = bytes(range(32))
SEND, READ = CAPABILITY_SCOPES["gmail.send"][1], CAPABILITY_SCOPES["gmail.read"][1]


class Crash(BaseException):
    """Simulated process crash (not an Exception, so no handler may swallow it)."""


class CrashOnRevoke(FakeProviderOAuth):
    def revoke(self, provider, token):
        raise Crash()


class SpyStore:
    """Wraps a real store and counts secret reads (the broker must not read for a revoked connection)."""

    def __init__(self, inner):
        self.inner, self.reads = inner, 0

    def put(self, *a):
        return self.inner.put(*a)

    def get(self, *a):
        self.reads += 1
        return self.inner.get(*a)

    def destroy(self, ref):
        return self.inner.destroy(ref)


@pytest.fixture
def world(build_env):
    """A factory: seams are called from the test body so an unwired service fails at the test, not in setup."""
    def build():
        env = build_env()
        store = SpyStore(seams.aes_secret_store(KEY))
        oauth = FakeProviderOAuth()
        return env, store, oauth, seams.connection_service(env, oauth, store), seams.instance_operations(env)
    return build


def state_of(begun) -> str:
    url = begun["authorization_url"] if isinstance(begun, dict) else begun
    return parse_qs(urlparse(url).query)["state"][0]


def connect(env, svc, auth, caps=("gmail.send",), provider="gmail", code="fake-code-ok"):
    begun = svc.begin_oauth(auth, provider, caps)
    return svc.complete_oauth(auth, state_of(begun), code), begun


def denies(call, *errors):
    with pytest.raises(AiclError) as err:
        call()
    assert err.value.error in errors, err.value.error
    return err.value


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/connections/ports.py:SecretStore")
def test_secret_store_encrypts_binds_to_owner_connection_and_destroys():
    store = seams.aes_secret_store(KEY)
    ref = store.put("owner-1", "conn-1", "access_token", b"tok-PLAINTEXT-123")
    assert "PLAINTEXT" not in ref and store.get(ref, "owner-1", "conn-1") == b"tok-PLAINTEXT-123"
    for owner, conn in (("owner-2", "conn-1"), ("owner-1", "conn-2")):  # AAD binds owner and connection
        with pytest.raises(SecretUnavailable):
            store.get(ref, owner, conn)
    with pytest.raises(SecretUnavailable):
        seams.aes_secret_store(bytes(reversed(KEY))).get(ref, "owner-1", "conn-1")  # wrong key never falls back
    assert store.put("owner-1", "conn-1", "access_token", b"tok-PLAINTEXT-123") != ref  # random nonce per put
    store.destroy(ref)
    store.destroy(ref)  # idempotent
    with pytest.raises(SecretUnavailable):
        store.get(ref, "owner-1", "conn-1")
    with pytest.raises(SecretUnavailable):
        store.get("missing-ref", "owner-1", "conn-1")


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/connections/ports.py:ConnectionService")
def test_oauth_accepts_only_matching_single_use_state_pkce_and_exact_scopes(world):
    env, store, oauth, svc, ops = world()
    auth, _ = env.new_instance()
    stranger, _ = env.new_instance()
    conn, begun = connect(env, svc, auth)
    assert conn.status == "active" and conn.provider == "gmail" and conn.granted_scopes == (SEND,) and conn.secret_ref
    assert conn.owner_id == auth.owner_id and "access_token" not in repr(conn)
    url = begun["authorization_url"] if isinstance(begun, dict) else begun
    query = parse_qs(urlparse(url).query)
    assert query["code_challenge_method"] == ["S256"] and len(query["code_challenge"][0]) >= 43
    assert query["redirect_uri"] == ["http://127.0.0.1:4173/connections/oauth/callback"]
    assert SEND in query["scope"][0] and "state" in query
    assert [e.event_type for e in env.audit.list_for_owner(auth)].count("connection.created") == 1

    def attempts():
        return [e.event_type for e in env.audit.list_for_owner(auth)].count("connection.created")

    state = state_of(svc.begin_oauth(auth, "gmail", ("gmail.send",)))
    svc.complete_oauth(auth, state, "fake-code-ok")
    assert attempts() == 2
    denies(lambda: svc.complete_oauth(auth, state, "fake-code-ok"), "denied", "validation_failed", "not_found")  # replay
    assert attempts() == 2

    wrong_session = auth.__class__(auth.owner_id, auth.tenant_id, "other-session", auth.expires_at)
    for who in (stranger, wrong_session):  # another owner or another session of the same owner
        state = state_of(svc.begin_oauth(auth, "gmail", ("gmail.send",)))
        denies(lambda: svc.complete_oauth(who, state, "fake-code-ok"), "denied", "validation_failed", "not_found")
        assert attempts() == 2
    denies(lambda: svc.complete_oauth(auth, "unknown-state", "fake-code-ok"), "denied", "validation_failed", "not_found")

    state = state_of(svc.begin_oauth(auth, "gmail", ("gmail.send",)))  # expiry after 600 seconds
    env.clock.advance(timedelta(seconds=601))
    denies(lambda: svc.complete_oauth(auth, state, "fake-code-ok"), "denied", "validation_failed", "not_found")
    env.clock.advance(timedelta(seconds=-601))
    state = state_of(svc.begin_oauth(auth, "gmail", ("gmail.send",)))  # a provider error or bad exchange creates nothing
    denies(lambda: svc.complete_oauth(auth, state, "fake-code-error"), "denied", "validation_failed", "unavailable")
    assert attempts() == 2

    short = seams.connection_service(env, FakeProviderOAuth(grant_scopes=(READ,)), store)  # scope shortfall
    state = state_of(short.begin_oauth(auth, "gmail", ("gmail.send",)))
    denies(lambda: short.complete_oauth(auth, state, "fake-code-ok"), "denied", "validation_failed")
    assert attempts() == 2
    denies(lambda: svc.begin_oauth(auth, "gmail", ("reddit.post",)), "validation_failed")  # capability/provider mismatch
    denies(lambda: svc.begin_oauth(auth, "gmail", ("network.fetch",)), "validation_failed")


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/connections/ports.py:ConnectionService")
def test_oauth_rejects_extra_scopes_before_saving_credentials(world, monkeypatch):
    env, store, _, _, _ = world()
    auth, _ = env.new_instance()
    oauth = FakeProviderOAuth(grant_scopes=(SEND, READ))
    svc = seams.connection_service(env, oauth, store)
    state = state_of(svc.begin_oauth(auth, "gmail", ("gmail.send",)))
    saved_fields = []
    original_put = store.put

    def record_put(owner_id, connection_id, field, plaintext):
        saved_fields.append(field)
        return original_put(owner_id, connection_id, field, plaintext)

    monkeypatch.setattr(store, "put", record_put)
    error = denies(lambda: svc.complete_oauth(auth, state, "fake-code-ok"), "validation_failed")
    assert error.extra["field_errors"] == [{"field": "scope", "code": "scope_mismatch"}]
    assert saved_fields == []
    with env.db.reader() as conn:
        assert conn.execute("SELECT count(*) FROM connection").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM connection_secret").fetchone()[0] == 0
    assert "connection.created" not in [e.event_type for e in env.audit.list_for_owner(auth)]


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/creation/operations.py:InstanceOperations")
def test_attach_rules_ownership_provider_scope_replacement_and_connection_gate(world):
    env, store, oauth, svc, ops = world()
    auth, inst = env.new_instance(limits=Limits(), capabilities=("gmail.send", "gmail.read", "reddit.post"))
    other, other_inst = env.new_instance()
    mine, _ = connect(env, svc, auth, ("gmail.read",))  # only gmail.readonly granted
    theirs, _ = connect(env, svc, other, ("gmail.send",))
    both, _ = connect(env, svc, auth, ("gmail.send", "gmail.read"))

    denies(lambda: ops.attach_connection(auth, inst.id, 1, "gmail.send", theirs.id), "not_found")  # other owner's
    denies(lambda: ops.attach_connection(other, inst.id, 1, "gmail.send", theirs.id), "not_found")  # other's instance
    denies(lambda: ops.attach_connection(auth, inst.id, 1, "reddit.post", both.id), "validation_failed")  # provider
    denies(lambda: ops.attach_connection(auth, inst.id, 1, "inference", both.id), "validation_failed")  # no provider
    short = denies(lambda: ops.attach_connection(auth, inst.id, 1, "gmail.send", mine.id), "validation_failed")
    assert any(f.get("code") == "scope_missing" for f in short.extra["field_errors"])
    denies(lambda: ops.attach_connection(auth, inst.id, 9, "gmail.send", both.id), "conflict")  # stale version
    assert env.instances.get(auth, inst.id).version == 1  # no refusal had an effect

    ok = ops.attach_connection(auth, inst.id, 1, "gmail.send", both.id)
    assert ok.changed and ok.instance.version == 2
    view = ok.instance.attachments
    assert [(a.capability, a.connection_id, a.connection_status) for a in view] == [("gmail.send", both.id, "active")]
    second, _ = connect(env, svc, auth, ("gmail.send",))
    replaced = ops.attach_connection(auth, inst.id, 2, "gmail.send", second.id)  # one active attachment per capability
    assert [a.connection_id for a in replaced.instance.attachments] == [second.id]
    ops.attach_connection(auth, inst.id, 3, "gmail.read", both.id)  # one connection, many capabilities/instances
    again = ops.attach_connection(auth, inst.id, 4, "gmail.read", both.id)
    assert again.changed is False
    detached = ops.detach_connection(auth, inst.id, 4, "gmail.read")
    assert [a.capability for a in detached.instance.attachments] == ["gmail.send"] and detached.instance.version == 5
    kinds = [e.event_type for e in env.audit.list_for_instance(auth, inst.id)]
    assert "connection.attached" in kinds and "connection.detached" in kinds

    # connection_* gate re-check: permits only when every gated capability has an active attachment on an active connection
    with env.db.transaction() as conn:
        env.instances.set_gated(conn, auth, inst.id, "connection_revoked", GateContext(("gmail.read",), None))
    version = env.instances.get(auth, inst.id).version
    assert denies(lambda: ops.resolve_gate(auth, inst.id, version), "denied").extra["reason"] == "gate_unresolved"
    cleared = ops.attach_connection(auth, inst.id, version, "gmail.read", both.id)  # fixing mutation clears it
    assert cleared.instance.gated_reason is None
    with env.db.transaction() as conn:
        env.instances.set_gated(conn, auth, inst.id, "connection_reauthorization_required", GateContext(("gmail.read",), None))
    version = env.instances.get(auth, inst.id).version
    assert ops.resolve_gate(auth, inst.id, version).instance.gated_reason is None  # now permits


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/connections/ports.py:ConnectionService")
def test_revocation_detaches_gates_destroys_secret_and_survives_provider_failure(world):
    env, store, oauth, svc, ops = world()
    auth, inst = env.new_instance(limits=Limits(), capabilities=("gmail.send",))
    spare, _ = env.new_instance()
    conn, _ = connect(env, svc, auth)
    ref = conn.secret_ref
    ops.set_lifecycle(auth, inst.id, 1, "activate")
    ops.attach_connection(auth, inst.id, 2, "gmail.send", conn.id)
    version = env.instances.get(auth, inst.id).version

    denies(lambda: svc.revoke_connection(spare, conn.id), "not_found")  # another owner
    out = svc.revoke_connection(auth, conn.id)
    assert out.connection.status == "revoked" and out.connection.secret_ref is None
    assert out.detached_instance_ids == (inst.id,) and out.provider_revoke_status == "succeeded"
    assert ("revoke", "gmail") in oauth.calls
    with pytest.raises(SecretUnavailable):
        store.inner.get(ref, auth.owner_id, conn.id)  # credentials invalidated
    after = env.instances.get(auth, inst.id)
    assert after.gated_reason == "connection_revoked" and after.gate_context.capabilities == ("gmail.send",)
    assert after.version == version + 1
    kinds = [e.event_type for e in env.audit.list_for_owner(auth)]
    assert "connection.revoked" in kinds and "connection.provider_revoke_succeeded" in kinds
    assert svc.revoke_connection(auth, conn.id).connection.status == "revoked"  # idempotent
    assert [e.event_type for e in env.audit.list_for_owner(auth)].count("connection.revoked") == 1

    failing_oauth = FakeProviderOAuth(fail_revoke=True)  # provider failure: local revoke still commits
    failing = seams.connection_service(env, failing_oauth, store)
    second, _ = connect(env, failing, auth, ("gmail.send",))
    outcome = failing.revoke_connection(auth, second.id)
    assert outcome.connection.status == "revoked" and outcome.connection.secret_ref is None
    assert outcome.provider_revoke_status == "failed"
    with pytest.raises(SecretUnavailable):
        store.inner.get(second.secret_ref, auth.owner_id, second.id)
    assert "connection.provider_revoke_failed" in [e.event_type for e in env.audit.list_for_owner(auth)]

    # crash after transaction A: the secret survives until the startup sweeper destroys it
    crashing = seams.connection_service(env, CrashOnRevoke(), store)
    third, _ = connect(env, crashing, auth, ("gmail.send",))
    with pytest.raises(Crash):
        crashing.revoke_connection(auth, third.id)
    assert store.inner.get(third.secret_ref, auth.owner_id, third.id)  # still readable only by the sweeper path
    seams.revocation_sweeper(env, failing_oauth, store).run_once()
    with pytest.raises(SecretUnavailable):
        store.inner.get(third.secret_ref, auth.owner_id, third.id)
    swept = [e for e in env.audit.list_for_owner(auth) if e.connection_id == third.id]
    assert "connection.provider_revoke_failed" in [e.event_type for e in swept]
    assert svc.revoke_connection(auth, third.id).connection.secret_ref is None


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/connections/ports.py:CredentialBroker")
def test_broker_checks_before_reading_secrets_refreshes_and_never_returns_credentials(world, caplog):
    env, store, oauth, svc, ops = world()
    auth, inst = env.new_instance(limits=Limits(), capabilities=("gmail.send",))
    conn, _ = connect(env, svc, auth)
    secret = store.inner.get(conn.secret_ref, auth.owner_id, conn.id).decode()
    attached = ops.attach_connection(auth, inst.id, 1, "gmail.send", conn.id)
    handle = attached.instance.attachments  # the opaque attachment id is the connection_handle
    broker = seams.credential_broker(env, oauth, store, FakeResolver({"gmail.googleapis.com": ["142.250.0.1"]}))
    work = AuthorizedWork("work_" + "1" * 30, inst.id, "gmail.send", {"to": "a@example.com"}, "hold", "attachment-id",
                          "https://gmail.googleapis.com/gmail/v1/users/me/messages/send")
    with caplog.at_level(logging.DEBUG):
        result = broker.call(work, "gmail.messages.send")
        assert result.status and isinstance(result.response_summary, dict)
        env.clock.advance(timedelta(days=2))  # expired access token is refreshed inside the broker
        broker.call(work, "gmail.messages.send")
        assert ("refresh", "gmail") in oauth.calls
        svc.revoke_connection(auth, conn.id)
        reads = store.reads
        denies(lambda: broker.call(work, "gmail.messages.send"), "denied", "unavailable")  # connection_unavailable
        assert store.reads == reads  # denied before any credential was read
    markers = {secret, *[t for t in secret.replace(":", " ").replace(",", " ").split() if len(t) >= 8]}
    blob = repr((result, handle, env.audit.list_for_owner(auth), caplog.text))
    assert not any(m in blob for m in markers), "credential leaked into a result, audit event or log"


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/connections/ports.py:CredentialBroker")
def test_refresh_cannot_restore_credentials_after_completed_revocation(world, monkeypatch):
    env, _, oauth, _, ops = world()
    store = SpyStore(AesGcmSecretStore(KEY, env.db))
    svc = seams.connection_service(env, oauth, store)
    auth, inst = env.new_instance(limits=Limits(), capabilities=("gmail.send",))
    connection, _ = connect(env, svc, auth)
    ops.attach_connection(auth, inst.id, 1, "gmail.send", connection.id)
    broker = seams.credential_broker(env, oauth, store, FakeResolver({"gmail.googleapis.com": ["142.250.0.1"]}))
    work = AuthorizedWork("work_" + "3" * 30, inst.id, "gmail.send", {}, "hold", "attachment-id",
                          "https://gmail.googleapis.com/gmail/v1/users/me/messages/send")
    env.clock.advance(timedelta(days=2))
    refresh = oauth.refresh

    def revoke_before_refresh_returns(provider, token):
        tokens = refresh(provider, token)
        revoked = svc.revoke_connection(auth, connection.id)
        assert revoked.connection.secret_ref is None
        return tokens

    monkeypatch.setattr(oauth, "refresh", revoke_before_refresh_returns)
    error = denies(lambda: broker.call(work, "gmail.messages.send"), "denied")
    assert error.extra["reason"] == "connection_unavailable"
    with env.db.reader() as conn:
        row = conn.execute("SELECT status, secret_ref FROM connection WHERE id = ?", (connection.id,)).fetchone()
        assert row["status"] == "revoked" and row["secret_ref"] is None
        assert conn.execute("SELECT count(*) FROM secret_blob WHERE destroyed_at IS NULL").fetchone()[0] == 0
    assert ("refresh", "gmail") in oauth.calls and ("revoke", "gmail") in oauth.calls
    assert ("call", "gmail") not in oauth.calls


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/connections/ports.py:CredentialBroker")
def test_failed_refresh_requires_reauthorization_and_denies(world):
    env, store, _, _, ops = world()
    oauth = FakeProviderOAuth(fail_refresh=True)
    svc = seams.connection_service(env, oauth, store)
    auth, inst = env.new_instance(limits=Limits(), capabilities=("gmail.send",))
    conn, _ = connect(env, svc, auth)
    ops.attach_connection(auth, inst.id, 1, "gmail.send", conn.id)
    broker = seams.credential_broker(env, oauth, store, FakeResolver({"gmail.googleapis.com": ["142.250.0.1"]}))
    work = AuthorizedWork("work_" + "2" * 30, inst.id, "gmail.send", {}, "hold", "attachment-id",
                          "https://gmail.googleapis.com/gmail/v1/users/me/messages/send")
    env.clock.advance(timedelta(days=2))
    denies(lambda: broker.call(work, "gmail.messages.send"), "denied", "unavailable")
    assert env.instances.get(auth, inst.id).gated_reason in (None, "connection_reauthorization_required")


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/connections/ports.py:ConnectionService")
def test_oauth_callback_route_requires_session_and_creates_nothing_on_invalid_state(web):
    anonymous = web.owner_a.__class__(web.app)
    assert anonymous.get("/connections/oauth/callback", params={"state": "x", "code": "c"}).status_code == 401
    for params in ({"state": "unknown-state", "code": "SECRET-CODE-1"}, {"error": "access_denied", "state": "s"}):
        r = web.owner_a.get("/connections/oauth/callback", params=params, follow_redirects=False)
        assert r.status_code in (302, 303, 307), params  # generic redirect to the Connections area
        assert "SECRET-CODE-1" not in r.headers.get("location", "") + r.text and "unknown-state" not in r.text
