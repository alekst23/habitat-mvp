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
MAINTENANCE_CONTEXT_PATH = ".gitlab/ctx/verification-context.json"
# Exact runtime/guide/test files for the automatic-acceptance maintenance sync.
# Not a generic workflow-edit grant: no commands, checkpoint identity, exclusions,
# application, product plan/design, manifest, provider or credential configuration.
EVIDENCE_MAINTENANCE_PATHS = frozenset({
    "AGENTS.md", "skills/ctx-project-go/SKILL.md", "skills/ctx-ci-check/SKILL.md",
    "skills/ctx-browser-check/SKILL.md",
    ".gitlab-ci.yml", ".gitlab/ci/browser.yml", ".gitlab/ci/delivery.yml",
    ".gitlab/ctx/browser-reporter.ts", MAINTENANCE_CONTEXT_PATH,
    ".gitlab/ctx/catalog.json", ".gitlab/duo/agents/ctx-project.md",
    ".gitlab/duo/agents/ctx-project.json", ".gitlab/duo/flows/ctx-development.yml",
    "scripts/ctx_ci_context.py", "scripts/ctx_acceptance.py", "scripts/ctx_development.py",
    "scripts/ctx_verify_backend.py", "scripts/ctx_workflow.py",
    "docs/development/acceptance-evidence.md", "docs/development/browser-checks.md",
    "docs/development/single-shot-development.md", "docs/development/next-action.md",
    "docs/development/automatic-acceptance.md", "docs/development/gitlab-workflow.md",
    "tests/workflow/test_ctx_ci_context.py", "tests/workflow/test_ctx_acceptance.py",
    "tests/workflow/test_ctx_development_evidence_resume.py", "tests/workflow/test_ctx_delivery.py",
    "tests/workflow/test_ctx_workflow.py", "tests/workflow/test_ctx_verify_backend.py",
    "tests/workflow/test_ctx_agents.py", "tests/workflow/test_ctx_native_execution.py",
})


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
            if item["phase"] == "integrate" and nodes[item["target"]].get("integration_reconciliation"):
                item.update(mode="read-only-reconciliation",
                            recovery_report_url=nodes[item["target"]]["integration_reconciliation"]["report_url"])
    result["owner_action"] = owner_action(run, result)
    return result


def owner_action(run, frontier):
    """Derived dispatch advice, never authorization or proof of remote evidence.

    Prioritize recovery and bounded repairs; only ask questions when no ready work
    remains. Do not change serialized nodes/events: old journals must still replay.
    """
    if frontier["active"]:
        return {"action": "reconcile_active", "claim": deepcopy(frontier["active"])}
    if frontier["complete"]:
        return {"action": "complete"}
    if frontier["actions_remaining"] <= 0:
        return {"action": "checkpoint", "reason": "cumulative action budget exhausted"}
    if frontier.get("repairable"):
        return {"action": "repair", "target": frontier["repairable"][0]}
    if frontier["ready"]:
        item = frontier["ready"][0]
        return {"action": "delegate", **item, "component": component(item["phase"])}
    blocked = [(key, run["nodes"][key]) for key in run["required_targets"]
               if run["nodes"][key]["status"] == "blocked"]
    for target, node in blocked:
        if integration_blocker(run, target) is not None:
            return {"action": "reconcile_integration", "target": target,
                    "reason": node["reason"]}
        if evidence_blocker(run, target) is not None:
            return {"action": "reconcile_evidence", "target": target,
                    "reason": node["reason"]}
    for target, node in blocked:
        if node.get("blocker_kind") in {"transient", "ci_pending"} and node["retries"] < 1:
            return {"action": "reconcile_retry", "target": target,
                    "reason": node["reason"]}
    questions = []
    for target, node in blocked:
        if node.get("blocker_kind") == "decision":
            pending = pending_decisions(run, target)
            if not pending:
                return {"action": "reconcile_blocker", "target": target,
                        "reason": "recover exact current question and prior answers from source evidence"}
            questions.extend({"target": target, **d} for d in pending)
    if questions:
        return {"action": "resolve_decisions", "questions": questions}
    if blocked and all(n.get("blocker_kind") in {"defect", "technical_design", "transient", "ci_pending"}
                       for _, n in blocked):
        return {"action": "checkpoint", "reason": "repair/retry budget exhausted; retain findings and attempts"}
    return {"action": "reconcile_blocker", "targets": [t for t, _ in blocked],
            "reason": "inspect missing evidence, dependencies or access; do not ask the user to diagnose"}


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
    if active["phase"] == "integrate" and node.get("integration_reconciliation"):
        active.update(mode="read-only-reconciliation",
                      recovery_report_url=node["integration_reconciliation"]["report_url"])
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
            if node.get("integration_reconciliation"):
                require(integration == node["integration_reconciliation"]["integration"],
                        "read-only integration must bind the already observed merge and verification")
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
            node.pop("integration_reconciliation", None)
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


def pending_decisions(run, target):
    """Read the current blocker, not legacy cached questions from earlier attempts.

    Keep serialized nodes/events unchanged so existing v2 journals still replay.
    A prose-only blocker needs explicit question reconciliation, never old answers.
    """
    node = run["nodes"][target]
    if node["status"] != "blocked" or node.get("blocker_kind") != "decision":
        return []
    for event in reversed(run["events"]):
        if event.get("target") == target:
            return deepcopy(event.get("decisions", [])) if event.get("blocker_kind") == "decision" else []
    return []


def resume_decision(run, target, receipt):
    """Resume only after answers were saved in scope; independent design review comes next.

    This receipt is not authorization: the coordinator must independently read the
    user's answer and committed diff. New scope/changed ACs require a separate plan.
    """
    next_actions(run)
    require(run["version"] == 2 and run["active"] is None and run["actions"] < MAX_ACTIONS,
            "decision resume needs an idle version-2 journal with remaining actions")
    node = run["nodes"][target]
    decisions = pending_decisions(run, target)
    require(decisions, "resume requires a recorded decision blocker")
    require(node["repairs"] < MAX_REPAIRS, "repair budget exhausted")
    answers = receipt.get("answers")
    require(isinstance(answers, list) and len(answers) == len(decisions), "all recorded answers required")
    require(all(isinstance(a, dict) and set(a) == {"id", "question", "answer", "source_url"} and
                all(isinstance(v, str) and v.strip() for v in a.values()) for a in answers), "invalid answer")
    expected = {d["id"]: d["question"] for d in decisions}
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


def evidence_blocker(run, target):
    """Return the latest eligible blocker, never a stale cached node field."""
    if run["version"] != 2 or target not in run["required_targets"]:
        return None
    node = run["nodes"][target]
    if node["status"] != "blocked" or node.get("blocker_kind") != "evidence" or phase(node) != "verify":
        return None
    event = next((e for e in reversed(run["events"]) if e.get("target") == target), None)
    if (event and event.get("phase") == "verify" and event.get("blocker_kind") == "evidence"
            and event.get("candidate_sha") == node["candidate_sha"]):
        return event
    return None


def integration_blocker(run, target):
    """Only a ticket stopped at integration, with its saved current-SHA review."""
    if run["version"] != 2 or target not in run["required_targets"]:
        return None
    node = run["nodes"][target]
    if (node["kind"] != "ticket" or node["status"] != "blocked" or
            node.get("blocker_kind") != "evidence" or phase(node) != "integrate"):
        return None
    blocked = next((e for e in reversed(run["events"]) if e.get("target") == target), None)
    review = next((e for e in reversed(run["events"]) if e.get("target") == target and
                   e.get("phase") == "review" and e.get("report_url") == node.get("review_url")), None)
    if (blocked and blocked.get("phase") == "integrate" and blocked.get("blocker_kind") == "evidence"
            and blocked.get("candidate_sha") == node["candidate_sha"] and review
            and review.get("candidate_sha") == node["candidate_sha"] and review.get("report_readback") is True
            and node.get("verification_url") and review.get("verification_url") == node["verification_url"]
            and normalize_response(review.get("response", ""), {"ready", "blocked"})["routing_token"] == "ready"):
        return blocked
    return None


def validate_evidence_maintenance(run, target, receipt):
    """Bind adoption to separately authorized/reviewed maintenance already saved.

    remote_readback attests the coordinator checked the real current branch head,
    old-to-new ancestry/merge, COMPLETE diff and exact changed paths, unchanged raw
    pinned manifest, an independent approved review of reviewed_sha, and the human
    maintenance authorization referenced on the source issue. If context changes,
    read its full saved content and run the reviewed resolver at the new SHA too.
    JSON alone cannot authenticate any of these facts or authorize the maintenance.
    """
    update = receipt.get("candidate_update")
    fields = {"previous_sha", "reviewed_sha", "changed_paths", "acceptance_manifest_sha256",
              "review_url", "authorization_url", "remote_readback"}
    require(isinstance(update, dict) and set(update) in (fields, fields | {"verification_context"}),
            "reviewed maintenance candidate update required")
    previous = run["nodes"][target]["candidate_sha"]
    require(update["previous_sha"] == previous and update["reviewed_sha"] == receipt["candidate_sha"]
            and receipt["candidate_sha"] != previous, "maintenance previous/reviewed SHA mismatch")
    paths = update["changed_paths"]
    require(isinstance(paths, list) and paths and all(isinstance(p, str) and p in EVIDENCE_MAINTENANCE_PATHS for p in paths)
            and len(paths) == len(set(paths)), "maintenance needs unique exact allowlisted changed paths")
    require(update["acceptance_manifest_sha256"] == scoped_manifest(run, target)[1],
            "maintenance cannot change the pinned acceptance manifest")
    prefix = re.escape(f"https://gitlab.com/{run['request']['project_path']}/-/")
    require(isinstance(update["review_url"], str) and re.fullmatch(
        prefix + r"merge_requests/[1-9][0-9]*#note_[1-9][0-9]*", update["review_url"]),
        "maintenance review must be an independently verified same-project MR note")
    source_report(run, update["authorization_url"])
    require(int(update["authorization_url"].rsplit("#note_", 1)[1]) < int(receipt["report_url"].rsplit("#note_", 1)[1]),
            "maintenance authorization must precede the recovery report, not authorize itself")
    require(update["remote_readback"] is True, "maintenance diff, ancestry, authority and independent review readback required")
    context_changed = MAINTENANCE_CONTEXT_PATH in paths
    require(("verification_context" in update) == context_changed,
            "changed verification context requires its exact saved contents")
    if context_changed:
        context = update["verification_context"]
        expected = {"version": 1, "project_id": str(run["request"]["project_id"]),
                    "epic": run["nodes"][target]["epic"], "scope": target}
        require(isinstance(context, dict) and context == expected and type(context.get("version")) is int,
                "maintenance verification context must preserve the blocked project/epic/target")


def resume_evidence(run, target, receipt):
    """Reopen verification after fresh evidence, without refunding or skipping work.

    The supervisor must fetch actual CI/artifacts, confirm the current remote head,
    and publish/read back the recovery report. This checks receipt consistency only;
    note/pipeline IDs bound freshness to recorded history, not unobserved remote state.
    No application code, manifest, authority or budget changes are authorized here.
    A new candidate needs a separately reviewed, exact-path maintenance receipt.
    """
    next_actions(run)
    require(run["version"] == 2 and run["active"] is None and run["actions"] < MAX_ACTIONS,
            "evidence resume needs an idle version-2 journal with remaining actions")
    blocked = evidence_blocker(run, target)
    require(blocked is not None, "resume requires an in-scope evidence-blocked verify receipt")
    fields = {
        "run_id", "target", "phase", "blocked_attempt", "blocked_report_url", "candidate_sha",
        "report_url", "report_readback", "verification"}
    require(isinstance(receipt, dict) and set(receipt) in (fields, fields | {"candidate_update"}),
            "invalid evidence resume receipt fields")
    for key, expected in (("run_id", run["request"]["run_id"]), ("target", target), ("phase", "verify"),
                          ("blocked_report_url", blocked["report_url"])):
        require(receipt.get(key) == expected, f"evidence resume identity mismatch: {key}")
    require(type(receipt["blocked_attempt"]) is int and receipt["blocked_attempt"] == blocked["attempt"],
            "evidence resume must bind the current blocked attempt")
    source_report(run, receipt["report_url"])
    require(receipt["report_readback"] is True, "saved evidence recovery report readback required")
    require(isinstance(receipt["candidate_sha"], str) and SHA.fullmatch(receipt["candidate_sha"]), "candidate SHA required")
    if "candidate_update" in receipt:
        validate_evidence_maintenance(run, target, receipt)
    else:
        require(receipt["candidate_sha"] == run["nodes"][target]["candidate_sha"],
                "changed candidate requires separately reviewed maintenance")
    validate_verification(run, target, receipt["candidate_sha"], receipt["verification"])

    require_fresh_recovery(run, target, receipt["report_url"], receipt["verification"]["pipeline_id"])

    result = deepcopy(run)
    node = result["nodes"][target]
    node.update(status="pending", reason="", candidate_sha=receipt["candidate_sha"])
    if node["kind"] == "epic" and "candidate_update" in receipt:
        result["epic_heads"][target] = receipt["candidate_sha"]
    invalidate_evidence(node)
    result["events"].append({"evidence_resume": target, "receipt": deepcopy(receipt)})
    return result


def require_fresh_recovery(run, target, report_url, pipeline_id):
    """Reject reused note/pipeline identities, including issue/work-item aliases."""
    note_ids, pipeline_ids = [], []
    for event in run["events"]:
        prior = event["receipt"] if set(event) in ({"decision_resume", "receipt"}, {"evidence_resume", "receipt"},
                                                  {"integration_resume", "receipt"}) else event
        if "report_url" in prior:
            note_ids.append(int(prior["report_url"].rsplit("#note_", 1)[1]))
        if prior.get("target") != target:
            continue
        integration = prior.get("integration")
        bundles = [prior.get("verification"), integration.get("verification") if isinstance(integration, dict) else None]
        for bundle in bundles:
            if isinstance(bundle, dict) and re.fullmatch(r"[1-9][0-9]*", str(bundle.get("pipeline_id", ""))):
                pipeline_ids.append(int(bundle["pipeline_id"]))
    require(int(report_url.rsplit("#note_", 1)[1]) > max(note_ids, default=0),
            "fresh source report required; stale/replayed note refused")
    require(int(pipeline_id) > max(pipeline_ids, default=0),
            "fresh verification pipeline required; stale/replayed evidence refused")


def resume_integration(run, target, receipt):
    """Reconcile an already completed human merge, never request/perform another.

    remote_readback and ownership_verified record the coordinator's actual MR,
    head/ancestry, CI/artifact and exclusive-session observations. JSON consistency
    cannot authenticate those facts, prove independent review or grant merge authority.
    Only a subsequent claimed read-only integration receipt may complete the ticket.
    """
    next_actions(run)
    require(run["version"] == 2 and run["active"] is None and run["actions"] < MAX_ACTIONS,
            "integration resume needs an idle version-2 journal with remaining actions")
    blocked = integration_blocker(run, target)
    require(blocked is not None, "resume requires an evidence-blocked ticket integration with current independent review")
    require(isinstance(receipt, dict) and set(receipt) == {
        "run_id", "target", "phase", "blocked_attempt", "blocked_report_url", "candidate_sha",
        "report_url", "report_readback", "remote_readback", "ownership_verified", "merge_request", "integration"},
        "invalid integration resume receipt fields")
    node = run["nodes"][target]
    for key, expected in (("run_id", run["request"]["run_id"]), ("target", target), ("phase", "integrate"),
                          ("blocked_report_url", blocked["report_url"]), ("candidate_sha", node["candidate_sha"])):
        require(receipt[key] == expected, f"integration resume identity mismatch: {key}")
    require(type(receipt["blocked_attempt"]) is int and receipt["blocked_attempt"] == blocked["attempt"],
            "integration resume must bind the current blocked attempt")
    source_report(run, receipt["report_url"])
    require(receipt["report_readback"] is True and receipt["remote_readback"] is True and
            receipt["ownership_verified"] is True, "actual saved report, merged MR and exclusive ownership readback required")
    mr, integration = receipt["merge_request"], receipt["integration"]
    require(isinstance(mr, dict) and set(mr) == {"url", "project_id", "state", "source_branch", "target_branch",
                                               "source_sha", "merge_sha", "target_head_sha"}, "full merged MR observation required")
    require(isinstance(integration, dict) and set(integration) == {
        "source_sha", "epic_sha", "pipeline_url", "review_url", "verification"}, "full post-merge integration receipt required")
    base = f"https://gitlab.com/{run['request']['project_path']}/-/"
    require(isinstance(mr["url"], str) and re.fullmatch(re.escape(base) + r"merge_requests/[1-9][0-9]*", mr["url"])
            and mr["project_id"] == str(run["request"]["project_id"]), "same-project merged MR required")
    epic = next(e for e in run["request"]["epics"] if e["state"]["epic"] == node["epic"])
    ticket = next(t for t in epic["state"]["tickets"] if t["id"] == target)
    require(mr["state"] == "merged" and mr["source_branch"] == ticket.get("branch", f"ctx/ticket-i{node['issue_iid']}")
            and mr["target_branch"] == epic["branch"], "MR must already be merged from this ticket into its epic")
    require(mr["source_sha"] == integration["source_sha"] == node["candidate_sha"] and
            integration["review_url"] == node["review_url"], "merged source must match saved independent review")
    require(isinstance(mr["merge_sha"], str) and SHA.fullmatch(mr["merge_sha"]) and
            mr["merge_sha"] == mr["target_head_sha"] == integration["epic_sha"], "merged SHA must match the observed epic head")
    validate_verification(run, target, integration["epic_sha"], integration["verification"])
    require(integration["pipeline_url"] == integration["verification"]["pipeline_url"], "post-merge verification pipeline mismatch")
    require_fresh_recovery(run, target, receipt["report_url"], integration["verification"]["pipeline_id"])
    result = deepcopy(run)
    node = result["nodes"][target]
    node.update(status="pending", reason="", integration_reconciliation={
        "report_url": receipt["report_url"], "merge_request": deepcopy(mr), "integration": deepcopy(integration)})
    node.pop("blocker_kind", None)
    result["events"].append({"integration_resume": target, "receipt": deepcopy(receipt)})
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
        elif set(event) == {"evidence_resume", "receipt"}:
            expected = resume_evidence(expected, event["evidence_resume"], event["receipt"])
        elif set(event) == {"integration_resume", "receipt"}:
            expected = resume_integration(expected, event["integration_resume"], event["receipt"])
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
    parser.add_argument("action", choices=("init", "next", "claim", "record", "retry", "repair", "resume-decision", "resume-evidence", "resume-integration"))
    parser.add_argument("journal", type=Path)
    parser.add_argument("input", nargs="?", help="request/receipt path, or target ID")
    parser.add_argument("--observation-url")
    parser.add_argument("--receipt", type=Path, help="saved decision, evidence or integration recovery receipt")
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
                elif args.action == "resume-evidence":
                    require(args.receipt is not None, "evidence receipt path required")
                    run = resume_evidence(run, args.input, read_json(args.receipt))
                elif args.action == "resume-integration":
                    require(args.receipt is not None, "integration receipt path required")
                    run = resume_integration(run, args.input, read_json(args.receipt))
            if args.action != "next":
                save_json(path, run)
            print(json.dumps(next_actions(run), indent=2))
    except (Invalid, RoutingError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
