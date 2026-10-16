"""InstanceOperations and evaluate_gate_control (technical.md "Instance mutation operations", owner E11-2).

Owner-UI form operations only; never reachable through /app-tools/* or chat. Every committed change bumps
`version` and appends one audit event in the same transaction; stale expected_version => AiclError conflict
(current_version) with no effect; archived => invalid_state; unchanged value at the current version =>
changed=False with no bump and no event.
"""

from __future__ import annotations

from sqlite3 import Connection
from typing import Literal, Protocol

from aicl.control.auth import AuthContext
from aicl.control.instances import AgentInstance, LifecycleAction, Limits
from aicl.creation.models import MutationResult
from aicl.creation.service import NOT_IMPLEMENTED

GateControlResult = Literal["permits", "still_denied"]


def evaluate_gate_control(conn: Connection, instance: AgentInstance) -> GateControlResult:
    """Re-evaluate the persisted `gated_reason` with its `gate_context` (no persisted gate => permits).

    budget_*: read_budget readable, a price version effective, all four windows available > 0;
    capability_disabled: every gate_context capability enabled; connection_*: every capability has an
    active attachment on an active connection; network_denied: network.fetch enabled and network_domains
    holds a host whose sha256 prefix equals gate_context.host_hash12. A window rollover never permits.
    """
    raise NotImplementedError(NOT_IMPLEMENTED)


class InstanceOperations(Protocol):
    def set_lifecycle(self, auth: AuthContext, instance_id: str, expected_version: int,
                      action: LifecycleAction) -> MutationResult: ...

    def set_capability(self, auth: AuthContext, instance_id: str, expected_version: int,
                       capability: str, enabled: bool) -> MutationResult: ...

    def set_limits(self, auth: AuthContext, instance_id: str, expected_version: int,
                   limits: Limits) -> MutationResult: ...

    def add_network_domain(self, auth: AuthContext, instance_id: str, expected_version: int,
                           host: str) -> MutationResult: ...

    def remove_network_domain(self, auth: AuthContext, instance_id: str, expected_version: int,
                              host: str) -> MutationResult: ...

    def resolve_gate(self, auth: AuthContext, instance_id: str, expected_version: int) -> MutationResult:
        """Clears the persisted gate only when evaluate_gate_control permits (instance.gate_resolved,
        committed); otherwise AiclError denied reason=gate_unresolved (audited, outcome denied)."""
        ...

    def attach_connection(self, auth: AuthContext, instance_id: str, expected_version: int,
                          capability: str, connection_id: str) -> MutationResult: ...

    def detach_connection(self, auth: AuthContext, instance_id: str, expected_version: int,
                          capability: str) -> MutationResult: ...


class UnimplementedInstanceOperations:
    """Contract stub: every operation raises NotImplementedError until the E11-2 slices implement it."""

    def _stub(self, *_args: object, **_kwargs: object) -> MutationResult:
        raise NotImplementedError(NOT_IMPLEMENTED)

    set_lifecycle = set_capability = set_limits = add_network_domain = remove_network_domain = _stub
    resolve_gate = attach_connection = detach_connection = _stub
