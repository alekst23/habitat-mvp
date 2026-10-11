"""Design closure assessment; no network, execution, or approval authority."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

PROJECT = "gitlab-ai-hackathon/transcend-october-2026/43066631/showcase"
MAX_REPAIRS = 3
MAX_RESEARCH_ATTEMPTS = 2
KINDS = {"technical", "decision", "research", "access", "enablement"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def note_url(value, source):
    require(isinstance(value, str), "missing report URL")
    parsed = urlsplit(value)
    require(parsed.scheme == "https" and parsed.netloc == "gitlab.com" and not parsed.query
            and parsed.path in {f"/{PROJECT}/-/issues/{source}", f"/{PROJECT}/-/work_items/{source}"}
            and re.fullmatch(r"note_[1-9][0-9]*", parsed.fragment), "wrong source report URL")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def assess(record, current_sha):
    """Validate a read-back record and choose work; callers must verify remote evidence.

    This does not attest reviewer independence, CI, URLs, or a remote lease. Never
    convert its result into implementation authorization or a completion receipt.
    """
    require(isinstance(record, dict) and record.get("version") == 1, "invalid closure version")
    require(record.get("mode") == "design-closure", "not a design-closure record")
    require(record.get("project_id") == 87329027, "wrong project")
    source = record.get("source_issue_iid")
    require(type(source) is int and source > 0, "invalid source issue")
    epic = record.get("epic", "")
    require(isinstance(epic, str) and re.fullmatch(r"E[1-9][0-9]*", epic), "invalid epic")
    require(record.get("branch") == "ctx/epic-i" + epic[1:], "wrong epic branch")
    require(sha(current_sha) and record.get("candidate_sha") == current_sha, "stale candidate SHA")
    require(record.get("structural_sha") is None or sha(record["structural_sha"]), "invalid structural SHA")
    repairs = record.get("repairs")
    attempts = record.get("research_attempts")
    require(isinstance(repairs, list) and len(repairs) <= MAX_REPAIRS, "invalid repair budget")
    require(isinstance(attempts, list) and len(attempts) <= 60 and all(nonempty(i) for i in attempts),
            "invalid research attempts")
    for repair in repairs:
        require(isinstance(repair, dict) and sha(repair.get("base_sha")) and sha(repair.get("result_sha"))
                and (repair["base_sha"] != repair["result_sha"] or repair.get("outcome") == "interrupted"), "invalid repair receipt")
        if "outcome" in repair:
            require(repair["outcome"] == "interrupted" and type(repair.get("session_id")) is int and repair["session_id"] > 0,
                    "invalid interrupted repair identity")
        note_url(repair.get("report_url"), source)
    reconciliations = record.get("reconciliations", [])
    require(isinstance(reconciliations, list) and len(reconciliations) <= 64, "invalid reconciliation history")
    for item in reconciliations:
        require(isinstance(item, dict) and set(item) == {"reservation", "observation", "report_url"},
                "invalid reconciliation receipt")
        reservation, observed = item["reservation"], item["observation"]
        require(isinstance(reservation, dict) and reservation.get("kind") in {"repair", "research", "review"}
                and sha(reservation.get("base_sha")) and type(reservation.get("session_id")) is int
                and reservation["session_id"] > 0, "invalid reconciled reservation")
        require(isinstance(observed, dict) and set(observed) == {"session_id", "project_id", "status", "observed_head"}
                and observed["session_id"] == reservation["session_id"] and observed["project_id"] == record["project_id"]
                and observed["status"] in {"failed", "stopped", "finished"} and sha(observed["observed_head"]),
                "invalid terminal reconciliation")
        note_url(item["report_url"], source)
        if reservation["kind"] == "repair":
            require(any(r.get("session_id") == observed["session_id"] and r["base_sha"] == reservation["base_sha"]
                        and r["result_sha"] == observed["observed_head"] and r.get("outcome") == "interrupted"
                        for r in repairs), "reconciled repair lost its consumed budget")
    review = record.get("review")
    groups = {kind: [] for kind in KINDS}
    if review is not None:
        require(isinstance(review, dict) and sha(review.get("sha")) and nonempty(review.get("reviewer")),
                "invalid independent review identity")
        note_url(review.get("report_url"), source)
        require(review.get("verdict") in {"ready", "blocked"}, "unknown review verdict")
        findings = review.get("findings")
        require(isinstance(findings, list), "missing review findings")
        ids = set()
        for item in findings:
            require(isinstance(item, dict) and all(nonempty(item.get(k)) for k in
                    ("id", "kind", "summary", "owner", "action")), "incomplete finding")
            require(item["id"] not in ids and item["kind"] in KINDS, "duplicate or unknown finding")
            ids.add(item["id"])
            tickets = item.get("tickets")
            require(isinstance(tickets, list) and tickets and len(set(tickets)) == len(tickets)
                    and all(isinstance(t, str) and re.fullmatch(epic + r"-[1-9][0-9]*", t) for t in tickets),
                    "invalid finding scope")
            if item["kind"] == "enablement":
                require(nonempty(item.get("safeguard")), "missing enablement safeguard")
            if item["kind"] == "research":
                require(all(nonempty(item.get(k)) for k in ("question", "deliverable", "fallback")),
                        "incomplete research request")
                urls = item.get("source_urls")
                require(isinstance(urls, list) and urls and all(nonempty(u) for u in urls),
                        "missing research source URLs")
            groups[item["kind"]].append(item["id"])
        blocking = any(groups[k] for k in KINDS - {"enablement"})
        require((review["verdict"] == "blocked") == blocking, "ambiguous review verdict/findings")

    def result(action, finding_ids=()):
        return {"action": action, "design_complete": action == "complete",
                "implementation_authorized": False, "finding_ids": list(finding_ids),
                "enablement_gates": groups["enablement"], "repairs_used": len(repairs)}

    active = record.get("active")
    if active is not None:
        require(isinstance(active, dict) and active.get("kind") in {"repair", "research", "review"}
                and sha(active.get("base_sha")) and isinstance(active.get("finding_ids"), list),
                "invalid active delegation")
        return result("reconcile_active")
    if record.get("structural_sha") != current_sha:
        return result("validate")
    if review is None or review["sha"] != current_sha:
        return result("review")
    research = [i for i in groups["research"] if attempts.count(i) < MAX_RESEARCH_ATTEMPTS]
    if research:
        return result("research", research)
    if groups["technical"]:
        return result("repair" if len(repairs) < MAX_REPAIRS else "checkpoint", groups["technical"])
    if groups["decision"]:
        return result("request_decision", groups["decision"])
    if groups["access"] or groups["research"]:
        return result("request_access", groups["access"] + groups["research"])
    if record.get("handoff_sha") != current_sha:
        return result("validate_handoff")
    return result("complete")


def reconcile_interrupted(record, observation, report_url):
    """Consume a failed reservation after actual remote reconciliation, never on age alone.

    The caller must read the identified session, actual head/diff, and saved report.
    This local function validates the receipt, not remote ownership or report truth.
    """
    assess(record, record["candidate_sha"])
    active = record["active"]
    require(active and type(active.get("session_id")) is int and active["session_id"] > 0,
            "resolve the reservation's actual session identity before recovery")
    require(set(observation) == {"session_id", "project_id", "status", "observed_head"} and
            observation["session_id"] == active["session_id"] and observation["project_id"] == record["project_id"] and
            observation["status"] in {"failed", "stopped", "finished"} and sha(observation["observed_head"]),
            "terminal same-project session and observed head required; unknown is not running or failed")
    note_url(report_url, record["source_issue_iid"])
    result = deepcopy(record)
    if active["kind"] == "repair":
        require(len(result["repairs"]) < MAX_REPAIRS, "repair budget exhausted; retain the unresolved reservation")
        result["repairs"].append({"base_sha": active["base_sha"], "result_sha": observation["observed_head"],
                                  "report_url": report_url, "outcome": "interrupted", "session_id": active["session_id"]})
    result.setdefault("reconciliations", []).append({"reservation": deepcopy(active),
        "observation": deepcopy(observation), "report_url": report_url})
    # Preserve outstanding questions/findings. A changed SHA makes this review stale;
    # unchanged documents may reuse their verified review after structural checks.
    result.update(active=None, candidate_sha=observation["observed_head"], structural_sha=None, handoff_sha=None)
    assess(result, result["candidate_sha"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--current-sha", required=True)
    parser.add_argument("--reconcile-session", type=Path, help="verified terminal-session observation JSON")
    parser.add_argument("--report-url", help="saved/read-back source-issue recovery report")
    args = parser.parse_args()
    try:
        record = json.loads(args.record.read_text(), object_pairs_hook=unique_object)
        if args.reconcile_session:
            observation = json.loads(args.reconcile_session.read_text(), object_pairs_hook=unique_object)
            require(observation["observed_head"] == args.current_sha, "recovery head mismatch")
            record = reconcile_interrupted(record, observation, args.report_url)
            result = {"record": record, "assessment": assess(record, args.current_sha)}
        else:
            result = assess(record, args.current_sha)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(f"CTX design closure rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
