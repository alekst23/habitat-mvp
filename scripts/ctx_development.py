"""Bounded single-shot progress journal. No agent launch, network or approval authority.

The Duo supervisor executes the returned actions. Receipts constrain ordering and
identity; remote reports/CI/ancestry must still be independently read and verified.
Local flock is NOT a distributed epic lease or proof of parallel execution.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from ctx_routing import normalize_response, RoutingError
from ctx_workflow import Invalid, SHA, positive_integer, ready_wave, require, ticket_order

TICKET_PHASES = ("design", "tests", "implementation", "browser", "review", "integrate")
EPIC_PHASES = ("docs", "epic_review", "close")
MAX_ACTIONS = 60  # Reserve room below the supervisor's hard max_delegations=64.
READ_ONLY_PHASES = {"browser", "review", "integrate", "epic_review", "close"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def new_run(request):
    require(isinstance(request, dict) and request.get("version") == 1, "invalid request version")
    require(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request.get("run_id", "")), "invalid run ID")
    require(positive_integer(request.get("source_issue_iid")), "invalid source issue IID")
    path = request.get("project_path", "")
    require(re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+", path) and
            not any(p in (".", "..") for p in path.split("/")), "invalid project path")
    require(re.fullmatch(r"[1-9][0-9]*", str(request.get("project_id", ""))), "invalid project ID")
    project_url = f"https://gitlab.com/{path}"
    require(re.fullmatch(re.escape(project_url) + r"/-/automate/agent-sessions/[1-9][0-9]*",
                         request.get("session_url", "")), "missing same-project session URL")
    epics = request.get("epics")
    require(isinstance(epics, list) and epics, "explicit authorized epics required")
    nodes, heads, issues, required_targets = {}, {}, set(), []
    for epic in epics:
        state = epic["state"]
        ready_wave(state)  # Also validates cycles, evidence shape and separate IID mapping.
        require(state["version"] == 2, "migrate legacy identity before dispatch")
        require(str(state["project_id"]) == str(request["project_id"]), "project mismatch")
        eid = state["epic"]
        require(eid not in heads, "duplicate epic")
        require(epic.get("branch") == f"ctx/epic-i{state['epic_issue_iid']}", "wrong epic branch")
        for key in ("base_sha", "design_sha"):
            require(SHA.fullmatch(epic.get(key, "")), f"missing committed {key}")
        require(state["epic_issue_iid"] not in issues, "duplicate issue mapping across epics")
        issues.add(state["epic_issue_iid"])
        heads[eid] = epic["base_sha"]
        all_ids = {ticket["id"] for ticket in state["tickets"]}
        selected = epic.get("ticket_ids", [ticket["id"] for ticket in state["tickets"]])
        require(isinstance(selected, list) and selected and all(isinstance(t, str) for t in selected)
                and len(selected) == len(set(selected)) and set(selected) <= all_ids,
                "invalid explicit ticket focus")
        required_targets.extend(selected)
        for ticket in state["tickets"]:
            tid = ticket["id"]
            require(ticket["issue_iid"] not in issues, "duplicate issue mapping across epics")
            issues.add(ticket["issue_iid"])
            status = ticket["status"]
            nodes[tid] = {
                "epic": eid, "issue_iid": ticket["issue_iid"], "kind": "ticket",
                "depends_on": ticket["depends_on"], "phase_index": 0,
                "status": "done" if status == "done" else "blocked" if status != "pending" else "pending",
                "reason": "existing in-flight/blocked work; reconcile, never take over" if status in ("running", "blocked") else "",
                "candidate_sha": epic["base_sha"], "retries": 0,
            }
            if tid not in selected and status != "done":
                nodes[tid].update(status="blocked", reason="outside approved ticket focus")
        if "ticket_ids" not in epic:
            required_targets.append(eid)
            nodes[eid] = {"epic": eid, "issue_iid": state["epic_issue_iid"], "kind": "epic",
                          "depends_on": [t["id"] for t in state["tickets"]], "phase_index": 0,
                          "status": "pending", "reason": "", "candidate_sha": epic["base_sha"], "retries": 0}
    return {"version": 1, "request": deepcopy(request), "request_sha256": digest(request),
            "nodes": nodes, "required_targets": required_targets, "epic_heads": heads,
            "actions": 0, "active": None, "events": []}


def phase(node):
    return (TICKET_PHASES if node["kind"] == "ticket" else EPIC_PHASES)[node["phase_index"]]


def next_actions(run):
    require(run["request_sha256"] == digest(run["request"]), "pinned scope changed")
    nodes = run["nodes"]
    frontier = [key for key, node in nodes.items() if node["status"] == "pending" and
                all(nodes[dep]["status"] == "done" for dep in node["depends_on"])]
    frontier.sort(key=lambda key: (int(key.split("-")[0][1:]),
                                   0 if "-" in key else 1,
                                   ticket_order(key)[1] if "-" in key else 0))
    complete = all(nodes[key]["status"] == "done" for key in run["required_targets"])
    permitted = not run["active"] and run["actions"] < MAX_ACTIONS
    return {"complete": complete, "mode": "serial-native-supervisor",
            "ready": [{"target": key, "phase": phase(nodes[key])} for key in frontier] if permitted else [],
            "active": run["active"], "actions_remaining": MAX_ACTIONS - run["actions"],
            "blocked": {key: n["reason"] for key, n in nodes.items() if n["status"] == "blocked"},
            "waiting": {key: [d for d in n["depends_on"] if nodes[d]["status"] != "done"]
                        for key, n in nodes.items() if n["status"] == "pending" and key not in frontier},
            "checkpoint": not complete and (not frontier or not permitted)}


def claim(run, target):
    result = deepcopy(run)
    ready = next_actions(result)["ready"]
    require(target in {item["target"] for item in ready}, "target is not ready or run is in-flight/exhausted")
    node = result["nodes"][target]
    if node["phase_index"] == 0:
        node["candidate_sha"] = result["epic_heads"][node["epic"]]
    result["actions"] += 1
    active = {"run_id": result["request"]["run_id"], "target": target,
              "phase": phase(node), "attempt": result["actions"], "candidate_sha": node["candidate_sha"]}
    result["active"] = active
    return result


def record(run, receipt):
    next_actions(run)
    active = run["active"]
    require(active is not None, "no active delegation; inspect uncertain completion before retrying")
    for key in ("run_id", "target", "phase", "attempt"):
        require(receipt.get(key) == active[key], f"receipt identity mismatch: {key}")
    target, operation = active["target"], active["phase"]
    allowed = {"more", "complete", "blocked"} if operation == "integrate" else {"ready", "blocked"}
    token = normalize_response(receipt.get("response", ""), allowed)["routing_token"]
    request = run["request"]
    prefix = re.escape(f"https://gitlab.com/{request['project_path']}/-/")
    require(re.fullmatch(prefix + rf"(?:issues|work_items)/{request['source_issue_iid']}#note_[1-9][0-9]*",
                         receipt.get("report_url", "")), "report must be on verified source issue")
    require(receipt.get("report_readback") is True, "saved report readback required")
    result = deepcopy(run)
    node = result["nodes"][target]
    if token == "blocked":
        require(receipt.get("reason") and isinstance(receipt["reason"], str), "blocked reason required")
        require(receipt.get("blocker_kind") in {"decision", "evidence", "ci_pending", "transient", "conflict"},
                "classify blocker before continuing other work")
        node.update(status="blocked", reason=receipt["reason"], blocker_kind=receipt["blocker_kind"])
    else:
        sha = receipt.get("candidate_sha", "")
        require(SHA.fullmatch(sha), "candidate SHA required")
        if operation in READ_ONLY_PHASES:
            require(sha == active["candidate_sha"], "review/evidence does not match delegated SHA")
        if operation == "integrate":
            integration = receipt.get("integration", {})
            require(integration.get("source_sha") == sha, "integration source mismatch")
            require(SHA.fullmatch(integration.get("epic_sha", "")), "integration SHA required")
            require(re.fullmatch(prefix + r"pipelines/[1-9][0-9]*", integration.get("pipeline_url", "")),
                    "integration pipeline required")
            require(integration.get("review_url") == node.get("review_url"), "independent review mismatch")
            result["epic_heads"][node["epic"]] = integration["epic_sha"]
            node["integration"] = integration
        if operation == "review":
            node["review_url"] = receipt["report_url"]
        if operation == "docs":
            result["epic_heads"][target] = sha
        node["candidate_sha"] = sha
        node["phase_index"] += 1
        phases = TICKET_PHASES if node["kind"] == "ticket" else EPIC_PHASES
        if node["phase_index"] == len(phases):
            node["status"] = "done"
    result["events"].append(deepcopy(receipt))
    result["active"] = None
    return result


def retry(run, target, observation_url):
    """One reconciled retry of a wait/transient failure; never automatic code repair."""
    next_actions(run)
    require(run["active"] is None, "do not retry in-flight work")
    node = run["nodes"][target]
    require(node["status"] == "blocked" and node.get("blocker_kind") in {"ci_pending", "transient"},
            "decision/evidence/conflict needs a human-reconciled resume")
    require(node["retries"] < 1, "retry budget exhausted")
    prefix = re.escape(f"https://gitlab.com/{run['request']['project_path']}/-/")
    require(re.fullmatch(prefix + r"(?:pipelines/[1-9][0-9]*|(?:issues|work_items)/[1-9][0-9]*#note_[1-9][0-9]*)",
                         observation_url), "fresh same-project observation required")
    result = deepcopy(run)
    result["nodes"][target].update(status="pending", reason="", retries=1)
    result["events"].append({"retry": target, "observation_url": observation_url})
    return result


def verify_journal(run):
    """Rebuild derived progress on load; edited status fields cannot skip phases.

    Replay proves protocol consistency, not the truth of remote evidence receipts.
    """
    expected = new_run(run["request"])
    require(isinstance(run["events"], list) and len(run["events"]) <= MAX_ACTIONS * 2,
            "invalid journal history size")
    for event in run["events"]:
        if set(event) == {"retry", "observation_url"}:
            expected = retry(expected, event["retry"], event["observation_url"])
        else:
            expected = record(claim(expected, event["target"]), event)
    if run["active"] is not None:
        expected = claim(expected, run["active"]["target"])
    require(expected == run, "journal progress differs from replayed receipts; reconcile, never reset")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    require(not path.is_symlink(), "symlink input refused")
    return json.loads(path.read_text(), object_pairs_hook=unique_object)


@contextmanager
def journal_lock(path):
    root = Path.cwd() / ".ctx" / "development"
    path = path.absolute()
    require(".." not in path.parts and path.suffix == ".json", "invalid journal path")
    require(path.is_relative_to(root), "journal must be inside .ctx/development in coordinator checkout")
    require(all(not p.is_symlink() for p in (path, *path.parents)), "symlink journal path refused")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield path
    finally:
        os.close(lock)


def save_json(path, value):
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "next", "claim", "record", "retry"))
    parser.add_argument("journal", type=Path)
    parser.add_argument("input", nargs="?", help="request/receipt path, or target ID")
    parser.add_argument("--observation-url")
    args = parser.parse_args()
    try:
        with journal_lock(args.journal) as path:
            if args.action == "init":
                require(not path.exists(), "journal already exists; reconcile it, do not reset")
                run = new_run(read_json(Path(args.input)))
            else:
                run = read_json(path)
                verify_journal(run)
                if args.action == "claim":
                    run = claim(run, args.input)
                elif args.action == "record":
                    run = record(run, read_json(Path(args.input)))
                elif args.action == "retry":
                    run = retry(run, args.input, args.observation_url or "")
            if args.action != "next":
                save_json(path, run)
            print(json.dumps(next_actions(run), indent=2))
    except (Invalid, RoutingError, OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
