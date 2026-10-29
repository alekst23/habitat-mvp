"""Scoped SQLite persistence for the nonproduction durable runtime.

This repository records state; the coordinator owns transitions and dispatch.
Payloads are ordinary JSON, not encrypted storage. All mutations accepting a
connection participate in the caller's transaction and never commit on their own.
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import json
import uuid

from aicl.control.errors import AiclError
from aicl.db import from_iso, to_iso


STATUSES = frozenset({"queued", "running", "waiting_owner", "blocked", "paused", "completed", "failed", "cancelled"})
_COUNTERS = frozenset({"owner_cursor", "applied_cursor", "decision_count", "action_count", "draft_count", "invalid_count"})
_CHANGES = _COUNTERS | {"status", "reason", "limits_json"}
_CONTENT_LIMIT = 2_000_000
_IDENTITY_NAMESPACE = uuid.UUID("a1de7b1f-194d-4098-b14d-423cd51f5506")


def canonical(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        size = len(encoded.encode("utf-8"))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise AiclError("validation_failed", "Content must be bounded JSON.") from None
    if size > _CONTENT_LIMIT:
        raise AiclError("validation_failed", "Content exceeds the stored payload limit.")
    return encoded


def _digest(encoded):
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _key(value, name):
    if not isinstance(value, str) or not value or len(value) > 240 or any(ord(char) < 32 for char in value):
        raise AiclError("validation_failed", f"A bounded {name} is required.")
    return value


def _transaction(conn):
    if not conn.in_transaction:
        raise RuntimeError("Agent storage mutation requires the caller's transaction")


class Repository:
    def __init__(self, db, clock):
        self.db, self.clock = db, clock

    def _auth(self, auth):
        if auth.expires_at <= self.clock.now():
            raise AiclError("unauthenticated", "Sign in to continue.")

    def owned_run(self, conn, auth, run_id):
        self._auth(auth)
        row = conn.execute("SELECT r.* FROM agent_run r JOIN agent_instance i ON i.id=r.instance_id "
                           "WHERE r.id=? AND r.tenant_id=? AND r.owner_id=? "
                           "AND i.tenant_id=r.tenant_id AND i.owner_id=r.owner_id",
                           (run_id, auth.tenant_id, auth.owner_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "Agent run not found.")
        return dict(row)

    def _put(self, conn, auth, run_id, kind, payload, identity=None):
        """Private bootstrap writer; caller has validated either run or instance."""
        _transaction(conn)
        _key(kind, "content kind")
        encoded = canonical(payload)
        digest = _digest(encoded)
        if identity is None:
            ref = str(uuid.uuid4())
        else:
            _key(identity, "content identity")
            ref = str(uuid.uuid5(_IDENTITY_NAMESPACE, canonical([auth.tenant_id, auth.owner_id, run_id, kind, identity])))
        prior = conn.execute("SELECT * FROM agent_content WHERE id=?", (ref,)).fetchone()
        if prior is not None:
            if ((prior["tenant_id"], prior["owner_id"], prior["run_id"], prior["kind"]) !=
                    (auth.tenant_id, auth.owner_id, run_id, kind) or prior["payload_json"] != encoded):
                raise AiclError("conflict", "Content identity already belongs to different input.")
            return ref
        conn.execute("INSERT INTO agent_content(id,tenant_id,owner_id,run_id,kind,payload_json,digest,created_at) "
                     "VALUES (?,?,?,?,?,?,?,?)", (ref, auth.tenant_id, auth.owner_id, run_id, kind, encoded, digest, to_iso(self.clock.now())))
        return ref

    def put_content(self, conn, auth, run_id, kind, payload, identity=None):
        self.owned_run(conn, auth, run_id)
        return self._put(conn, auth, run_id, kind, payload, identity)

    def get_content(self, conn, auth, run_id, ref):
        self.owned_run(conn, auth, run_id)
        row = conn.execute("SELECT payload_json,digest FROM agent_content "
                           "WHERE id=? AND tenant_id=? AND owner_id=? AND run_id=?",
                           (ref, auth.tenant_id, auth.owner_id, run_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "Agent content not found.")
        if _digest(row["payload_json"]) != row["digest"]:
            raise AiclError("unavailable", "Stored content failed its integrity check.")
        return json.loads(row["payload_json"])

    def create_run(self, auth, instance_id, request_key, definition, limits):
        self._auth(auth)
        _key(request_key, "request key")
        if not isinstance(definition, dict) or not isinstance(limits, dict):
            raise AiclError("validation_failed", "Definition and limits must be objects.")
        digest = _digest(canonical({"definition": definition, "limits": limits}))
        with self.db.transaction() as conn:
            instance = conn.execute("SELECT id FROM agent_instance WHERE id=? AND tenant_id=? AND owner_id=?",
                                    (instance_id, auth.tenant_id, auth.owner_id)).fetchone()
            if instance is None:
                raise AiclError("not_found", "Agent not found.")
            prior = conn.execute("SELECT * FROM agent_run WHERE tenant_id=? AND instance_id=? AND request_key=?",
                                 (auth.tenant_id, instance_id, request_key)).fetchone()
            if prior is not None:
                row = self.owned_run(conn, auth, prior["id"])
                if row["request_digest"] != digest:
                    raise AiclError("conflict", "Request key already belongs to different input.")
                return row
            run_id, now = str(uuid.uuid4()), to_iso(self.clock.now())
            definition_ref = self._put(conn, auth, run_id, "definition", definition, "definition")
            checkpoint_ref = self._put(conn, auth, run_id, "checkpoint", {
                "plan": {}, "memory": {}, "artifacts": {}, "question": None, "completed_artifacts": []}, "checkpoint:1")
            conn.execute("INSERT INTO agent_run(id,tenant_id,owner_id,instance_id,request_key,request_digest,definition_ref,"
                         "checkpoint_ref,status,limits_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,'queued',?,?,?)",
                         (run_id, auth.tenant_id, auth.owner_id, instance_id, request_key, digest, definition_ref,
                          checkpoint_ref, canonical(limits), now, now))
            self._wakeup(conn, run_id, 1, now)
            return self.owned_run(conn, auth, run_id)

    @staticmethod
    def _wakeup(conn, run_id, version, now):
        conn.execute("INSERT INTO agent_wakeup(run_id,generation,available_at) VALUES (?,?,?) "
                     "ON CONFLICT(run_id) DO UPDATE SET generation=excluded.generation,available_at=excluded.available_at",
                     (run_id, version, now))

    def claim(self, auth, run_id, worker_id, lease_seconds=30):
        _key(worker_id, "worker identity")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise AiclError("validation_failed", "Lease duration must be between 1 and 3600 seconds.")
        with self.db.transaction() as conn:
            run = self.owned_run(conn, auth, run_id)
            if run["status"] not in ("queued", "running"):
                raise AiclError("invalid_transition", "This run is not available for execution.")
            now = self.clock.now()
            if run["lease_owner"] and from_iso(run["lease_until"]) > now and run["lease_owner"] != worker_id:
                raise AiclError("conflict", "Another worker holds this run's lease.")
            wakeup = conn.execute("SELECT available_at FROM agent_wakeup WHERE run_id=?", (run_id,)).fetchone()
            if run["status"] == "queued" and wakeup and from_iso(wakeup[0]) > now:
                raise AiclError("denied", "This run is not due yet.")
            changed = conn.execute("UPDATE agent_run SET status='running',lease_owner=?,lease_until=?,fence=fence+1,updated_at=? "
                                   "WHERE id=? AND fence=? AND version=?",
                                   (worker_id, to_iso(now + timedelta(seconds=lease_seconds)), to_iso(now), run_id,
                                    run["fence"], run["version"])).rowcount
            if changed != 1:
                raise AiclError("conflict", "Run ownership changed.")
            conn.execute("DELETE FROM agent_wakeup WHERE run_id=?", (run_id,))
            return self.owned_run(conn, auth, run_id)

    def check_fence(self, conn, auth, run_id, worker_id, fence):
        run = self.owned_run(conn, auth, run_id)
        if (run["status"] != "running" or run["lease_owner"] != worker_id or run["fence"] != fence
                or run["lease_until"] is None or from_iso(run["lease_until"]) <= self.clock.now()):
            raise AiclError("conflict", "Worker lease is stale or no longer active.")
        return run

    def renew(self, conn, auth, run_id, worker_id, fence, lease_seconds):
        """Lease bookkeeping must not supersede a decision's semantic version."""
        _transaction(conn)
        self.check_fence(conn, auth, run_id, worker_id, fence)
        conn.execute("UPDATE agent_run SET lease_until=? WHERE id=? AND fence=?",
                     (to_iso(self.clock.now() + timedelta(seconds=lease_seconds)), run_id, fence))

    def save_checkpoint(self, conn, auth, run, checkpoint, changes):
        _transaction(conn)
        current = self.owned_run(conn, auth, run["id"])
        if current["version"] != run["version"] or current["fence"] != run["fence"]:
            raise AiclError("conflict", "Run state changed.", current_version=current["version"])
        if not isinstance(checkpoint, dict) or not isinstance(changes, dict) or not set(changes).issubset(_CHANGES):
            raise AiclError("validation_failed", "Supply a checkpoint and supported run changes.")
        values = dict(changes)
        if "status" in values and (not isinstance(values["status"], str) or values["status"] not in STATUSES):
            raise AiclError("validation_failed", "Unsupported run state.")
        if "reason" in values and values["reason"] is not None and (not isinstance(values["reason"], str) or len(values["reason"]) > 4000):
            raise AiclError("validation_failed", "Run reason exceeds its bound.")
        for key in _COUNTERS & values.keys():
            if type(values[key]) is not int or values[key] < current[key]:
                raise AiclError("validation_failed", "Run counters must be monotonic nonnegative integers.")
        if values.get("applied_cursor", current["applied_cursor"]) > values.get("owner_cursor", current["owner_cursor"]):
            raise AiclError("validation_failed", "Applied owner cursor exceeds received messages.")
        if "limits_json" in values:
            try:
                limits = json.loads(values["limits_json"]) if isinstance(values["limits_json"], str) else values["limits_json"]
            except (ValueError, TypeError):
                raise AiclError("validation_failed", "Run limits must be an object.") from None
            if not isinstance(limits, dict):
                raise AiclError("validation_failed", "Run limits must be an object.")
            values["limits_json"] = canonical(limits)
        version, now = current["version"] + 1, to_iso(self.clock.now())
        ref = self._put(conn, auth, run["id"], "checkpoint", checkpoint, f"checkpoint:{version}")
        values.update(checkpoint_ref=ref, version=version, updated_at=now)
        assignments = ",".join(f"{key}=?" for key in values)
        changed = conn.execute(f"UPDATE agent_run SET {assignments} WHERE id=? AND version=? AND fence=?",
                               (*values.values(), run["id"], current["version"], current["fence"])).rowcount
        if changed != 1:
            raise AiclError("conflict", "Run state changed.")
        updated = self.owned_run(conn, auth, run["id"])
        if updated["status"] in ("queued", "running"):
            self._wakeup(conn, run["id"], version, now)
        else:
            conn.execute("DELETE FROM agent_wakeup WHERE run_id=?", (run["id"],))
        return updated

    def append_event(self, conn, auth, run_id, kind, payload, request_key):
        _transaction(conn)
        self.owned_run(conn, auth, run_id)
        _key(kind, "event kind")
        _key(request_key, "event request key")
        encoded = canonical(payload)
        prior = conn.execute("SELECT * FROM agent_event WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
        if prior is not None:
            saved = self.get_content(conn, auth, run_id, prior["payload_ref"])
            if prior["kind"] != kind or canonical(saved) != encoded:
                raise AiclError("conflict", "Event request key already belongs to different input.")
            return dict(prior) | {"payload": saved}
        sequence = conn.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM agent_event WHERE run_id=?", (run_id,)).fetchone()[0]
        ref = self._put(conn, auth, run_id, "event", payload)
        event = {"id": str(uuid.uuid4()), "run_id": run_id, "sequence": sequence, "kind": kind,
                 "request_key": request_key, "payload_ref": ref, "created_at": to_iso(self.clock.now())}
        conn.execute("INSERT INTO agent_event(id,run_id,sequence,kind,request_key,payload_ref,created_at) VALUES (?,?,?,?,?,?,?)",
                     tuple(event.values()))
        return event | {"payload": json.loads(encoded)}

    def events(self, conn, auth, run_id, after=0):
        self.owned_run(conn, auth, run_id)
        if type(after) is not int or after < 0:
            raise AiclError("validation_failed", "Event cursor must be a nonnegative integer.")
        rows = conn.execute("SELECT * FROM agent_event WHERE run_id=? AND sequence>? ORDER BY sequence", (run_id, after)).fetchall()
        return [dict(row) | {"payload": self.get_content(conn, auth, run_id, row["payload_ref"])} for row in rows]

    def steps(self, conn, auth, run_id):
        self.owned_run(conn, auth, run_id)
        return [dict(row) for row in conn.execute("SELECT * FROM agent_step WHERE run_id=? ORDER BY sequence", (run_id,))]

    def release(self, auth, run_id, worker_id, fence):
        with self.db.transaction() as conn:
            run = self.owned_run(conn, auth, run_id)
            if run["fence"] != fence or run["lease_owner"] not in (None, worker_id):
                raise AiclError("conflict", "Worker lease is stale or no longer active.")
            if run["lease_owner"] is None:
                return run
            status, now = ("queued" if run["status"] == "running" else run["status"]), to_iso(self.clock.now())
            conn.execute("UPDATE agent_run SET status=?,lease_owner=NULL,lease_until=NULL,updated_at=? WHERE id=? AND fence=?",
                         (status, now, run_id, fence))
            if status == "queued":
                self._wakeup(conn, run_id, run["version"], now)
            else:
                conn.execute("DELETE FROM agent_wakeup WHERE run_id=?", (run_id,))
            return self.owned_run(conn, auth, run_id)
