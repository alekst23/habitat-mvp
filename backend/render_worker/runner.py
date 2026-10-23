"""Plan, generate through AICL, check saved criteria, and submit durable work.

The worker is a reviewed program, not a shell or arbitrary owner-code executor.
It cannot approve a purchase or capture a payment. Human waiting is persisted by
AICL; the Render task exits instead of occupying an instance until approval.
"""
from __future__ import annotations

from render_worker.client import MachineAPIError, identifier

MAX_ATTEMPTS_PER_RUN = 12


def plan_attempt(attempt):
    """Resolve the reviewed work contract from AICL's immutable snapshot."""
    spec, snapshot = attempt.get("spec"), attempt.get("snapshot")
    if not isinstance(spec, dict) or not isinstance(snapshot, dict):
        raise MachineAPIError("AICL supplied an invalid work snapshot")
    criteria = spec.get("criteria")
    if (not isinstance(criteria, list) or not 1 <= len(criteria) <= 12
            or any(not isinstance(c, str) or not c.strip() or len(c) > 500 for c in criteria)):
        raise MachineAPIError("AICL supplied invalid saved completion criteria")
    identifier(attempt.get("id"))
    return {"attempt_id": attempt["id"], "criteria": tuple(criteria)}


def validate_output(result, plan):
    """Structural checks only; model claims still require owner quality review."""
    if not isinstance(result, dict) or result.get("validation_error"):
        return {"passed": False}
    content, checks = result.get("content"), result.get("criteria")
    valid = (isinstance(content, str) and bool(content.strip()) and len(content) <= 30000
             and isinstance(checks, list) and len(checks) == len(plan["criteria"]))
    if valid:
        valid = all(isinstance(check, dict) and check.get("criterion") == expected
                    and type(check.get("passed")) is bool
                    and isinstance(check.get("reason"), str) and len(check["reason"]) <= 3000
                    for check, expected in zip(checks, plan["criteria"]))
    # A failed criterion is a valid report of unfinished work, not malformed data.
    # AICL independently checks the exact cached response and sets needs_work.
    return {"passed": bool(valid)}


def execute(client, dispatch_id, task_run_id, *, emit=lambda event: None):
    """Run one durable dispatch. Only public correlation IDs reach Render logs."""
    identifier(dispatch_id)
    identifier(task_run_id)
    current = client.claim(dispatch_id, task_run_id)
    processed = set()
    while True:
        attempts = current.get("attempts", [])
        if not isinstance(attempts, list):
            raise MachineAPIError("AICL supplied an invalid attempt list")
        for attempt in attempts:
            plan = plan_attempt(attempt)
            if plan["attempt_id"] in processed:
                raise MachineAPIError("AICL repeated an unfinished attempt")
            if len(processed) >= MAX_ATTEMPTS_PER_RUN:
                raise MachineAPIError("Render task reached its bounded work limit")
            processed.add(plan["attempt_id"])
            emit({"stage": "generate", "dispatch_id": dispatch_id, "attempt_id": plan["attempt_id"]})
            generated = client.generate(dispatch_id, task_run_id, plan["attempt_id"])
            if isinstance(generated.get("result"), dict):
                validation = validate_output(generated["result"], plan)
                client.complete_attempt(dispatch_id, task_run_id, plan["attempt_id"], validation)
                emit({"stage": "checked", "dispatch_id": dispatch_id, "passed": validation["passed"]})
            # Blocked or unresolved inference has no result. AICL retains its
            # reservation and terminal/pending state; never resend independently.
        current = client.finish(dispatch_id, task_run_id)
        if not current.get("attempts"):
            break
    return {
        "dispatch_id": dispatch_id,
        "task_run_id": task_run_id,
        "state": current.get("state", "unknown"),
        "job_ids": current.get("job_ids", []),
        "deliverable_ids": current.get("deliverable_ids", []),
    }
