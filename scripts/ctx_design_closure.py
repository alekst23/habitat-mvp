"""Design closure assessment; no network, execution, or approval authority."""
import argparse
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
                and repair["base_sha"] != repair["result_sha"], "invalid repair receipt")
        note_url(repair.get("report_url"), source)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--current-sha", required=True)
    args = parser.parse_args()
    try:
        result = assess(json.loads(args.record.read_text(), object_pairs_hook=unique_object), args.current_sha)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(f"CTX design closure rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
