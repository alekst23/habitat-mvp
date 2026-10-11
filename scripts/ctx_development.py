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
from ctx_acceptance import selected_criteria, validate_acceptance

TICKET_PHASES = ("design", "tests", "implementation", "browser", "review", "integrate")
EPIC_PHASES = ("docs", "epic_review", "close")
MAX_ACTIONS = 60  # Cumulative across native execution slices; never reset on a new session.
READ_ONLY_PHASES = {"browser", "review", "integrate", "epic_review", "close", "design_review"}
V2_TICKET_PHASES = ("design", "tests", "implementation", "verify", "review", "integrate")
V2_EPIC_PHASES = ("implementation", "docs", "verify", "epic_review", "close")
MAX_REPAIRS = 3
REPAIR_PHASES = {"implementation", "verify", "review", "epic_review"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def new_run(request):
    require(isinstance(request, dict) and type(request.get("version")) is int and
            request["version"] in (1, 2), "invalid request version")
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
        if request["version"] == 2:
            manifest, _ = acceptance_manifest(epic)
            criteria = selected_criteria(manifest, eid)
            require(manifest["epic"] == eid and {c["id"].split(".")[0] for c in criteria} == all_ids,
                    "manifest must cover exactly the planned tickets")
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
    if request["version"] == 2:
        for node in nodes.values():
            node.update(protocol_version=2, repairs=0)
            if node["kind"] == "epic":
                node["phase_index"] = 1  # Start with docs; implementation is only for repair.
    return {"version": request["version"], "request": deepcopy(request), "request_sha256": digest(request),
            "nodes": nodes, "required_targets": required_targets, "epic_heads": heads,
            "actions": 0, "active": None, "events": []}


def phases(node):
    if node.get("protocol_version") == 2:
        return V2_TICKET_PHASES if node["kind"] == "ticket" else V2_EPIC_PHASES
    return TICKET_PHASES if node["kind"] == "ticket" else EPIC_PHASES


def phase(node):
    if node.get("design_revision"):
        return node["design_revision"]["phase"]
    return phases(node)[node["phase_index"]]


def component(operation):
    return {"verify": "browser", "design_revision": "design", "design_review": "epic_review"}.get(operation, operation)


def source_report(run, url):
    prefix = re.escape(f"https://gitlab.com/{run['request']['project_path']}/-/")
    source = run["request"]["source_issue_iid"]
    require(isinstance(url, str) and re.fullmatch(prefix + rf"(?:issues|work_items)/{source}#note_[1-9][0-9]*", url),
            "decision/report must be on the verified source issue")


def validate_design_addendum(run, target, value, changed=True):
    """Protocol checks only; the coordinator must verify remote diff, scope and readback."""
    require(value.get("affected_targets") == [target], "cross-target design impact requires an explicit revision plan")
    require(value.get("acceptance_manifest_sha256") == scoped_manifest(run, target)[1],
            "design revision cannot change the pinned acceptance manifest")
    if changed:
        paths = value.get("changed_paths")
        eid = run["nodes"][target]["epic"]
        require(isinstance(paths, list) and paths and len(paths) == len(set(paths)), "changed design paths required")
        for path in paths:
            require(isinstance(path, str) and (re.fullmatch(r"docs/design/[a-z0-9]+(?:-[a-z0-9]+)*/(?:spec|technical|research)\.md", path)
                    or path == f"docs/plan/{eid}/{target}.md"), "design revision is limited to scoped document paths")


def invalidate_evidence(node):
    for key in ("verification", "verification_url", "review_url", "integration", "blocker_kind"):
        node.pop(key, None)


def acceptance_manifest(epic):
    raw = epic.get("acceptance_manifest")
    require(isinstance(raw, str) and raw.strip(), "exact committed acceptance manifest text required")
    manifest = json.loads(raw, object_pairs_hook=unique_object)
    require(isinstance(manifest, dict), "acceptance manifest must be an object")
    return manifest, hashlib.sha256(raw.encode()).hexdigest()


def scoped_manifest(run, target):
    eid = run["nodes"][target]["epic"]
    return acceptance_manifest(next(e for e in run["request"]["epics"] if e["state"]["epic"] == eid))


def validate_verification(run, target, sha, bundle):
    """Check actual report snapshots, not a model's 'all ACs passed' summary.

    URLs/snapshots still require independent remote readback by the supervisor.
    The acceptance validator additionally binds raw manifest bytes and every AC.
    """
    require(isinstance(bundle, dict), "verification bundle required")
    pipeline = bundle.get("pipeline_id")
    require(isinstance(pipeline, str) and re.fullmatch(r"[1-9][0-9]*", pipeline), "pipeline ID required")
    base = f"https://gitlab.com/{run['request']['project_path']}/-/"
    require(bundle.get("pipeline_url") == base + "pipelines/" + pipeline, "verification pipeline mismatch")
    expected = {"project_id": str(run["request"]["project_id"]), "source_sha": sha,
                "pipeline_id": pipeline, "scope": target}
    manifest, manifest_hash = scoped_manifest(run, target)
    criteria = selected_criteria(manifest, target)
    browser_ids = {c["id"] for c in criteria if "browser" in c["methods"]}
    names = {"ctx:verify", "ctx:acceptance"} | ({"ctx:browser"} if browser_ids else set())
    jobs = bundle.get("jobs")
    require(isinstance(jobs, dict) and names <= jobs.keys(), "required application jobs missing")
    urls = set()
    for name in names:
        job = jobs[name]
        require(isinstance(job, dict) and job.get("status") == "success", f"{name}: job not passed")
        require(job.get("allow_failure") is False, f"{name}: mandatory non-allowed-failure job required")
        require(all(job.get(k) == expected[k] for k in ("project_id", "source_sha", "pipeline_id")),
                f"{name}: stale/wrong job identity")
        url = job.get("url", "")
        require(isinstance(url, str) and re.fullmatch(re.escape(base) + r"jobs/[1-9][0-9]*", url) and url not in urls,
                "distinct same-project application job URLs required")
        urls.add(url)
    report = bundle.get("acceptance")
    require(isinstance(report, dict), "full acceptance report required")
    validate_acceptance(manifest, manifest_hash, report, expected, bundle.get("browser"))
    # Bind runtime evidence to the successful producer job, not another run's URL.
    for producer, data, method in (("ctx:verify", report, "test"),
                                   ("ctx:browser", bundle.get("browser"), "browser")):
        for row in (data or {}).get("criteria", []):
            if method not in row.get("evidence", {}):
                continue
            url = row["evidence"][method]["url"]
            job_url = jobs[producer]["url"]
            require(url == job_url or url.startswith(job_url + "/artifacts/") or url.startswith(job_url + "#"),
                    "AC evidence must link its verified producer job")


def validate_findings(run, target, findings):
    manifest, _ = scoped_manifest(run, target)
    allowed = {c["id"] for c in selected_criteria(manifest, target)}
    require(isinstance(findings, list) and findings, "actionable findings required")
    seen = set()
    prefix = re.escape(f"https://gitlab.com/{run['request']['project_path']}/-/")
    for finding in findings:
        require(isinstance(finding, dict), "invalid finding")
        fid, ids = finding.get("id"), finding.get("ac_ids")
        require(isinstance(fid, str) and fid.strip() and fid not in seen, "unique finding ID required")
        seen.add(fid)
        require(isinstance(ids, list) and ids and all(isinstance(cid, str) and cid in allowed for cid in ids)
                and len(ids) == len(set(ids)), "findings must reference in-scope ACs")
        require(isinstance(finding.get("summary"), str) and finding["summary"].strip(), "finding summary required")
        require(re.fullmatch(prefix + r"(?:jobs/[1-9][0-9]*(?:/artifacts/[^\s]+)?|(?:issues|work_items|merge_requests)/[1-9][0-9]*#note_[1-9][0-9]*)",
                             finding.get("evidence_url", "")), "same-project failure evidence required")


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
    repairable = [key for key, node in nodes.items() if node["status"] == "blocked" and
                  node.get("blocker_kind") in {"defect", "technical_design"} and node.get("repairs", MAX_REPAIRS) < MAX_REPAIRS]
    result = {"complete": complete, "mode": "serial-native-supervisor",
            "ready": [{"target": key, "phase": phase(nodes[key])} for key in frontier] if permitted else [],
            "active": run["active"], "actions_remaining": MAX_ACTIONS - run["actions"],
            "blocked": {key: n["reason"] for key, n in nodes.items() if n["status"] == "blocked"},
            "waiting": {key: [d for d in n["depends_on"] if nodes[d]["status"] != "done"]
                        for key, n in nodes.items() if n["status"] == "pending" and key not in frontier},
            "checkpoint": not complete and (not (frontier or repairable) or not permitted)}
    if run["version"] == 2:
        result["repairable"] = repairable if permitted else []
        for item in result["ready"]:
            item["component"] = component(item["phase"])
    return result


def claim(run, target):
    result = deepcopy(run)
    ready = next_actions(result)["ready"]
    require(target in {item["target"] for item in ready}, "target is not ready or run is in-flight/exhausted")
    node = result["nodes"][target]
    initial = 1 if node.get("protocol_version") == 2 and node["kind"] == "epic" else 0
    if node["phase_index"] == initial and not node.get("repairs", 0) and not node.get("started"):
        node["candidate_sha"] = result["epic_heads"][node["epic"]]
    if result["version"] == 2:
        node["started"] = True
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
    v2 = run["version"] == 2
    if v2:
        sha = receipt.get("candidate_sha", "")
        require(isinstance(sha, str) and SHA.fullmatch(sha), "candidate SHA required")
        if operation in READ_ONLY_PHASES | {"verify"}:
            require(sha == active["candidate_sha"], "review/evidence does not match delegated SHA")
    if token == "blocked":
        require(receipt.get("reason") and isinstance(receipt["reason"], str), "blocked reason required")
        require(receipt.get("blocker_kind") in ({"decision", "evidence", "ci_pending", "transient", "conflict"} |
                                               ({"defect", "technical_design"} if v2 else set())),
                "classify blocker before continuing other work")
        if v2 and receipt["blocker_kind"] in {"defect", "technical_design"}:
            allowed_phases = REPAIR_PHASES | ({"design", "tests", "design_revision", "design_review"}
                                            if receipt["blocker_kind"] == "technical_design" else set())
            require(operation in allowed_phases, "this phase cannot authorize repair")
            validate_findings(run, target, receipt.get("findings"))
            node.update(findings=deepcopy(receipt["findings"]), candidate_sha=sha)
        if v2 and receipt["blocker_kind"] == "decision" and "decisions" in receipt:
            decisions = receipt["decisions"]
            require(isinstance(decisions, list) and decisions and all(isinstance(d, dict) and
                    set(d) == {"id", "question"} and all(isinstance(d[k], str) and d[k].strip() for k in d)
                    for d in decisions), "stable decision IDs and questions required")
            require(len({d["id"] for d in decisions}) == len(decisions), "duplicate decision ID")
            node["decisions"] = deepcopy(decisions)
        if v2:
            node["candidate_sha"] = sha  # Preserve a reconciled write even when its CI is pending.
        node.update(status="blocked", reason=receipt["reason"], blocker_kind=receipt["blocker_kind"])
    else:
        sha = receipt.get("candidate_sha", "")
        require(SHA.fullmatch(sha), "candidate SHA required")
        if operation in READ_ONLY_PHASES:
            require(sha == active["candidate_sha"], "review/evidence does not match delegated SHA")
        if operation in {"design_revision", "design_review"}:
            validate_design_addendum(run, target, receipt, changed=operation == "design_revision")
            if operation == "design_revision":
                require(sha != active["candidate_sha"], "design repair must produce a new candidate SHA")
                require(set(receipt.get("resolved_findings", [])) == {f["id"] for f in node["findings"]},
                        "design repair must name all resolved findings")
                node["design_revision"].update(phase="design_review", report_url=receipt["report_url"])
            else:
                require(receipt.get("design_report_url") == node["design_revision"]["report_url"],
                        "independent design review must bind the saved addendum")
                node.pop("design_revision")
                node["phase_index"] = phases(node).index("tests" if node["kind"] == "ticket" else "implementation")
                node["design_review_url"] = receipt["report_url"]
                # A later implementation must produce a code candidate, not just reuse the document SHA.
                node["repair_from_sha"] = sha
            node["candidate_sha"] = sha
            result["events"].append(deepcopy(receipt))
            result["active"] = None
            return result
        if v2 and operation == "implementation" and "repair_from_sha" in node:
            require(sha != node["repair_from_sha"], "repair must produce a new candidate SHA")
            resolved = receipt.get("resolved_findings")
            expected_ids = {finding["id"] for finding in node["findings"]}
            require(isinstance(resolved, list) and all(isinstance(fid, str) for fid in resolved) and
                    len(resolved) == len(set(resolved)) and set(resolved) == expected_ids,
                    "repair must report all resolved findings; independent review still required")
        if v2 and operation == "verify":
            validate_verification(run, target, sha, receipt.get("verification"))
            node.update(verification=deepcopy(receipt["verification"]), verification_url=receipt["report_url"])
        if v2 and operation in {"review", "epic_review"}:
            require(node.get("verification_url") and receipt.get("verification_url") == node["verification_url"],
                    "independent review must bind current verification")
            node["review_url"] = receipt["report_url"]
        if v2 and operation == "close":
            require(node.get("review_url") and receipt.get("review_url") == node["review_url"],
                    "close must bind independent whole-epic review")
        if operation == "integrate":
            integration = receipt.get("integration", {})
            require(integration.get("source_sha") == sha, "integration source mismatch")
            require(SHA.fullmatch(integration.get("epic_sha", "")), "integration SHA required")
            require(re.fullmatch(prefix + r"pipelines/[1-9][0-9]*", integration.get("pipeline_url", "")),
                    "integration pipeline required")
            require(integration.get("review_url") == node.get("review_url"), "independent review mismatch")
            if v2:
                validate_verification(run, target, integration["epic_sha"], integration.get("verification"))
                require(integration["pipeline_url"] == integration["verification"]["pipeline_url"],
                        "integration verification pipeline mismatch")
            result["epic_heads"][node["epic"]] = integration["epic_sha"]
            node["integration"] = integration
        if operation == "review":
            node["review_url"] = receipt["report_url"]
        if operation == "docs" or (v2 and operation == "implementation" and node["kind"] == "epic"):
            result["epic_heads"][target] = sha
        node["candidate_sha"] = sha
        node["phase_index"] += 1
        if node["phase_index"] == len(phases(node)):
            node["status"] = "done"
    result["events"].append(deepcopy(receipt))
    result["active"] = None
    return result


def repair(run, target):
    """Reopen only an evidenced in-scope defect; never widen authority or reset budgets."""
    next_actions(run)
    require(run["version"] == 2, "legacy runs require reconciled resume, not an implicit upgrade")
    require(run["active"] is None and run["actions"] < MAX_ACTIONS, "active work or action budget exhausted")
    node = run["nodes"][target]
    require(node["status"] == "blocked" and node.get("blocker_kind") in {"defect", "technical_design"},
            "only actionable code/test/AC defects permit automatic repair")
    require(node["repairs"] < MAX_REPAIRS, "repair budget exhausted; persist checkpoint")
    result = deepcopy(run)
    node = result["nodes"][target]
    technical = node["blocker_kind"] == "technical_design"
    node.update(status="pending", reason="", repairs=node["repairs"] + 1,
                phase_index=phases(node).index("implementation"), repair_from_sha=node["candidate_sha"])
    if technical:
        node["design_revision"] = {"phase": "design_revision"}
    invalidate_evidence(node)
    result["events"].append({"repair": target})
    return result


def resume_decision(run, target, receipt):
    """Resume only after answers were saved in scope; independent design review comes next.

    This receipt is not authorization: the coordinator must independently read the
    user's answer and committed diff. New scope/changed ACs require a separate plan.
    """
    next_actions(run)
    require(run["version"] == 2 and run["active"] is None and run["actions"] < MAX_ACTIONS,
            "decision resume needs an idle version-2 journal with remaining actions")
    node = run["nodes"][target]
    require(node["status"] == "blocked" and node.get("blocker_kind") == "decision" and node.get("decisions"),
            "resume requires a recorded decision blocker")
    require(node["repairs"] < MAX_REPAIRS, "repair budget exhausted")
    answers = receipt.get("answers")
    require(isinstance(answers, list) and len(answers) == len(node["decisions"]), "all recorded answers required")
    require(all(isinstance(a, dict) and set(a) == {"id", "question", "answer", "source_url"} and
                all(isinstance(v, str) and v.strip() for v in a.values()) for a in answers), "invalid answer")
    expected = {d["id"]: d["question"] for d in node["decisions"]}
    require(len({a.get("id") for a in answers}) == len(answers) and {a.get("id") for a in answers} == set(expected),
            "answer IDs do not match the recorded questions")
    for answer in answers:
        require(answer.get("question") == expected[answer["id"]] and isinstance(answer.get("answer"), str)
                and answer["answer"].strip(), "answer question mismatch or empty answer")
        source_report(run, answer.get("source_url"))
    sha = receipt.get("candidate_sha", "")
    require(isinstance(sha, str) and SHA.fullmatch(sha) and sha != node["candidate_sha"], "answer must be applied at a new SHA")
    source_report(run, receipt.get("report_url"))
    require(receipt.get("report_readback") is True, "answer application readback required")
    validate_design_addendum(run, target, receipt)
    result = deepcopy(run)
    node = result["nodes"][target]
    node.update(status="pending", reason="", candidate_sha=sha, repairs=node["repairs"] + 1,
                design_revision={"phase": "design_review", "report_url": receipt["report_url"]},
                findings=[{"id": a["id"]} for a in answers], started=True)
    invalidate_evidence(node)
    result["events"].append({"decision_resume": target, "receipt": deepcopy(receipt)})
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
        if set(event) == {"repair"}:
            expected = repair(expected, event["repair"])
        elif set(event) == {"retry", "observation_url"}:
            expected = retry(expected, event["retry"], event["observation_url"])
        elif set(event) == {"decision_resume", "receipt"}:
            expected = resume_decision(expected, event["decision_resume"], event["receipt"])
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
    parser.add_argument("action", choices=("init", "next", "claim", "record", "retry", "repair", "resume-decision"))
    parser.add_argument("journal", type=Path)
    parser.add_argument("input", nargs="?", help="request/receipt path, or target ID")
    parser.add_argument("--observation-url")
    parser.add_argument("--receipt", type=Path, help="saved decision application receipt for resume-decision")
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
                elif args.action == "repair":
                    run = repair(run, args.input)
                elif args.action == "resume-decision":
                    require(args.receipt is not None, "decision receipt path required")
                    run = resume_decision(run, args.input, read_json(args.receipt))
            if args.action != "next":
                save_json(path, run)
            print(json.dumps(next_actions(run), indent=2))
    except (Invalid, RoutingError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
