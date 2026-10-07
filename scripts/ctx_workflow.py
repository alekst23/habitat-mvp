"""Local/CI checks for the CTX workflow. No network calls or deployment authority."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
STEPS = ("verify", "acceptance", "source-security", "package", "artifact-security", "configure")
IDENTITY_KEYS = ("project_id", "source_sha", "pipeline_id")
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
EPIC_ID = re.compile(r"E([1-9][0-9]*)")
TICKET_ID = re.compile(r"E([1-9][0-9]*)-([1-9][0-9]*)")
LEGACY_EPIC_ID = re.compile(r"EPIC-I([1-9][0-9]*)")
LEGACY_TICKET_ID = re.compile(r"T-I([1-9][0-9]*)")
TOOLS = {
    "read_file", "list_dir", "find_files", "grep", "get_project", "get_issue",
    "list_issues", "get_merge_request", "gitlab_merge_request_search",
    "gitlab_api_get", "create_issue_note", "create_merge_request_note",
    "create_file_with_contents", "edit_file", "run_command", "create_branch",
    "create_commit", "create_merge_request", "create_issue", "update_issue",
}
WRITE_TOOLS = {
    "create_file_with_contents", "edit_file", "run_command", "create_branch",
    "create_commit", "create_merge_request", "create_issue", "update_issue",
}


class Invalid(ValueError):
    """Malformed configuration or missing/invalid evidence; always fail closed."""


class UniqueLoader(yaml.SafeLoader):
    """Reject silently overwritten keys in safety-critical YAML."""


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise Invalid(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def read_yaml(path):
    return yaml.load(Path(path).read_text(), Loader=UniqueLoader)


def require(condition, message):
    if not condition:
        raise Invalid(message)


def matches(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def https_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def terminal_token_set(value, label):
    require(isinstance(value, list) and value and
            all(isinstance(token, str) and re.fullmatch(r"[a-z][a-z_]*", token)
                and token != "default_route" for token in value),
            f"invalid terminal tokens: {label}")
    require(len(value) == len(set(value)), f"duplicate terminal tokens: {label}")
    return set(value)


def documented_terminal_tokens(text, label, required=True):
    """Read the explicit contract, not a heuristic interpretation of prose."""
    declarations = re.findall(r"(?m)^[ \t]*Terminal tokens:[ \t]*(.*)$", text)
    if not declarations and not required:
        return None
    require(len(declarations) == 1, f"exactly one terminal token declaration required: {label}")
    try:
        value = yaml.load(declarations[0], Loader=UniqueLoader)
    except yaml.YAMLError as exc:
        raise Invalid(f"invalid terminal token declaration: {label}") from exc
    return terminal_token_set(value, label)


def validate_skill_terminal_tokens(flow, skills):
    """A reused skill may constrain outputs, but cannot add a consuming prompt's tokens."""
    for prompt in flow["prompts"]:
        system = prompt["prompt_template"]["system"]
        allowed = documented_terminal_tokens(system, prompt["prompt_id"])
        for path in re.findall(r"(?m)^[ \t]*- (skills/ctx-[a-z-]+/SKILL\.md)[ \t]*$", system):
            require(path in skills, f"missing required skill: {path}")
            tokens = documented_terminal_tokens(skills[path], path, required=False)
            if tokens is not None:
                require(tokens <= allowed,
                        f"skill terminal tokens differ from {prompt['prompt_id']}: {path}")


def validate_flow(flow, registration):
    """Validate the intentionally small v1 subset we use, not GitLab's full schema."""
    require(isinstance(flow, dict), "flow must be a mapping")
    require(set(flow) == {"version", "environment", "coding_environment", "components",
                          "prompts", "routers", "flow"}, "unsupported top-level flow fields")
    require(flow["version"] == "v1" and flow["environment"] == "ambient", "not ambient v1")
    require(flow["coding_environment"] == "full", "repository checkout required")
    components = flow["components"]
    require(isinstance(components, list) and components, "components must not be empty")
    names = [c["name"] for c in components]
    require(len(set(names)) == len(names), "duplicate component name")
    require(all(re.fullmatch(r"[a-z][a-z_]*", name) for name in names), "invalid component name")
    require(not {"end", "abort"} & set(names), "reserved component name")
    declared = registration.get("terminal_tokens")
    require(isinstance(declared, dict) and set(declared) == set(names),
            "catalog terminal tokens must cover every component exactly")
    prompts = {p["prompt_id"]: p for p in flow["prompts"]}
    require(len(prompts) == len(flow["prompts"]), "duplicate prompt id")
    used_prompts = set()
    for component in components:
        require(set(component) == {"name", "type", "prompt_id", "inputs", "toolset",
                                   "ui_log_events"}, "unsupported component fields")
        require(component["type"] == "AgentComponent", "unsupported component type")
        require(component["prompt_id"] in prompts, "missing prompt reference")
        used_prompts.add(component["prompt_id"])
        prompt = prompts[component["prompt_id"]]
        require(set(prompt) == {"prompt_id", "name", "unit_primitives", "prompt_template",
                                "params"}, "unsupported prompt fields")
        require(prompt["unit_primitives"] == [], "unexpected unit primitives")
        require(set(prompt["params"]) == {"timeout"}, "unsupported prompt params")
        template = prompt["prompt_template"]
        require(set(template) == {"system", "user", "placeholder"}, "invalid prompt template")
        require(template["placeholder"] == "history", "history placeholder missing")
        require("No further steps" in template["system"], "explicit stopping rule missing")
        inputs = component["inputs"]
        require(inputs == [{"from": "context:goal", "as": "goal"},
                           {"from": "context:project_id", "as": "project_id"}],
                "explicit goal/project inputs required")
        variables = set(re.findall(r"{{\s*(\w+)\s*}}", template["user"]))
        require(variables == {"goal", "project_id"}, "prompt/input mismatch")
        require("{{" not in template["system"], "undeclared system template variable")
        tools = component["toolset"]
        require(isinstance(tools, list) and set(tools) <= TOOLS, "unknown tool")
        require(len(tools) == len(set(tools)), "duplicate tool")
        if component["name"] in registration["read_only_components"]:
            require(not set(tools) & WRITE_TOOLS, "reviewer has execution/write tools")
    require(used_prompts == set(prompts), "orphan prompt")
    require(set(registration["read_only_components"]) <= set(names), "unknown read-only component")
    prompt_text = "\n".join(p["prompt_template"]["system"] for p in prompts.values())
    for operation in registration["operations"]:
        require(operation in prompt_text, f"missing operation contract: {operation}")

    graph = {}
    for router in flow["routers"]:
        source = router["from"]
        require(source in names and source not in graph, "unknown/duplicate router source")
        require(set(router) == {"from", "condition"}, "unconditional/unsupported router")
        condition = router["condition"]
        require(set(condition) == {"input", "routes"}, "invalid router condition")
        require(condition["input"] == f"context:{source}.final_answer", "wrong routing input")
        routes = condition["routes"]
        require(routes.get("blocked") == routes.get("default_route") == "abort",
                "blocked and unknown answers must abort")
        require(all(target in {*names, "end", "abort"} for target in routes.values()),
                "unknown routing target")
        require(any(v != "abort" for v in routes.values()), "no success route")
        component = next(c for c in components if c["name"] == source)
        documented = documented_terminal_tokens(
            prompts[component["prompt_id"]]["prompt_template"]["system"], source)
        expected = set(routes) - {"default_route"}
        require(documented == expected, f"prompt terminal tokens differ from router: {source}")
        require(terminal_token_set(declared[source], source) == expected,
                f"catalog terminal tokens differ from router: {source}")
        graph[source] = set(routes.values())
    require(set(graph) == set(names), "component without router")
    require(set(flow["flow"]) == {"entry_point"}, "unsupported flow entry fields")
    entry = flow["flow"]["entry_point"]
    require(entry in names, "missing entry point")
    visited, active = set(), set()

    def visit(name):
        if name in ("end", "abort"):
            return
        require(name not in active, "unbounded routing cycle")
        if name in visited:
            return
        active.add(name)
        for target in graph[name]:
            visit(target)
        active.remove(name)
        visited.add(name)

    visit(entry)
    require(visited == set(names), "unreachable component")


def validate_commands(config):
    require(isinstance(config, dict) and config.get("version") == 1, "invalid command version")
    require(set(config) == {"version", "commands"}, "unknown command config fields")
    require(set(config["commands"]) == set(STEPS), "command set does not match CI adapters")
    for name, command in config["commands"].items():
        require(set(command) == {"argv", "timeout_seconds"}, f"invalid command: {name}")
        argv = command["argv"]
        require(argv is None or (isinstance(argv, list) and argv and
                                all(isinstance(a, str) and a for a in argv)),
                f"{name} must use a nonempty argument array, or null for blocked")
        timeout = command["timeout_seconds"]
        require(type(timeout) is int and 0 < timeout <= 900, f"invalid timeout: {name}")


def validate_repository(root=ROOT):
    catalog = json.loads((root / ".gitlab/ctx/catalog.json").read_text())
    require(catalog["version"] == 2, "unsupported catalog version")
    actual = {str(p.relative_to(root)) for p in (root / ".gitlab/duo/flows").glob("*.yml")}
    require(actual == set(catalog["flows"]), "flow catalog and files differ")
    skill_texts = {filename: (root / filename).read_text()
                  for filename in catalog["skills"].values() if (root / filename).is_file()}
    for filename, registration in catalog["flows"].items():
        flow = read_yaml(root / filename)
        validate_flow(flow, registration)
        validate_skill_terminal_tokens(flow, skill_texts)
        prompt_text = "\n".join(p["prompt_template"]["system"] for p in flow["prompts"])
        for operation in registration["operations"]:
            skill = catalog["skills"].get(operation)
            require(skill is not None and skill in prompt_text, f"flow does not load skill: {operation}")
    operations = {op for f in catalog["flows"].values() for op in f["operations"]}
    require(set(catalog["skills"]) == operations, "skill catalog and operations differ")
    for operation, filename in catalog["skills"].items():
        require(filename == f"skills/{operation}/SKILL.md", "unexpected skill path")
        path = root / filename
        require(path.is_file(), f"missing skill: {operation}")
        parts = path.read_text().split("---", 2)
        require(len(parts) == 3 and not parts[0].strip(), f"missing skill frontmatter: {operation}")
        metadata = yaml.load(parts[1], Loader=UniqueLoader)
        require(metadata.get("name") == operation and bool(metadata.get("description")),
                f"invalid skill metadata: {operation}")
        require(bool(parts[2].strip()), f"empty skill: {operation}")
    validate_commands(read_yaml(root / ".gitlab/ctx/commands.yml"))
    config = read_yaml(root / ".gitlab/duo/agent-config.yml")
    require(config["network_policy"]["allow_all_unix_sockets"] is False,
            "unrestricted unix sockets are not allowed")
    ci = read_yaml(root / ".gitlab-ci.yml")
    jobs = read_yaml(root / ".gitlab/ci/delivery.yml")
    require(jobs[".ctx-check"]["allow_failure"] is False, "checks must block on failure")
    for i, step in enumerate(STEPS):
        job = jobs[f"ctx:{step}"]
        require(job["stage"] in ci["stages"], "CI stage missing")
        require(job["script"] == [f"python scripts/ctx_workflow.py run {step}"],
                "CI does not use evidence adapter")
        needs = {need if isinstance(need, str) else need["job"] for need in job.get("needs", [])}
        expected = {f"ctx:{s}" for s in STEPS[:i]}
        if step == "acceptance":
            expected.add("ctx:browser")
        require(needs == expected,
                f"missing evidence dependencies for {step}")
        require("environment" not in job, "deployment requires a separate reviewed adapter")
    browser = read_yaml(root / ".gitlab/ci/browser.yml")["ctx:browser"]
    require(browser["allow_failure"] is False and browser["stage"] == "verify",
            "browser execution must be a blocking verification job")
    return {"status": "passed", "flows": len(actual), "skills": len(operations),
            "scope": "local CTX contract validation; GitLab catalog/CI lint still required"}


def positive_integer(value):
    return type(value) is int and value > 0


def validate_plan_identity(state):
    """Validate project/epic/issue mappings; v1 remains readable until migrated."""
    require(isinstance(state, dict), "state must be a mapping")
    version = state.get("version")
    require(type(version) is int and version in (1, 2), "unsupported state version")
    require(re.fullmatch(r"[1-9][0-9]*", str(state.get("project_id", ""))), "invalid project ID")
    legacy = version == 1
    require(matches(LEGACY_EPIC_ID if legacy else EPIC_ID, state.get("epic")), "invalid epic ID")
    tickets = state.get("tickets")
    require(isinstance(tickets, list) and tickets, "epic must contain tickets")
    if not legacy:
        epic_iid = state.get("epic_issue_iid")
        require(positive_integer(epic_iid), "invalid epic issue IID")
        require(state["epic"] == f"E{epic_iid}", "epic ID does not match epic issue IID")
        require(positive_integer(state.get("source_issue_iid")), "invalid source issue IID")
        require(positive_integer(state.get("next_ticket_number")), "invalid next ticket number")
    seen_ids, seen_issues = set(), set()
    for ticket in tickets:
        require(isinstance(ticket, dict), "ticket must be a mapping")
        tid = ticket.get("id")
        require(matches(LEGACY_TICKET_ID if legacy else TICKET_ID, tid), "invalid ticket ID")
        require(tid not in seen_ids, "duplicate ticket ID")
        seen_ids.add(tid)
        if not legacy:
            parent, number = map(int, TICKET_ID.fullmatch(tid).groups())
            require(parent == epic_iid, f"ticket {tid} belongs to another epic")
            issue_iid = ticket.get("issue_iid")
            require(positive_integer(issue_iid), f"invalid issue IID: {tid}")
            require(issue_iid != epic_iid, "ticket issue cannot also be the epic issue")
            require(issue_iid not in seen_issues, "duplicate ticket issue IID")
            seen_issues.add(issue_iid)
            require(number < state["next_ticket_number"], "next ticket number must exceed allocated numbers")


def ticket_order(tid):
    """Sort numerically (E2-2 before E2-10), without changing assigned numbers."""
    match = TICKET_ID.fullmatch(tid) or LEGACY_TICKET_ID.fullmatch(tid)
    return tuple(map(int, match.groups()))


def ready_wave(state):
    """Pure planning: validates the graph but does not dispatch or certify remote state."""
    validate_plan_identity(state)
    tickets = state.get("tickets")
    by_id = {}
    for ticket in tickets:
        tid = ticket.get("id", "")
        require(ticket.get("status") in {"pending", "running", "blocked", "done"},
                f"invalid ticket status: {tid}")
        deps = ticket.get("depends_on")
        require(isinstance(deps, list) and all(isinstance(d, str) for d in deps),
                f"invalid dependencies: {tid}")
        pattern = LEGACY_TICKET_ID if state["version"] == 1 else TICKET_ID
        require(all(matches(pattern, dep) for dep in deps), f"invalid dependency ID: {tid}")
        require(len(deps) == len(set(deps)), "duplicate dependency")
        by_id[tid] = ticket
        if ticket["status"] == "running":
            require(ticket.get("session_url", "").startswith("https://"), "running work needs session URL")
        if ticket["status"] == "done":
            evidence = ticket.get("integration", {})
            require(SHA.fullmatch(evidence.get("source_sha", "")), "done needs source SHA")
            require(SHA.fullmatch(evidence.get("epic_sha", "")), "done needs integration SHA")
            require(evidence.get("pipeline_url", "").startswith("https://"), "done needs pipeline URL")
            require(evidence.get("review_url", "").startswith("https://"), "done needs review URL")
    visiting, visited = set(), set()

    def walk(tid):
        require(tid in by_id, f"unknown dependency: {tid}")
        require(tid not in visiting, "dependency cycle")
        if tid in visited:
            return
        visiting.add(tid)
        for dep in by_id[tid]["depends_on"]:
            walk(dep)
            if by_id[tid]["status"] in {"done", "running"}:
                require(by_id[dep]["status"] == "done", "work started before dependency integration")
        visiting.remove(tid)
        visited.add(tid)

    for tid in by_id:
        walk(tid)
    ready = sorted((tid for tid, t in by_id.items() if t["status"] == "pending" and
                    all(by_id[d]["status"] == "done" for d in t["depends_on"])), key=ticket_order)
    return {"project_id": state["project_id"], "epic": state["epic"], "ready": ready,
            "in_flight": sorted((tid for tid, t in by_id.items() if t["status"] == "running"), key=ticket_order),
            "blocked": sorted((tid for tid, t in by_id.items() if t["status"] == "blocked"), key=ticket_order),
            "complete": all(t["status"] == "done" for t in tickets)}


def migrate_numbering(state, epic_issue_iid, source_issue_iid):
    """Return a migration preview only; caller must verify the actual GitLab parent."""
    ready_wave(state)
    require(positive_integer(epic_issue_iid), "invalid epic issue IID")
    require(positive_integer(source_issue_iid), "invalid source issue IID")
    if state["version"] == 2:
        require(state["epic_issue_iid"] == epic_issue_iid and
                state["source_issue_iid"] == source_issue_iid, "migration identity conflict")
        return deepcopy(state)
    # Preserve stored plan order, issue identity, status, evidence and other metadata.
    # The old epic suffix could identify the intake issue, so never infer the parent.
    result = deepcopy(state)
    epic = f"E{epic_issue_iid}"
    mapping = {t["id"]: f"{epic}-{n}" for n, t in enumerate(state["tickets"], 1)}
    result.update(version=2, epic=epic, epic_issue_iid=epic_issue_iid,
                  source_issue_iid=source_issue_iid, legacy_epic_id=state["epic"],
                  next_ticket_number=len(mapping) + 1)
    for ticket in result["tickets"]:
        old_id = ticket["id"]
        issue_iid = int(LEGACY_TICKET_ID.fullmatch(old_id).group(1))
        if "issue_iid" in ticket:
            require(type(ticket["issue_iid"]) is int and ticket["issue_iid"] == issue_iid,
                    "legacy ticket issue identity conflict")
        ticket.update(id=mapping[old_id], legacy_id=old_id, issue_iid=issue_iid,
                      depends_on=[mapping[d] for d in ticket["depends_on"]])
    ready_wave(result)
    return result


def add_ticket(state, issue_iid, depends_on=()):
    """Return a state preview with a stable epic-local ID for a verified GitLab issue."""
    ready_wave(state)
    require(state["version"] == 2, "migrate numbering before adding tickets")
    require(positive_integer(issue_iid), "invalid ticket issue IID")
    existing = next((t for t in state["tickets"] if t["issue_iid"] == issue_iid), None)
    if existing:
        require(not depends_on or list(depends_on) == existing["depends_on"],
                "existing ticket dependencies differ; reconcile explicitly")
        return deepcopy(state)
    result = deepcopy(state)
    number = result["next_ticket_number"]
    result["tickets"].append({"id": f"{state['epic']}-{number}", "issue_iid": issue_iid,
                              "depends_on": list(depends_on), "status": "pending"})
    result["next_ticket_number"] += 1
    ready_wave(result)
    return result


def validate_evidence(step, evidence, identity, prior):
    require(isinstance(evidence, dict), "evidence must be an object")
    require(evidence.get("source_sha") == identity["source_sha"], "evidence source SHA mismatch")
    require(https_url(evidence.get("report_url")), "accessible report URL required")
    if step == "verify":
        require(type(evidence.get("tests_total")) is int and evidence["tests_total"] > 0,
                "no collected application tests")
        require(evidence.get("passed") is True, "application tests did not pass")
    elif step == "acceptance":
        require(evidence.get("passed") is True and positive_integer(evidence.get("criteria_total")),
                "acceptance criteria did not pass")
        require(matches(re.compile(r"[0-9a-f]{64}"), evidence.get("manifest_sha256")),
                "acceptance manifest hash required")
        require(matches(re.compile(r"E[1-9][0-9]*(?:-[1-9][0-9]*)?"), evidence.get("scope")),
                "acceptance scope required")
    elif step == "source-security":
        require(isinstance(evidence.get("checks"), dict), "source scan checks must be a mapping")
        for check in ("source", "dependency", "secrets"):
            require(evidence.get("checks", {}).get(check) == "passed", f"missing/pending {check} scan")
        require(type(evidence.get("blocking_findings")) is int and evidence["blocking_findings"] == 0,
                "blocking security findings or missing verdict")
    elif step == "package":
        require(matches(DIGEST, evidence.get("artifact_digest")), "immutable sha256 digest required")
        for field in ("artifact_url", "sbom_url"):
            require(https_url(evidence.get(field)), f"missing {field}")
    elif step == "artifact-security":
        require(evidence.get("artifact_digest") == prior["package"]["evidence"]["artifact_digest"],
                "artifact scan digest mismatch")
        require(type(evidence.get("blocking_findings")) is int and evidence["blocking_findings"] == 0,
                "blocking artifact findings or missing verdict")
        require(evidence.get("passed") is True, "artifact scan not passed")
    elif step == "configure":
        require(evidence.get("environment") == "staging", "only staging validation supported")
        require(matches(re.compile(r"[0-9a-f]{64}"), evidence.get("configuration_revision")),
                "configuration content SHA256 required")
        require(evidence.get("passed") is True, "configuration validation failed")
        require(evidence.get("artifact_digest") == prior["package"]["evidence"]["artifact_digest"],
                "configuration candidate digest mismatch")
    else:
        raise Invalid(f"unsupported evidence step: {step}")


def validate_prior(step, reports, identity):
    validated = {}
    for name in STEPS[:STEPS.index(step)]:
        report = reports.get(name)
        require(isinstance(report, dict), f"missing prerequisite report: {name}")
        require(report.get("step") == name and report.get("status") == "passed",
                f"prerequisite not passed: {name}")
        require(all(report.get(k) == identity[k] for k in IDENTITY_KEYS),
                f"stale or wrong-project/pipeline evidence: {name}")
        validate_evidence(name, report.get("evidence"), identity, validated)
        validated[name] = report
    return validated


def execute_step(step, root=ROOT, environment=None):
    """Run a reviewed adapter, retaining failed/blocked reports as CI artifacts."""
    env = dict(os.environ if environment is None else environment)
    reports_dir = root / ".ctx/reports"
    output_dir = root / ".ctx/outputs"
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {"step": step, "status": "blocked", "timestamp": datetime.now(timezone.utc).isoformat()}
    code = 2
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        require(SHA.fullmatch(head), "invalid HEAD")
        require(env.get("CI_COMMIT_SHA", head) == head, "checkout does not match pipeline SHA")
        identity = {"project_id": env.get("CI_PROJECT_ID", "local"), "source_sha": head,
                    "pipeline_id": env.get("CI_PIPELINE_ID", "local")}
        report.update(identity)
        config = read_yaml(root / ".gitlab/ctx/commands.yml")
        validate_commands(config)
        command = config["commands"][step]
        require(command["argv"] is not None, f"{step} command is not configured; application foundation required")
        require(not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"],
                                            cwd=root, text=True).strip(),
                "candidate checkout is dirty; commit changes before recording SHA-bound evidence")
        prior = {}
        for name in STEPS[:STEPS.index(step)]:
            path = reports_dir / f"{name}.json"
            if path.is_file():
                prior[name] = json.loads(path.read_text())
        validate_prior(step, prior, identity)
        output = output_dir / f"{step}.json"
        # This path is exclusively generated evidence, never a user-supplied target.
        require(not output.is_symlink(), "refusing symlink evidence output")
        output.unlink(missing_ok=True)
        env["CTX_OUTPUT"] = str(output)
        env["CTX_SOURCE_SHA"] = head
        env["CTX_STEP"] = step
        # No shell parsing. Adapter output belongs in normal CI logs; it must redact secrets.
        completed = subprocess.run(command["argv"], cwd=root, env=env,
                                   timeout=command["timeout_seconds"], check=False)
        report["exit_code"] = completed.returncode
        if completed.returncode != 0:
            report.update(status="failed", reason="adapter command failed; inspect redacted job log")
            code = 1
        else:
            after_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            require(after_head == head, "adapter changed the candidate commit")
            require(not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"],
                                                cwd=root, text=True).strip(),
                    "adapter changed the candidate checkout")
            require(output.is_file() and not output.is_symlink(), "command emitted no fresh evidence")
            evidence = json.loads(output.read_text())
            validate_evidence(step, evidence, identity, prior)
            report.update(status="passed", evidence=evidence)
            code = 0
    except subprocess.TimeoutExpired:
        report.update(status="failed", reason="adapter command timed out")
        code = 1
    except (Invalid, OSError, ValueError, KeyError, TypeError, yaml.YAMLError, subprocess.CalledProcessError) as exc:
        report["reason"] = str(exc)
    (reports_dir / f"{step}.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    subs.add_parser("validate")
    subs.add_parser("waves").add_argument("state", type=Path)
    migration = subs.add_parser("migrate-numbering", help="print migrated state; no files or GitLab writes")
    migration.add_argument("state", type=Path)
    migration.add_argument("--epic-issue-iid", type=int, required=True)
    migration.add_argument("--source-issue-iid", type=int, required=True)
    allocation = subs.add_parser("add-ticket", help="print state with an epic-local ticket ID; no writes")
    allocation.add_argument("state", type=Path)
    allocation.add_argument("--issue-iid", type=int, required=True)
    allocation.add_argument("--depends-on", action="append", default=[])
    subs.add_parser("run").add_argument("step", choices=STEPS)
    args = parser.parse_args()
    try:
        if args.action == "run":
            return execute_step(args.step)
        if args.action == "validate":
            result = validate_repository()
        else:
            state = json.loads(args.state.read_text())
            if args.action == "migrate-numbering":
                result = migrate_numbering(state, args.epic_issue_iid, args.source_issue_iid)
            elif args.action == "add-ticket":
                result = add_ticket(state, args.issue_iid, args.depends_on)
            else:
                result = ready_wave(state)
        print(json.dumps(result, indent=2))
        return 0
    except (Invalid, OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f"CTX blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
