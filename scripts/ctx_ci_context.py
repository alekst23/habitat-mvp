"""Resolve acceptance from committed plan/branch identity, never user CI variables.

prepare is an agent-owned candidate edit, committed BEFORE verification/review.
Its ticket context travels with the merge so post-integration CI verifies that
ticket at the new epic SHA. Epic documentation prepares whole-epic scope before
final verification. Context is configuration, not passing evidence or authority.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from ctx_acceptance import selected_criteria

CONTEXT_PATH = ".gitlab/ctx/verification-context.json"
# A maintenance-only pipeline is explicitly NOT application acceptance. This
# allowlist never includes product plans/ACs, command adapters, credentials or
# checkpoint/controller policy. Those changes require real scoped verification.
MAINTENANCE_FILES = frozenset({
    "AGENTS.md", ".gitlab-ci.yml", ".gitlab/ci/browser.yml", ".gitlab/ci/delivery.yml",
    ".gitlab/ctx/browser-reporter.ts", ".gitlab/ctx/playwright.config.ts", ".gitlab/ctx/catalog.json",
    "scripts/ctx_ci_context.py", "scripts/ctx_workflow.py", "scripts/ctx_acceptance.py",
    "scripts/ctx_development.py", "scripts/ctx_execution_budget.py",
})
MAINTENANCE_PREFIXES = (".gitlab/duo/agents/", ".gitlab/duo/flows/", "docs/development/",
                        "skills/ctx-", "tests/workflow/")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.PIPE).strip()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def committed_json(root, name, *, require_unchanged=True):
    path = root / name
    require(path.resolve() == path and path.is_file(), f"not a regular repository file: {name}")
    try:
        raw = subprocess.check_output(["git", "show", f"HEAD:{name}"], cwd=root, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"candidate file is not committed: {name}") from exc
    require(not require_unchanged or path.read_bytes() == raw,
            f"commit candidate context before verification: {name}")
    return json.loads(raw, object_pairs_hook=unique_object), raw


def maintenance_context(root, env, sha, branch, plans):
    """Only a proven workflow-only ancestor diff may omit application evidence."""
    target = env.get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME")
    default = env.get("CI_DEFAULT_BRANCH", "main")
    targets = {default} | {s.get("epic_branch", f"ctx/epic-i{s['epic_issue_iid']}") for s, _ in plans.values()}
    targets |= {t.get("branch", f"ctx/ticket-i{t['issue_iid']}")
                for s, _ in plans.values() for t in s["tickets"]}
    if target is not None:
        require(target in targets, "maintenance MR target is not a known epic/default branch")
        base = env.get("CI_MERGE_REQUEST_DIFF_BASE_SHA", "")
    else:
        base = env.get("CI_COMMIT_BEFORE_SHA", "")
    require(re.fullmatch(r"[0-9a-f]{40}", base) and base != "0" * 40,
            "unmapped branch needs a verified maintenance diff base; no scope guessing")
    require(subprocess.run(["git", "merge-base", "--is-ancestor", base, sha], cwd=root,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0,
            "maintenance base is unavailable or not a candidate ancestor")
    paths = git(root, "diff", "--no-renames", "--name-only", base, sha).splitlines()
    require(paths and all(p in MAINTENANCE_FILES or p.startswith(MAINTENANCE_PREFIXES) for p in paths),
            "unmapped candidate contains non-maintenance changes; use the planned ticket branch")
    return {"version": 1, "mode": "maintenance", "project_id": str(env.get("CI_PROJECT_ID", "local")),
            "source_sha": sha, "branch": branch, "base_sha": base, "changed_paths": paths,
            "reason": "Verified workflow-only diff; not application or acceptance evidence."}


def resolve_context(root, environment=None, *, ignore_context=False):
    root = Path(root).resolve()
    env = os.environ if environment is None else environment
    sha = git(root, "rev-parse", "HEAD")
    require(env.get("CI_COMMIT_SHA", sha) == sha, "candidate does not match pipeline SHA")
    branch = env.get("CI_MERGE_REQUEST_SOURCE_BRANCH_NAME") or env.get("CI_COMMIT_BRANCH")
    branch = branch or git(root, "branch", "--show-current")
    require(branch, "no source branch identity; detached local checkout is not a scope")
    plans, matches = {}, []
    names = git(root, "ls-files", "docs/plan/E*/state.json").splitlines()
    for name in names:
        if not re.fullmatch(r"docs/plan/E[1-9][0-9]*/state\.json", name):
            continue  # Legacy EPIC-I* records are history, never candidate identity.
        state, _ = committed_json(root, name, require_unchanged=not ignore_context)
        epic = state.get("epic", "")
        require(state.get("version") == 2 and re.fullmatch(r"E[1-9][0-9]*", epic),
                f"version-2 plan identity required: {name}")
        require(name == f"docs/plan/{epic}/state.json" and epic not in plans and
                type(state.get("epic_issue_iid")) is int and epic == f"E{state['epic_issue_iid']}",
                "ambiguous epic mapping")
        require(re.fullmatch(r"[1-9][0-9]*", str(state.get("project_id", ""))), "invalid project mapping")
        require(str(state["project_id"]) == str(env.get("CI_PROJECT_ID", state["project_id"])),
                "plan belongs to a different project")
        tickets = state.get("tickets")
        require(isinstance(tickets, list) and tickets, "plan has no ticket mapping")
        ids, iids = set(), set()
        for ticket in tickets:
            tid, iid = ticket.get("id", ""), ticket.get("issue_iid")
            require(re.fullmatch(rf"{epic}-[1-9][0-9]*", tid) and tid not in ids and
                    type(iid) is int and iid > 0 and iid != state["epic_issue_iid"] and iid not in iids,
                    "ambiguous ticket mapping")
            ids.add(tid)
            iids.add(iid)
            if branch == ticket.get("branch", f"ctx/ticket-i{iid}"):
                matches.append((epic, tid))
        if branch == state.get("epic_branch", f"ctx/epic-i{state['epic_issue_iid']}"):
            matches.append((epic, epic))
        plans[epic] = (state, ids)
    require(plans, "no committed version-2 plan for application verification")
    is_default = branch == env.get("CI_DEFAULT_BRANCH", "main")
    if not matches and not ignore_context:
        # On default, maintenance may omit application checks only when its
        # complete diff proves no app work. Otherwise require whole-epic context.
        try:
            return maintenance_context(root, env, sha, branch, plans)
        except ValueError:
            if not is_default:
                raise
    marker = None
    if not ignore_context and (root / CONTEXT_PATH).exists():
        marker, _ = committed_json(root, CONTEXT_PATH)
        require(isinstance(marker, dict) and set(marker) == {"version", "project_id", "epic", "scope"}
                and type(marker["version"]) is int and marker["version"] == 1,
                "invalid candidate verification context")
    if is_default:
        require(marker is not None and marker.get("epic") in plans and marker.get("scope") == marker["epic"],
                "default branch requires committed whole-epic verification context")
        matches.append((marker["epic"], marker["epic"]))
    require(len(matches) == 1, f"source branch must map to exactly one planned target: {branch}")
    epic, scope = matches[0]
    state, tids = plans[epic]
    target = env.get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME")
    if target:
        expected = (env.get("CI_DEFAULT_BRANCH", "main") if scope == epic else
                    state.get("epic_branch", f"ctx/epic-i{state['epic_issue_iid']}"))
        require(target == expected, "MR target does not match the committed ticket/epic hierarchy")
    if marker is not None:
        require(marker["epic"] == epic and str(marker["project_id"]) == str(state["project_id"]),
                "candidate context project/epic mismatch")
        require(marker["scope"] in tids | {epic}, "candidate context names unknown target")
        if scope != epic:
            require(marker["scope"] == scope, "stale candidate context; prepare it on this ticket before committing")
        else:
            scope = marker["scope"]
    name = f"docs/plan/{epic}/acceptance.json"
    manifest, raw = committed_json(root, name, require_unchanged=not ignore_context)
    require(manifest.get("epic") == epic, "manifest belongs to another epic")
    criteria = selected_criteria(manifest, scope)
    return {"version": 1, "mode": "application", "project_id": str(state["project_id"]), "source_sha": sha,
            "branch": branch, "epic": epic, "scope": scope, "manifest": name,
            "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "browser_required": any("browser" in c["methods"] for c in criteria)}


def prepare_context(root, environment=None, *, whole_epic=False):
    root = Path(root).resolve()
    # Workers may inherit main-branch CI variables inside a ticket worktree.
    # Preparation edits that actual worktree; evidence CI still checks its own SHA.
    env = dict(os.environ if environment is None else environment)
    env["CI_COMMIT_BRANCH"] = git(root, "branch", "--show-current")
    env["CI_COMMIT_SHA"] = git(root, "rev-parse", "HEAD")
    require(env["CI_COMMIT_BRANCH"], "prepare requires a named isolated ticket/epic branch")
    for key in tuple(env):
        if key.startswith("CI_MERGE_REQUEST_") or key == "CI_COMMIT_BEFORE_SHA":
            env.pop(key)
    context = resolve_context(root, env, ignore_context=True)
    require((context["scope"] == context["epic"]) == whole_epic,
            "prepare on a ticket branch, or use --whole-epic on its epic branch")
    marker = {key: context[key] for key in ("version", "project_id", "epic", "scope")}
    path = root / CONTEXT_PATH
    require(path.resolve() == path, "refusing symlink context output")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(marker, indent=2) + "\n")
    return marker


def require_whole_epic(root, environment=None):
    context = resolve_context(root, environment)
    if context["mode"] != "maintenance":
        require(context["scope"] == context["epic"],
                "epic MR is not ready: prepare and verify whole-epic scope before merging to default")
    return context


def run_browser(root, environment=None):
    env = dict(os.environ if environment is None else environment)
    context = resolve_context(root, env)
    path = root / ".ctx/browser"
    path.mkdir(parents=True, exist_ok=True)
    # Never keep stale browser evidence from a previous invocation.
    for name in ("acceptance.json", "not-applicable.json"):
        (path / name).unlink(missing_ok=True)
    if context["mode"] == "maintenance" or not context["browser_required"]:
        (path / "not-applicable.json").write_text(json.dumps({**context, "status": "not_applicable",
            "reason": context.get("reason", "The committed scope contains no browser criteria.")}, indent=2) + "\n")
        print("Browser not applicable to this checked context; no browser pass claimed.")
        return 0
    require((root / "package-lock.json").is_file(), "browser foundation missing: package-lock.json")
    if (root / "backend/requirements.txt").is_file():
        subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                        "-r", "backend/requirements.txt"], cwd=root, env=env, check=True)
    subprocess.run(["npm", "ci"], cwd=root, env=env, check=True)
    version = subprocess.check_output(["node", "-p", 'require("@playwright/test/package.json").version'],
                                      cwd=root, env=env, text=True).strip()
    require(version == "1.63.0", "Playwright version must match the pinned browser image")
    return subprocess.run(["npx", "--no-install", "playwright", "test", "--config",
                           ".gitlab/ctx/playwright.config.ts"], cwd=root, env=env, check=False).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["resolve", "prepare", "browser", "require-whole-epic", "delivery-readiness"])
    parser.add_argument("--whole-epic", action="store_true")
    args = parser.parse_args()
    try:
        require(not args.whole_epic or args.action == "prepare", "--whole-epic is only for prepare")
        root = Path.cwd().resolve()
        if args.action == "browser":
            return run_browser(root)
        if args.action == "delivery-readiness":
            context = resolve_context(root)
            if context["mode"] == "maintenance":
                print(json.dumps({**context, "status": "not_applicable"}, indent=2))
                return 0
            return subprocess.run([sys.executable, "scripts/ctx_delivery.py", "--phase", "candidate"],
                                  cwd=root, check=False).returncode
        if args.action == "require-whole-epic":
            result = require_whole_epic(root)
        else:
            result = prepare_context(root, whole_epic=args.whole_epic) if args.action == "prepare" else resolve_context(root)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError) as exc:
        # Do not print subprocess output or the process environment (may include credentials).
        print(f"CI context blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
