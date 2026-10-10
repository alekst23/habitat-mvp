"""Durable, bounded controller for native Duo execution slices.

Run from a trusted controller checkout, never an agent checkout. No merges,
deployments, credential provisioning, or changes to the authorized scope.
"""
from copy import deepcopy
import hashlib
import json
import re
import time
import uuid

import ctx_development as development
from ctx_design_closure import assess, unique_object

PROJECT_ID = 87329027
PROJECT_PATH = "gitlab-ai-hackathon/transcend-october-2026/43066631/showcase"
TERMINAL = {"finished", "failed", "stopped"}
WAITING = {"paused", "input_required", "plan_approval_required", "tool_call_approval_required"}
OUTCOMES = {"continue", "complete", "needs_decision", "needs_access", "blocked"}
MARKER = "<!-- ctx-execution-checkpoint:v1 -->"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def validate_request(request):
    require(set(request) == {"version", "run_id", "project_id", "source_issue_iid", "epic_issue_iid",
                            "branch", "mode", "objective", "design_sha", "max_sessions", "max_recoveries"},
            "unexpected execution request fields")
    require(request["version"] == 1 and request["project_id"] == PROJECT_ID, "wrong version/project")
    require(isinstance(request["run_id"], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request["run_id"]),
            "invalid run ID")
    require(all(integer(request[k], 1, 2**31) for k in ("source_issue_iid", "epic_issue_iid")), "invalid issue")
    require(request["branch"] == f"ctx/epic-i{request['epic_issue_iid']}", "wrong epic branch")
    require(request["mode"] in {"execute", "design-closure"}, "unknown execution mode")
    require(isinstance(request["objective"], str) and 1 <= len(request["objective"].strip()) <= 4000,
            "explicit objective required")
    require(sha(request["design_sha"]), "pin the full approved design SHA")
    require(integer(request["max_sessions"], 1, 64) and integer(request["max_recoveries"], 0, 3),
            "session/recovery budget outside bounds")


def new_run(request):
    validate_request(request)
    return {"version": 1, "request": deepcopy(request), "request_sha256": digest(request),
            "status": "ready", "attempts": [], "recoveries": 0, "no_progress": 0, "active": None,
            "checkpoint": None, "checkpoint_sha256": None, "checkpoint_note_id": None,
            "summary": "Authorized scope saved; ready for first execution slice."}


def validate_state(state):
    validate_request(state["request"])
    require(state["version"] == 1 and digest(state["request"]) == state["request_sha256"], "request changed")
    require(state["status"] in {"ready", "running", "complete", "needs_decision", "needs_access", "blocked"},
            "unknown controller status")
    require(len(state["attempts"]) <= state["request"]["max_sessions"], "session budget changed")
    require(integer(state["recoveries"], 0, state["request"]["max_recoveries"]), "recovery budget changed")
    require(integer(state["no_progress"], 0, 2), "invalid no-progress count")
    if state["checkpoint"]:
        require(digest(state["checkpoint"]) == state["checkpoint_sha256"], "checkpoint changed")


def checkpoint_body(value):
    return MARKER + "\n```json\n" + json.dumps(value, indent=2) + "\n```"


def parse_checkpoint(body):
    require(body.count(MARKER) == 1, "ambiguous checkpoint marker")
    match = re.fullmatch(re.escape(MARKER) + r"\s*```json\s*\n(.*)\n```\s*", body, re.S)
    require(match is not None, "checkpoint must be one complete JSON record")
    return json.loads(match[1], object_pairs_hook=unique_object)


def extend_history(old, new, label):
    require(isinstance(new, list) and new[:len(old)] == old, f"{label} history was reset/rewritten")


def validate_checkpoint(value, state, session_id, head):
    """Verify protocol/identity/history; the independent reviewer still judges evidence."""
    request = state["request"]
    active = state["active"]
    require(set(value) == {"version", "run_id", "attempt_id", "request_sha256", "previous_checkpoint_sha256",
                          "session_id", "candidate_sha", "outcome", "summary", "next_action", "closure", "journal"},
            "incomplete or unknown checkpoint fields")
    require(value["version"] == 1 and value["run_id"] == request["run_id"]
            and value["attempt_id"] == active["id"] and value["session_id"] == session_id
            and value["request_sha256"] == state["request_sha256"]
            and value["previous_checkpoint_sha256"] == state["checkpoint_sha256"], "checkpoint identity mismatch")
    require(sha(head) and value["candidate_sha"] == head, "checkpoint is not current epic HEAD")
    require(value["outcome"] in OUTCOMES, "unknown checkpoint outcome")
    require(isinstance(value["summary"], str) and 1 <= len(value["summary"].split()) <= 120,
            "summary must be 1-120 words")
    require(isinstance(value["next_action"], str) and bool(value["next_action"].strip()), "next action required")
    closure = value["closure"]
    require(closure["source_issue_iid"] == request["source_issue_iid"]
            and closure["epic"] == f"E{request['epic_issue_iid']}"
            and closure["branch"] == request["branch"], "closure scope mismatch")
    design = assess(closure, closure["candidate_sha"])
    journal = value["journal"]
    previous = state["checkpoint"]
    if previous:
        for key in ("repairs", "research_attempts"):
            extend_history(previous["closure"][key], closure[key], key)
        old_active = previous["closure"]["active"]
        if old_active and old_active["kind"] == "repair":
            appended = closure["repairs"][len(previous["closure"]["repairs"]):]
            require(closure["active"] == old_active or (appended and appended[0]["base_sha"] == old_active["base_sha"]),
                    "reserved design repair cannot be discarded")
    if journal is None:
        require(closure["candidate_sha"] == head, "stale design closure")
        require(not previous or previous["journal"] is None, "execution journal discarded")
        finished = design["design_complete"] and request["mode"] == "design-closure"
        actionable = design["action"] in {"validate", "review", "research", "repair", "reconcile_active",
                                          "validate_handoff"} or (design["design_complete"] and request["mode"] == "execute")
    else:
        require(request["mode"] == "execute" and design["design_complete"], "execution before design closure")
        development.verify_journal(journal)
        pinned = journal["request"]
        require(pinned["version"] == 2 and str(pinned["project_id"]) == str(PROJECT_ID)
                and pinned["project_path"] == PROJECT_PATH and pinned["run_id"] == request["run_id"]
                and pinned["source_issue_iid"] == request["source_issue_iid"] and len(pinned["epics"]) == 1,
                "journal scope mismatch")
        epic = pinned["epics"][0]
        require(epic["branch"] == request["branch"] and epic["state"]["epic_issue_iid"] == request["epic_issue_iid"]
                and epic["design_sha"] == closure["candidate_sha"] and "ticket_ids" not in epic,
                "wrong pinned design/epic or narrowed epic scope")
        if previous and previous["journal"]:
            require(pinned == previous["journal"]["request"], "pinned execution scope changed")
            extend_history(previous["journal"]["events"], journal["events"], "execution")
            require(journal["actions"] >= previous["journal"]["actions"], "active claim budget reset")
            old_claim = previous["journal"]["active"]
            if old_claim:
                added = journal["events"][len(previous["journal"]["events"]):]
                if added:
                    require(all(added[0].get(k) == old_claim[k] for k in ("run_id", "target", "phase", "attempt")),
                            "active claim was replaced rather than reconciled")
                else:
                    require(journal["active"] == old_claim, "active claim discarded")
        progress = development.next_actions(journal)
        finished = progress["complete"]
        # Dependency waiting is NOT actionable when its prerequisite needs a decision.
        retryable = any(n["status"] == "blocked" and n.get("blocker_kind") in {"ci_pending", "transient"}
                        and n["retries"] < 1 for n in journal["nodes"].values())
        actionable = bool(progress["ready"] or progress.get("repairable") or progress["active"] or retryable)
    require(value["outcome"] != "complete" or finished, "completion lacks closed design/execution evidence")
    require(value["outcome"] != "continue" or actionable, "continue has no eligible work")
    require(value["outcome"] not in {"needs_decision", "needs_access"} or not actionable,
            "finish agent-owned work before requesting user input")


def goal_for(state):
    request, active = state["request"], state["active"]
    envelope = {"request": request, "request_sha256": state["request_sha256"],
                "attempt_id": active["id"], "previous_checkpoint_sha256": state["checkpoint_sha256"],
                "checkpoint_note_id": state["checkpoint_note_id"], "reconcile_session_id": active["reconcile_session_id"],
                "started_at": active["started_at"], "save_by": active["started_at"] + 1800}
    return (active["marker"] + "\nControlled execution slice. Read docs/development/durable-execution.md "
            "from the trusted default revision. Reconcile saved state before work; at most ONE delegation. "
            "Save/read back the structured checkpoint on the source issue and stop. No merges or deployments.\n"
            + canonical(envelope))


class Controller:
    """One short tick. Store.save is compare-and-swap; no network write is blindly retried."""
    def __init__(self, api, store, config, now=time.time):
        self.api, self.store, self.config, self.now = api, store, config, now

    def tick(self):
        state, revision = self.store.load()
        validate_state(state)
        if state["status"] not in {"ready", "running"}:
            return state
        request = state["request"]
        if state["active"] is None:
            if len(state["attempts"]) >= request["max_sessions"]:
                state.update(status="blocked", summary="Session budget exhausted; saved work retained.")
                self.store.save(state, revision)
                return state
            # Durable intent is reserved BEFORE POST. A crash after this CAS never issues a second POST.
            attempt = uuid.uuid4().hex
            last = state["attempts"][-1] if state["attempts"] else None
            state["active"] = {"id": attempt, "marker": f"[CTX:{request['run_id']}:{attempt}]",
                               "started_at": int(self.now()), "session_id": None,
                               "reconcile_session_id": last["session_id"] if last and last.get("interrupted") else None}
            state["attempts"].append(deepcopy(state["active"]))
            state["status"] = "running"
            revision = self.store.save(state, revision)
            # Unknown result stays reserved. Next tick searches by the exact attempt marker.
            session = self.api.start(goal_for(state), request, self.config)
            require(integer(session.get("id"), 1, 2**63) and session.get("project_id") == PROJECT_ID,
                    "invalid flow-start receipt; reconcile reserved dispatch")
            state["active"]["session_id"] = session["id"]
            state["attempts"][-1]["session_id"] = session["id"]
            self.store.save(state, revision)
            return state

        active = state["active"]
        sessions = self.api.sessions(active["session_id"], active["marker"])
        if not sessions:
            # An empty search is not proof that an uncertain POST did not create a flow.
            state["summary"] = "Dispatch/status not yet observable; retaining reservation, no duplicate launch."
            if self.now() - active["started_at"] > 600:
                state.update(status="blocked", summary="Uncertain dispatch/status requires reconciliation; no duplicate launch.")
            self.store.save(state, revision)
            return state
        require(len(sessions) == 1, "ambiguous session ownership; no dispatch")
        session = sessions[0]
        require(session["project_id"] == PROJECT_ID and session["goal"] == goal_for(state), "foreign session")
        require(active["session_id"] in (None, session["id"]), "session identity changed")
        active["session_id"] = session["id"]
        state["attempts"][-1]["session_id"] = session["id"]
        status = session["status"]
        if status in {"created", "running"}:
            state["summary"] = ("Session running; waiting for its durable checkpoint." if
                                self.now() - active["started_at"] <= 2700 else
                                "Session overdue; waiting for confirmed termination, never starting a concurrent writer.")
            self.store.save(state, revision)
            return state
        if status in WAITING:
            state.update(status="needs_decision", summary=f"Duo session requires input/approval ({status}); do not start another.")
            self.store.save(state, revision)
            return state
        require(status in TERMINAL, "unknown Duo session status; no dispatch")
        matches = []
        for note in self.api.notes(request["source_issue_iid"]):
            if (MARKER not in note["body"] or active["id"] not in note["body"]
                    or note["author"]["id"] not in self.config["report_author_ids"]):
                continue
            value = parse_checkpoint(note["body"])
            if value.get("run_id") == request["run_id"] and value.get("attempt_id") == active["id"]:
                matches.append((note, value))
        require(len(matches) <= 1, "ambiguous saved checkpoint; no dispatch")
        if matches:
            note, value = matches[0]
            saved = self.api.note(request["source_issue_iid"], note["id"])
            require(saved == note, "saved note changed during readback")
            validate_checkpoint(value, state, session["id"], self.api.head(request["branch"]))
            previous = state["checkpoint"]
            unchanged = previous and all(previous[k] == value[k] for k in ("closure", "journal", "candidate_sha"))
            state["no_progress"] = min(2, state["no_progress"] + 1) if unchanged and value["outcome"] == "continue" else 0
            state.update(checkpoint=value, checkpoint_sha256=digest(value), checkpoint_note_id=note["id"],
                         status="ready" if value["outcome"] == "continue" else value["outcome"], summary=value["summary"])
            if state["no_progress"] >= 2:
                state.update(status="blocked", summary="Two slices made no durable progress; inspect the retained findings before more spend.")
        else:
            # Even a 'finished' session without a receipt is interrupted, not completed work.
            if state["recoveries"] >= request["max_recoveries"]:
                state.update(status="blocked", summary="Recovery budget exhausted; inspect retained session/checkpoints.")
            else:
                state["recoveries"] += 1
                state.update(status="ready", summary="Interrupted session; next slice reconciles remote writes before resuming.")
                state["attempts"][-1]["interrupted"] = True
        state["attempts"][-1]["status"] = status
        state["active"] = None
        self.store.save(state, revision)
        return state
