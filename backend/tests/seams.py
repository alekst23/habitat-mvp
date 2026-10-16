"""E11-2 test seams: the only place tests learn how to build E11-2 services.

The committed stubs fix signatures, not constructors. Each seam takes the E11-1 `Env` and returns the service.
The implementation phase edits only the bodies of these functions. Until then a seam raises NotImplementedError,
so dependent tests fail at their first call, never at import or collection.
"""

from __future__ import annotations

NOT_WIRED = "E11-2 seam is not wired: implementation phase must construct this service here"


def instance_operations(env):
    """-> InstanceOperations (aicl.creation.operations) over env.db/clock/audit/budget."""
    from aicl.creation.operations import UnimplementedInstanceOperations
    return UnimplementedInstanceOperations()


def connection_service(env, oauth, secret_store, public_base_url="http://127.0.0.1:4173"):
    """-> ConnectionService (begin_oauth/complete_oauth/revoke_connection) over the given fake ports."""
    raise NotImplementedError(NOT_WIRED)


def revocation_sweeper(env, oauth, secret_store):
    """-> RevocationSweeper with run_once()."""
    raise NotImplementedError(NOT_WIRED)


def aes_secret_store(key: bytes):
    """-> the AES-256-GCM SecretStore built from a 32-byte key."""
    raise NotImplementedError(NOT_WIRED)


def credential_broker(env, oauth, secret_store, resolver):
    """-> CredentialBroker."""
    raise NotImplementedError(NOT_WIRED)


def work_gate(env, executor, resolver, oauth=None, secret_store=None):
    """-> WorkAuthorization wired to env.budget/confirmations/audit and the given fakes."""
    raise NotImplementedError(NOT_WIRED)


def hold_reconciler(env, executor):
    """-> HoldReconciler with run_once()."""
    raise NotImplementedError(NOT_WIRED)


def budget_audit_recorder(env):
    """-> BudgetAuditRecorder (O-1) appending through env.audit."""
    from aicl.work.gate import UnimplementedBudgetAuditRecorder
    return UnimplementedBudgetAuditRecorder()
