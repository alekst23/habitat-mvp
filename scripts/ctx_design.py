"""Read-only structural validation of generated design handoffs (not approval)."""
import argparse
from functools import cache
import json
from pathlib import Path
import re

from ctx_acceptance import selected_criteria
from ctx_workflow import ready_wave


SCENARIO = r"[A-Z][A-Za-z0-9_-]*-S[1-9][0-9]*"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read(root, name):
    require(isinstance(name, str), "path must be text")
    path = Path(name)
    require(not path.is_absolute() and ".." not in path.parts and path.parts and
            path.parts[0] == "docs", f"invalid document path: {name}")
    candidate = root / path
    require(not any(p.is_symlink() for p in (candidate, *candidate.parents)),
            f"symlink document path: {name}")
    require(candidate.is_file() and candidate.resolve().is_relative_to(root.resolve()),
            f"missing/unsafe document path: {name}")
    require(candidate.stat().st_size <= 1024 * 1024, f"oversized document: {name}")
    return candidate.read_text()


def validate_epic(root, directory, ready=False):
    root, directory = Path(root).absolute(), Path(directory)
    relative = directory.relative_to(root).as_posix() if directory.is_absolute() else directory.as_posix()
    root = root.resolve()
    require(re.fullmatch(r"docs/plan/E[1-9][0-9]*", relative), "invalid epic directory")

    def document(name):
        value = json.loads(read(root, f"{relative}/{name}.json"), object_pairs_hook=unique_object)
        require(isinstance(value, dict), f"{name} must be an object")
        return value

    state = document("state")
    graph = ready_wave(state)
    epic = state["epic"]
    require(relative.endswith("/" + epic) and state["version"] == 2, "epic directory/identity mismatch")
    tickets = {t["id"]: t for t in state["tickets"]}

    @cache
    def ancestors(tid):
        direct = set(tickets[tid]["depends_on"])
        return direct | {a for d in direct for a in ancestors(d)}

    @cache
    def wave(tid):
        return 1 + max((wave(d) for d in tickets[tid]["depends_on"]), default=0)

    for tid, ticket in tickets.items():
        if "wave" in ticket:
            require(type(ticket["wave"]) is int and ticket["wave"] == wave(tid),
                    f"incorrect recorded wave: {tid}; expected {wave(tid)}")
    # Planning is allowed to save scope before Design exists. Once either design
    # artifact is present, the complete handoff must be structurally consistent.
    has_design = (root / relative / "design.json").exists()
    has_manifest = (root / relative / "acceptance.json").exists()
    if not has_design and not has_manifest:
        require(not ready, "design pending")
        return {"epic": epic, "status": "planning_only", "implementation_ready": False}
    design, manifest = document("design"), document("acceptance")
    require(type(design.get("version")) is int and design.get("version") in {1, 2} and
            design.get("epic") == epic and manifest.get("epic") == epic,
            "design/acceptance epic identity mismatch")
    require(design.get("status") in {"draft", "specified"}, "invalid design status")
    criteria = selected_criteria(manifest, epic)
    by_ac = {c["id"]: c for c in criteria}
    scenarios, technical_paths = set(), set()
    features = design.get("features")
    require(isinstance(features, list) and features, "features required")
    feature_ids, feature_scenarios = set(), []
    index = read(root, "docs/design/README.md")
    for feature in features:
        require(isinstance(feature, dict), "feature must be an object")
        if design["version"] == 2:
            fid = feature.get("id")
            require(isinstance(fid, str) and re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", fid)
                    and fid not in feature_ids, "invalid/duplicate feature identity")
            feature_ids.add(fid)
            require(isinstance(feature.get("purpose"), str) and feature["purpose"].strip(),
                    f"feature purpose required: {fid}")
            require(feature.get("spec") == f"docs/design/{fid}/spec.md", f"invalid feature spec path: {fid}")
            if feature.get("technical"):
                require(feature["technical"] == f"docs/design/{fid}/technical.md",
                        f"invalid feature technical path: {fid}; link shared contracts, do not share the whole file")
            assigned = feature.get("tickets")
            require(isinstance(assigned, list) and assigned and
                    all(isinstance(t, str) and t in tickets for t in assigned) and
                    len(assigned) == len(set(assigned)), f"invalid feature tickets: {fid}")
        spec = read(root, feature["spec"])
        ids = re.findall(r"^\*\*(" + SCENARIO + r"):?\*\*:?[ \t]+", spec, re.MULTILINE)
        require(ids and len(ids) == len(set(ids)) and not (scenarios & set(ids)),
                "missing/duplicate stable scenario definitions")
        scenarios.update(ids)
        feature_scenarios.append(set(ids))
        require(feature["spec"].removeprefix("docs/design/") in index, "feature missing from design index")
        if feature.get("technical"):
            technical = read(root, feature["technical"])
            technical_paths.add(feature["technical"])
            for heading in ("Contracts", "Process topology", "Configuration"):
                require(re.search(r"^## " + heading + r"\s*$", technical, re.MULTILINE),
                        f"technical design missing {heading}")
        else:
            reason = feature.get("technical_not_applicable")
            require(isinstance(reason, str) and reason.strip(), "technical design or applicability reason required")
    mapped = set()
    for criterion in criteria:
        tid = criterion["id"].split(".")[0]
        require(tid in tickets, f"criterion belongs to unknown ticket: {tid}")
        value = criterion.get("scenario")
        require(isinstance(value, str) and value.strip(), f"scenario IDs required: {criterion['id']}")
        refs = [s.strip() for s in value.split(",")]
        require(all(re.fullmatch(SCENARIO, s) for s in refs) and len(refs) == len(set(refs)),
                f"invalid scenario mapping: {criterion['id']}")
        require(set(refs) <= scenarios, f"unknown scenario mapping: {criterion['id']}")
        mapped.update(refs)
    require(mapped == scenarios, f"unmapped spec scenarios: {sorted(scenarios - mapped)}")
    if design["version"] == 2:
        for feature, ids in zip(features, feature_scenarios):
            actual = {c["id"].split(".")[0] for c in criteria
                      if ids & {s.strip() for s in c["scenario"].split(",")}}
            require(set(feature["tickets"]) == actual,
                    f"feature ticket coverage mismatch: {feature['id']}; expected {sorted(actual)}")
    for tid, ticket in tickets.items():
        body = read(root, f"{relative}/{tid}.md")
        require(body.startswith(f"# {tid}:"), f"ticket heading mismatch: {tid}")
        owned = [cid for cid in by_ac if cid.split(".")[0] == tid]
        require(owned, f"ticket has no acceptance criteria: {tid}")
        require(all(cid in body for cid in owned), f"ticket missing AC mapping: {tid}")
        for heading in ("Solution approach", "Contracts", "Verification"):
            require(re.search(r"^## " + heading + r"\s*$", body, re.MULTILINE),
                    f"ticket missing {heading}: {tid}")
    contracts = design.get("contracts")
    require(isinstance(contracts, list), "contract inventory required")
    if not contracts:
        reason = design.get("contracts_not_applicable")
        require(isinstance(reason, str) and reason.strip(), "empty contract inventory needs applicability reason")
    seen = set()
    for contract in contracts:
        cid, owner = contract.get("id"), contract.get("owner")
        require(isinstance(cid, str) and cid and cid not in seen, "duplicate/missing contract identity")
        seen.add(cid)
        require(owner in tickets and contract.get("document") in technical_paths, "unknown contract owner/document")
        require(contract.get("status") in {"specified", "pending"} and
                contract.get("stub_phase") in {"development-design", "not_applicable"}, "invalid contract phase/status")
        consumers = contract.get("consumers")
        require(isinstance(consumers, list) and len(consumers) == len(set(consumers)), "invalid contract consumers")
        for consumer in consumers:
            require(consumer in tickets and (consumer == owner or owner in ancestors(consumer)),
                    f"missing contract dependency: {cid}, {owner} -> {consumer}")
        if ready:
            require(contract["status"] == "specified", f"contract pending: {cid}")
    wiring = design.get("wiring", {})
    target = wiring.get("ticket")
    if target is None:
        reason = wiring.get("not_applicable")
        require(not contracts and isinstance(reason, str) and reason.strip(),
                "wiring requires a ticket or justified applicability with no new contracts")
    else:
        require(target in tickets and ancestors(target) == set(tickets) - {target},
                "wiring ticket must depend transitively on all other tickets")
        wire_acs = wiring.get("criteria")
        require(isinstance(wire_acs, list) and wire_acs and
                all(c in by_ac and c.split(".")[0] == target for c in wire_acs), "invalid wiring criteria")
    decisions = design.get("decisions")
    require(isinstance(decisions, list), "decision inventory required")
    decision_ids = set()
    for decision in decisions:
        did = decision.get("id")
        require(isinstance(did, str) and did and did not in decision_ids, "duplicate/missing decision ID")
        decision_ids.add(did)
        require(decision.get("status") in {"open", "resolved"} and decision.get("owner") and
                decision.get("question"), "decision needs status, owner and question")
        require(isinstance(decision.get("blocks"), list) and set(decision["blocks"]) <= set(tickets),
                "invalid decision blocking scope")
        if ready:
            require(decision["status"] == "resolved", f"open decision: {did}")
    if ready:
        require(design["status"] == "specified", "design is still a draft")
        require(not graph["blocked"], "plan has unresolved blocked tickets")
    return {"epic": epic, "status": "structurally_valid", "scenarios": len(scenarios),
            "features": len(features),
            "feature_layout": "explicit" if design["version"] == 2 else "legacy_unclassified",
            "criteria": len(criteria), "ready_gate_passed": ready,
            "implementation_ready": False,
            "remaining": "Independent semantic design review and actual execution prerequisites remain required."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("epic", nargs="?")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--ready", action="store_true")
    args = parser.parse_args()
    if bool(args.epic) == args.all:
        parser.error("supply one epic directory or --all")
    root = args.root.resolve()
    directories = ([p for p in sorted((root / "docs/plan").glob("E[0-9]*")) if p.is_dir()]
                   if args.all else [Path(args.epic)])
    reports, failed = [], False
    for directory in directories:
        try:
            reports.append(validate_epic(root, directory, args.ready))
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
            failed = True
            reports.append({"epic": str(directory), "status": "invalid", "error": str(error)})
    legacy = [p.name for p in sorted((root / "docs/plan").glob("EPIC-*/state.json"))]
    print(json.dumps({"status": "invalid" if failed else "structurally_valid", "epics": reports,
                      "legacy_plans_not_checked": len(legacy) if args.all else 0,
                      "implementation_ready": False}, indent=2))
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
