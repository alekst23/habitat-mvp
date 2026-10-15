"""Read-only native handoff codec and resume selector; no dispatch or authority.

The caller retrieves complete notes and verifies authors, authorization, session
ownership and repository evidence. This module checks consistency, not their truth.
The payload wraps existing closure/journal state; it is not a second progress DB.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import sys

import ctx_development as dev
import ctx_design_closure as closure
from ctx_execution_budget import admission
from ctx_workflow import validate_checkpoint_exclusions

MARKER = "CTX_OWNER_HANDOFF_V1_BEGIN"
END = "CTX_OWNER_HANDOFF_V1_END"
LEGACY_MARKER = "<!-- ctx-owner-handoff:v1 -->"
LEGACY_END = "<!-- /ctx-owner-handoff -->"
PROJECT_ID = 87329027
EXCLUSIONS = Path(__file__).resolve().parents[1] / ".gitlab/ctx/checkpoint-exclusions.json"
require = closure.require


def validate(value):
    require(isinstance(value, dict) and type(value.get("version")) is int and value["version"] == 1,
            "invalid native handoff version")
    objective = value.get("objective")
    require(isinstance(objective, dict), "missing approved objective")
    require(objective.get("project_id") == PROJECT_ID and objective.get("project_path") == closure.PROJECT,
            "wrong project")
    require(type(objective.get("source_issue_iid")) is int and objective["source_issue_iid"] > 0,
            "invalid source issue")
    epic = objective.get("epic", "")
    require(isinstance(epic, str) and re.fullmatch(r"E[1-9][0-9]*", epic), "invalid epic")
    require(objective.get("branch") == "ctx/epic-i" + epic[1:], "wrong epic branch")
    require(isinstance(objective.get("run_id"), str) and
            re.fullmatch(r"[A-Za-z0-9_-]{1,64}", objective["run_id"]), "invalid objective run ID")
    require(objective.get("mode") in {"execute", "design-closure"}, "explicit objective mode required")
    require(closure.nonempty(objective.get("goal")), "missing objective text")
    closure.note_url(objective.get("authorization_url"), objective["source_issue_iid"])
    tickets = objective.get("ticket_ids")
    require(tickets is None or (isinstance(tickets, list) and tickets and
            all(isinstance(t, str) and re.fullmatch(epic + r"-[1-9][0-9]*", t) for t in tickets)
            and len(tickets) == len(set(tickets))), "invalid ticket-only scope")
    require(isinstance(objective.get("exclusions"), list) and objective["exclusions"] and
            all(closure.nonempty(x) for x in objective["exclusions"]), "scope exclusions required")
    record = value.get("closure")
    require(isinstance(record, dict), "full closure record required, including its history")
    closure_result = closure.assess(record, record["candidate_sha"])
    for key in ("project_id", "source_issue_iid", "epic", "branch"):
        require(record[key] == objective[key], "closure/objective identity mismatch")
    returns = value.get("closure_returns")
    require(isinstance(returns, list), "closure worker return receipts required")
    for receipt in returns:
        require(isinstance(receipt, dict) and isinstance(receipt.get("reservation"), dict) and
                closure.sha(receipt.get("result_sha")), "invalid closure worker return")
        closure.note_url(receipt.get("report_url"), objective["source_issue_iid"])
    journal = value.get("journal")
    if journal is not None:
        require(objective["mode"] == "execute", "design-only objective cannot carry execution")
        require(closure_result["design_complete"], "execution requires a completed baseline closure")
        dev.verify_journal(journal)
        request = journal["request"]
        require(str(request["project_id"]) == str(objective["project_id"]) and
                all(request[k] == objective[k] for k in ("project_path", "source_issue_iid", "run_id")),
                "journal/objective identity mismatch")
        require(len(request["epics"]) == 1, "native owner handoff supports one explicit epic")
        entry = request["epics"][0]
        require(entry["state"]["epic"] == epic and entry["branch"] == objective["branch"] and
                entry.get("ticket_ids") == tickets, "journal widens or changes objective scope")
        require(entry["design_sha"] == record["candidate_sha"], "journal design baseline differs from closure")
    session = value.get("session")
    require(isinstance(session, dict) and type(session.get("session_id")) is int and session["session_id"] > 0,
            "actual session identity required")
    admission(session.get("started_at"), session.get("started_at"), delegations=session.get("delegations"))
    require(isinstance(value.get("resources"), list), "full owned-resource manifest required")
    # Keep decisions and their provenance even when they are queued, not applied.
    decisions = value.get("decisions")
    require(isinstance(decisions, list), "decision ledger required")
    seen = set()
    for item in decisions:
        require(isinstance(item, dict) and all(closure.nonempty(item.get(k)) for k in
                ("id", "question", "answer", "source_url")), "incomplete recorded answer")
        require(item["id"] not in seen, "conflicting decision identities")
        seen.add(item["id"])
        closure.note_url(item["source_url"], objective["source_issue_iid"])
        require(item.get("state") in {"acknowledged", "queued", "saved", "reviewed"}, "unknown answer state")
        require(isinstance(item.get("targets"), list) and item["targets"] and
                all(t == epic or (isinstance(t, str) and re.fullmatch(epic + r"-[1-9][0-9]*", t))
                    for t in item["targets"]), "answer target mismatch")
        if item["state"] in {"saved", "reviewed"}:
            require(closure.sha(item.get("saved_sha")), "saved answer needs artifact SHA")
    return value


def render(value):
    validate(value)
    # Keep HTML in free text safe from the same note transport. Visible framing
    # lives on separate lines, so marker text inside JSON strings cannot collide.
    encoded = json.dumps(value, sort_keys=True, indent=2).replace("<", "\\u003c")
    return f"{MARKER}\n\n```json\n{encoded}\n```\n\n{END}"


def marker_lines(body):
    require(isinstance(body, str), "note body must be text")
    return [(i, line.strip()) for i, line in enumerate(body.splitlines())
            if line.strip().startswith(("CTX_OWNER_HANDOFF_", "<!-- ctx-owner-handoff:",
                                        "<!-- /ctx-owner-handoff"))]


def decode_block(encoded):
    require(encoded.startswith("```json\n") and encoded.endswith("\n```"), "malformed native handoff")
    return validate(json.loads(encoded[8:-4], object_pairs_hook=dev.unique_object))


def parse(body):
    markers = marker_lines(body)
    require([text for _, text in markers] in ([MARKER, END], [LEGACY_MARKER, LEGACY_END]),
            "missing or ambiguous native handoff")
    begin, end = (index for index, _ in markers)
    return decode_block("\n".join(body.splitlines()[begin + 1:end]).strip())


def parse_legacy(body):
    """Explicit migration only, after select verifies the caller-selected note."""
    require(not marker_lines(body), "marked handoffs must use ordinary parsing")
    lines = body.splitlines()
    fences = [i for i, line in enumerate(lines) if line.strip().startswith(("```", "~~~"))]
    require(len(fences) == 2, "legacy note requires exactly one fenced JSON block")
    return decode_block("\n".join(lines[fences[0]:fences[1] + 1]).strip())


def select(notes, *, source_issue_iid, epic, trusted_author_ids, legacy_note_ids=None):
    """Select complete caller-read notes; never fall back past a broken newer record.

    Notes must come from the verified source item, with server IDs/URLs, after
    pagination, with server-returned author_id. The caller obtains trusted writer
    IDs from verified registration/session evidence, never note-body claims.
    Untrusted authors cannot inject or poison state. This offline filter cannot
    authenticate caller-supplied metadata or grant authority to a trusted writer.
    Legacy notes require agent-owned migration, not a fresh run or user log copying.
    """
    require(isinstance(notes, list), "source notes must be a list")
    require(isinstance(trusted_author_ids, list) and trusted_author_ids and
            all(type(i) is int and i > 0 for i in trusted_author_ids), "verified trusted writer IDs required")
    legacy_ids = [] if legacy_note_ids is None else legacy_note_ids
    require(isinstance(legacy_ids, list) and all(type(i) is int and i > 0 for i in legacy_ids) and
            len(legacy_ids) == len(set(legacy_ids)), "invalid/duplicate legacy note IDs")
    policy = validate_checkpoint_exclusions(dev.read_json(EXCLUSIONS))
    applicable = policy["source_issue_iid"] == source_issue_iid and policy["epic"] == epic
    excluded = []
    migrated = set()
    candidates, ids = [], set()
    for note in notes:
        require(isinstance(note, dict) and type(note.get("id")) is int and note["id"] > 0 and
                note["id"] not in ids and isinstance(note.get("body"), str), "invalid/duplicate source note")
        ids.add(note["id"])
        closure.note_url(note.get("url"), source_issue_iid)
        require(note["url"].endswith(f"#note_{note['id']}"), "note URL/ID mismatch")
        require(type(note.get("author_id")) is int and note["author_id"] > 0, "server note author ID required")
        if applicable and note["id"] in policy["note_ids"]:
            require(note["author_id"] == policy["author_id"] and note["author_id"] in trusted_author_ids,
                    "excluded checkpoint writer mismatch")
            require(note["id"] not in legacy_ids, "excluded checkpoint cannot be migrated")
            excluded.append({"note_id": note["id"], "url": note["url"],
                             "reason": policy["reason"], "evidence_url": policy["evidence_url"]})
            continue
        if note["author_id"] not in trusted_author_ids:
            require(note["id"] not in legacy_ids, "legacy note must have a verified trusted writer")
            continue
        if note["id"] in legacy_ids:
            value = parse_legacy(note["body"])
            migrated.add(note["id"])
        elif marker_lines(note["body"]):
            value = parse(note["body"])
        else:
            continue
        require(value["objective"]["source_issue_iid"] == source_issue_iid and
                value["objective"]["epic"] == epic, "handoff source/epic mismatch")
        candidates.append((note["id"], note["url"], value))
    require(migrated == set(legacy_ids), "selected legacy note not found")
    if not candidates:
        require(not excluded, "excluded checkpoints require the original valid run, never initialize over them")
        return {"action": "reconcile_legacy", "reason": "read existing notes/artifacts; preserve history, never initialize over it"}
    candidates.sort(key=lambda row: row[0])
    for prior, current in zip(candidates, candidates[1:]):
        validate_continuation(prior[2], current[2])
    _, url, value = candidates[-1]
    require(not excluded or value["objective"]["run_id"] == policy["run_id"],
            "checkpoint exclusion belongs to a different original run")
    return {"action": "resume", "source_url": url, "handoff": deepcopy(value),
            "excluded_notes": excluded, "reconciliation_required": True, "next": next_action(value)}


def validate_continuation(old, new):
    require(old["objective"] == new["objective"], "competing or changed objective; reconcile authorization, not newest-note wins")
    for key in ("repairs", "research_attempts", "reconciliations"):
        before, after = old["closure"].get(key, []), new["closure"].get(key, [])
        require(after[:len(before)] == before, "closure history or budget was reset")
    before, after = old["closure_returns"], new["closure_returns"]
    require(after[:len(before)] == before, "closure return receipts lost")
    active = old["closure"].get("active")
    if active and new["closure"].get("active") != active:
        reconciled = any(r["reservation"] == active for r in new["closure"].get("reconciliations", []))
        if active["kind"] == "repair":
            completed = any(r["base_sha"] == active["base_sha"] for r in
                            new["closure"]["repairs"][len(old["closure"]["repairs"]):])
        else:
            completed = any(r["reservation"] == active and r["result_sha"] == new["closure"]["candidate_sha"]
                            for r in new["closure_returns"][len(old["closure_returns"]):])
        require(reconciled or completed, "active closure work lost without a result or reconciliation")
    if old["journal"] is not None:
        require(new["journal"] is not None and old["journal"]["request"] == new["journal"]["request"],
                "pinned journal/request lost")
        before, after = old["journal"]["events"], new["journal"]["events"]
        require(after[:len(before)] == before and new["journal"]["actions"] >= old["journal"]["actions"],
                "journal history or budget was reset")
    if old["session"]["session_id"] == new["session"]["session_id"]:
        require(old["session"]["started_at"] == new["session"]["started_at"] and
                new["session"]["delegations"] >= old["session"]["delegations"], "session budget was reset")
    require(new["resources"][:len(old["resources"])] == old["resources"], "owned-resource history lost")
    answers = {d["id"]: d for d in new["decisions"]}
    for decision in old["decisions"]:
        require(decision["id"] in answers and all(answers[decision["id"]][k] == decision[k]
                for k in ("question", "answer", "source_url", "targets")), "settled answer lost or changed")
        states = ("acknowledged", "queued", "saved", "reviewed")
        require(states.index(answers[decision["id"]]["state"]) >= states.index(decision["state"]),
                "answer application state regressed")


def next_action(value):
    """Recompute work, ignoring cached prose 'next' instructions or claimed success."""
    validate(value)
    journal, record = value["journal"], value["closure"]
    if journal is not None:
        action = dev.next_actions(journal)["owner_action"]
    else:
        result = closure.assess(record, record["candidate_sha"])
        action = {"action": result["action"], "finding_ids": result["finding_ids"]}
        if result["action"] == "complete" and value["objective"]["mode"] == "execute":
            action = {"action": "execution_preflight"}  # Historical evidence/enablement still required.
    pending = [d for d in value["decisions"] if d["state"] in {"acknowledged", "queued"}]
    if pending and action["action"] != "reconcile_active":
        return {"action": "reconcile_answers", "decisions": deepcopy(pending)}
    if action["action"] in {"request_decision", "resolve_decisions"}:
        action["instruction"] = "check prior authorized answers first; ask only unanswered product questions with a recommendation"
    return action


def recover_closure(value, observation, report_url):
    """Apply the existing terminal recovery transition, preserving the owner handoff."""
    validate(value)
    require(value["journal"] is None, "execution claims require attributed journal receipts, not closure restart")
    result = deepcopy(value)
    result["closure"] = closure.reconcile_interrupted(value["closure"], observation, report_url)
    validate_continuation(value, result)
    validate(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("render", "parse", "next", "resume", "recover-closure"))
    parser.add_argument("input", type=Path)
    parser.add_argument("--source-issue", type=int)
    parser.add_argument("--epic")
    parser.add_argument("--trusted-author-id", type=int, action="append", dest="trusted_author_ids")
    parser.add_argument("--legacy-note-id", type=int, action="append", dest="legacy_note_ids",
                        help="Explicit verified marker-stripped checkpoint to migrate (resume only)")
    parser.add_argument("--observation", type=Path)
    parser.add_argument("--report-url")
    args = parser.parse_args()
    try:
        require(args.legacy_note_ids is None or args.action == "resume", "legacy migration requires resume")
        if args.action == "parse":
            result = parse(args.input.read_text())
        else:
            value = dev.read_json(args.input)
            if args.action == "render":
                print(render(value))
                return 0
            if args.action == "resume":
                require(args.source_issue is not None and args.epic is not None, "verified source/epic required")
                result = select(value, source_issue_iid=args.source_issue, epic=args.epic,
                                trusted_author_ids=args.trusted_author_ids, legacy_note_ids=args.legacy_note_ids)
            elif args.action == "recover-closure":
                require(args.observation is not None, "actual terminal observation required")
                result = recover_closure(value, dev.read_json(args.observation), args.report_url)
            else:
                result = next_action(value)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, TypeError, KeyError, IndexError, AttributeError) as exc:
        print(json.dumps({"action": "reconcile_state", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
