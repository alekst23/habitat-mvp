"""Shared error taxonomy (technical.md "Error taxonomy"). Data and a carrier type only."""

from __future__ import annotations

# error code -> HTTP status, exactly as the taxonomy table.
ERROR_HTTP_STATUS: dict[str, int] = {
    "unauthenticated": 401,
    "not_found": 404,
    "validation_failed": 422,
    "conflict": 409,
    "invalid_transition": 409,
    "invalid_state": 409,
    "denied": 403,
    "unavailable": 503,
}

# Denial vocabulary of the gate; E11-1 raises the budget-related ones.
GATE_REASONS: tuple[str, ...] = (
    "instance_not_active", "capability_disabled", "confirmation_required", "confirmation_expired",
    "confirmation_used", "confirmation_mismatch", "connection_unavailable", "network_denied",
    "budget_exhausted", "budget_unavailable", "price_unavailable", "estimate_missing",
    "reconciliation_pending", "gate_unresolved", "check_unavailable",
)


class AiclError(Exception):
    """Structured error `{error, message, ...extra}`; `error` is a key of ERROR_HTTP_STATUS.

    `denied` carries `reason` (a GATE_REASONS value) in `extra`; `conflict` carries
    `current_version` or `existing_result_id`; `validation_failed` carries `field_errors`.
    """

    def __init__(self, error: str, message: str = "", **extra: object) -> None:
        super().__init__(error)
        self.error = error
        self.message = message
        self.extra = dict(extra)
