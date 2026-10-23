"""Durable operator-funded allowance for setup before an agent has service credit.

Reserve each provider request before I/O. Unknown outcomes retain their hold and
block further dispatch; a page read or a request retry cannot release money.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from aicl.control.errors import AiclError
from aicl.db import from_iso, to_iso

MODEL = "gpt-6-sol"
PRICE_VERSION = "gpt-6-sol-2026-10-22"
MAX_INPUT = 50000
MAX_OUTPUT = 2000
RESERVATION = MAX_INPUT * 2 + MAX_OUTPUT * 10
MAX_CALLS = 5


def allowance(db, cap):
    with db.reader() as conn:
        row = conn.execute("SELECT COALESCE(SUM(CASE WHEN state='settled' THEN cost_micro_usd ELSE 0 END),0) spent, "
                           "COALESCE(SUM(CASE WHEN state IN ('held','unknown') THEN reserved_micro_usd ELSE 0 END),0) held, "
                           "COALESCE(SUM(CASE WHEN state='unknown' OR reason='usage_exceeded_bound' THEN 1 ELSE 0 END),0) unknown "
                           "FROM assistant_inference_attempt").fetchone()
        return {"spent_micro_usd": row["spent"], "held_micro_usd": row["held"],
                "cap_micro_usd": cap, "unknown": bool(row["unknown"])}


class AssistantMeter:
    def __init__(self, ctx, auth, turn_id):
        self.db, self.clock, self.auth, self.turn_id = ctx.db, ctx.clock, auth, turn_id
        self.cap = ctx.settings.assistant_max_spend_micro_usd

    def reserve(self):
        if self.auth.expires_at <= self.clock.now():
            raise AiclError("unauthenticated", "Sign in again before asking the assistant to continue.")
        with self.db.transaction() as conn:
            conn.execute("UPDATE assistant_inference_attempt SET state='unknown',reason='interrupted',updated_at=? "
                         "WHERE state='held' AND created_at<?", (to_iso(self.clock.now()), to_iso(self.clock.now() - timedelta(minutes=5))))
        # Persist recovery even when the dispatch gate below denies the request.
        with self.db.transaction() as conn:
            # Existing turns can outlive browser session revocation; reread the
            # workspace expiry before each provider request, including migration.
            demo = conn.execute("SELECT expires_at FROM judge_demo_workspace WHERE owner_id=?",
                                (self.auth.owner_id,)).fetchone()
            if demo is not None and from_iso(demo["expires_at"]) <= self.clock.now():
                raise AiclError("denied", "This demo workspace has expired. New work is stopped.",
                                reason="judge_demo_expired")
            row = conn.execute("SELECT t.state FROM assistant_turn t JOIN assistant_session s ON s.id=t.session_id "
                               "WHERE t.id=? AND s.tenant_id=? AND s.owner_id=?",
                               (self.turn_id, self.auth.tenant_id, self.auth.owner_id)).fetchone()
            if row is None or row["state"] != "running":
                raise AiclError("conflict", "This assistant turn is no longer running.")
            usage = allowance(self.db, self.cap)
            if usage["unknown"]:
                raise AiclError("denied", "An earlier assistant request has an unresolved charge. Reconcile it before making another request.")
            if usage["spent_micro_usd"] + usage["held_micro_usd"] + RESERVATION > self.cap:
                raise AiclError("denied", "The assistant allowance has been reached. Existing agents and review controls remain available.")
            calls = conn.execute("SELECT COUNT(*) FROM assistant_inference_attempt WHERE turn_id=?", (self.turn_id,)).fetchone()[0]
            if calls >= MAX_CALLS:
                raise AiclError("denied", "This reply reached its model-call limit. Continue with a shorter follow-up.")
            attempt_id, now = str(uuid.uuid4()), to_iso(self.clock.now())
            conn.execute("INSERT INTO assistant_inference_attempt "
                         "(id,turn_id,tenant_id,owner_id,state,reserved_micro_usd,price_version,created_at,updated_at) "
                         "VALUES (?,?,?,?,'held',?,?,?,?)",
                         (attempt_id, self.turn_id, self.auth.tenant_id, self.auth.owner_id, RESERVATION, PRICE_VERSION, now, now))
            return attempt_id

    def settle(self, attempt_id, response_id, model, input_tokens, output_tokens, cached_tokens=0, cache_write_tokens=0):
        valid = (model == MODEL and isinstance(response_id, str) and 1 <= len(response_id) <= 200
                 and all(type(v) is int and v >= 0 for v in (input_tokens, output_tokens, cached_tokens, cache_write_tokens))
                 and cached_tokens == cache_write_tokens == 0)
        if not valid:
            self.fail(attempt_id, no_charge=False, reason="unrecognized_usage")
            raise AiclError("unavailable", "Provider usage could not be verified; its allowance remains reserved.")
        exceeded = input_tokens > MAX_INPUT or output_tokens > MAX_OUTPUT
        with self.db.transaction() as conn:
            changed = conn.execute("UPDATE assistant_inference_attempt SET state='settled',cost_micro_usd=?,input_tokens=?,"
                                   "output_tokens=?,response_id=?,model=?,reason=?,updated_at=? WHERE id=? AND turn_id=? AND state='held'",
                                   (input_tokens * 2 + output_tokens * 10, input_tokens, output_tokens, response_id, model,
                                    "usage_exceeded_bound" if exceeded else "", to_iso(self.clock.now()), attempt_id, self.turn_id)).rowcount
            if changed != 1:
                raise AiclError("conflict", "Provider request already settled or requires reconciliation.")
        if exceeded:
            raise AiclError("unavailable", "Provider usage exceeded its bound. Further assistant calls are stopped for review.")

    def fail(self, attempt_id, no_charge, reason):
        # Reasons are internal codes only. Never persist a raw provider exception.
        safe_reason = reason if isinstance(reason, str) and reason.replace("_", "").isalnum() and len(reason) <= 64 else "provider_error"
        with self.db.transaction() as conn:
            conn.execute("UPDATE assistant_inference_attempt SET state=?,reason=?,updated_at=? WHERE id=? AND turn_id=? AND state='held'",
                         ("rejected" if no_charge else "unknown", safe_reason, to_iso(self.clock.now()), attempt_id, self.turn_id))

    def abandon(self):
        with self.db.transaction() as conn:
            conn.execute("UPDATE assistant_inference_attempt SET state='unknown',reason='interrupted',updated_at=? "
                         "WHERE turn_id=? AND state='held'", (to_iso(self.clock.now()), self.turn_id))
