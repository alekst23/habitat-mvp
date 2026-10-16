"""Append-only audit log and single-use confirmations on real SQLite (F1-S13, confirmation primitives)."""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from aicl.control.audit import DETAILS_ALLOW_LIST, AuditEvent
from aicl.control.confirmation import payload_digest
from aicl.control.errors import AiclError
from support import Abort, add_pending_action, table_names


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/control/audit.py:SqliteAuditLog")
def test_audit_is_ordered_redacted_append_only_owner_scoped_and_hides_null_identity_events(build_env):
    env = build_env()
    auth, inst = env.new_instance()
    other_auth, _ = env.new_instance()
    with env.db.transaction() as conn:
        first = env.audit.append(conn, AuditEvent(
            "instance.lifecycle_changed", "owner", "committed", auth.tenant_id, auth.owner_id, inst.id,
            details={"from": "draft", "to": "active", "instructions": "SECRET-INSTRUCTIONS",
                     "token": "tok_123", "body": "message body", "payload_digest": "f" * 64}))
        second = env.audit.append(conn, AuditEvent(
            "work.denied", "gate", "denied", auth.tenant_id, auth.owner_id, inst.id, reason="budget_exhausted",
            details={"denial_reason": "budget_exhausted"}))
        env.audit.append(conn, AuditEvent(
            "auth.link_rejected", "system", "denied", None, None, details={"reason_code": "unknown", "count": 1}))
    assert first.seq is not None and first.id and first.occurred_at is not None
    assert second.seq > first.seq
    assert set(first.details) <= DETAILS_ALLOW_LIST and first.details == {"from": "draft", "to": "active"}

    listed = env.audit.list_for_instance(auth, inst.id)
    assert [e.seq for e in listed] == [second.seq, first.seq]  # newest first
    assert all(e.tenant_id == auth.tenant_id for e in listed)
    assert "SECRET-INSTRUCTIONS" not in repr(listed) and "tok_123" not in repr(listed)
    owner_events = env.audit.list_for_owner(auth, limit=100)
    assert [e.event_type for e in owner_events] == ["work.denied", "instance.lifecycle_changed"]  # no null-tenant event
    assert env.audit.list_for_owner(auth, after_seq=first.seq) == [e for e in owner_events if e.seq > first.seq]
    assert env.audit.list_for_owner(other_auth) == [] and env.audit.list_for_instance(other_auth, inst.id) == []

    # an authenticated event cannot omit its identity; only the pre-authentication types may
    with pytest.raises((AiclError, ValueError)):
        with env.db.transaction() as conn:
            env.audit.append(conn, AuditEvent("work.denied", "gate", "denied", None, None))

    # a rolled-back change leaves no event
    count_before = len(env.audit.list_for_owner(auth))
    with pytest.raises(Abort):
        with env.db.transaction() as conn:
            env.audit.append(conn, AuditEvent("instance.created", "owner", "committed", auth.tenant_id,
                                              auth.owner_id, inst.id))
            raise Abort()
    assert len(env.audit.list_for_owner(auth)) == count_before

    # database triggers abort UPDATE and DELETE
    with env.db.transaction() as conn:
        (table,) = table_names(conn, "audit")
        for sql in (f"UPDATE {table} SET outcome = 'committed'", f"DELETE FROM {table}"):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(sql)


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/control/confirmation.py:SqliteConfirmationStore")
def test_confirmation_is_bound_to_digest_expires_and_is_single_use(build_env):
    env = build_env(ttl_seconds=300)
    auth, inst = env.new_instance(capabilities=("gmail.send",))
    digest = payload_digest(inst.id, "gmail.send", {"to": "a@example.com", "body": "hi"})
    other_digest = payload_digest(inst.id, "gmail.send", {"to": "a@example.com", "body": "changed"})
    with env.db.transaction() as conn:
        pending_id = add_pending_action(conn, inst, digest)
        confirmation = env.confirmations.create_confirmation(conn, auth, pending_id)
        assert env.confirmations.create_confirmation(conn, auth, pending_id).id == confirmation.id  # idempotent
    assert confirmation.payload_digest == digest and confirmation.used_at is None
    assert confirmation.expires_at - confirmation.created_at == timedelta(seconds=300)
    assert (confirmation.tenant_id, confirmation.owner_id) == (auth.tenant_id, auth.owner_id)

    now = env.clock.now()
    with env.db.transaction() as conn:  # a different payload digest is refused and does not burn it
        assert env.confirmations.consume_confirmation(conn, confirmation.id, other_digest, now) is False
    with env.db.transaction() as conn:
        assert env.confirmations.consume_confirmation(conn, confirmation.id, digest, now) is True
    with env.db.transaction() as conn:  # single use
        assert env.confirmations.consume_confirmation(conn, confirmation.id, digest, now) is False

    # a consumption rolls back with its transaction, so it is not burned by a failed reservation
    with env.db.transaction() as conn:
        pending2 = add_pending_action(conn, inst, digest)
        second = env.confirmations.create_confirmation(conn, auth, pending2)
    with pytest.raises(Abort):
        with env.db.transaction() as conn:
            assert env.confirmations.consume_confirmation(conn, second.id, digest, now) is True
            raise Abort()
    with env.db.transaction() as conn:
        assert env.confirmations.consume_confirmation(conn, second.id, digest, now) is True

    # expiry: at or after expires_at it can no longer be consumed
    with env.db.transaction() as conn:
        pending3 = add_pending_action(conn, inst, digest)
        third = env.confirmations.create_confirmation(conn, auth, pending3)
    with env.db.transaction() as conn:
        assert env.confirmations.consume_confirmation(conn, third.id, digest, third.expires_at) is False
