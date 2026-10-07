"""Validate AC coverage against a committed manifest; never execute application code."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlparse


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def https_url(value):
    if not isinstance(value, str):
        return False
    try:
        url = urlparse(value)
        return url.scheme == "https" and bool(url.hostname) and not url.username and not url.password
    except ValueError:
        return False


def selected_criteria(manifest, scope):
    require(manifest.get("version") == 1, "unsupported acceptance manifest")
    epic = manifest.get("epic")
    require(isinstance(epic, str) and re.fullmatch(r"E[1-9][0-9]*", epic), "invalid epic")
    require(isinstance(scope, str) and (scope == epic or re.fullmatch(epic + r"-[1-9][0-9]*", scope)),
            "scope must name the manifest epic or one of its tickets")
    criteria = manifest.get("criteria")
    require(isinstance(criteria, list) and criteria, "empty acceptance manifest")
    seen, selected = set(), []
    for criterion in criteria:
        cid = criterion.get("id")
        require(isinstance(cid, str) and re.fullmatch(epic + r"-[1-9][0-9]*\.AC[1-9][0-9]*", cid),
                "invalid AC identity")
        require(cid not in seen, "duplicate AC in manifest")
        seen.add(cid)
        require(isinstance(criterion.get("statement"), str) and criterion["statement"].strip(),
                f"missing AC statement: {cid}")
        methods = criterion.get("methods")
        require(isinstance(methods, list) and methods and all(isinstance(m, str) for m in methods),
                f"missing verification methods: {cid}")
        require(len(set(methods)) == len(methods) and set(methods) <= {"test", "browser", "inspection"},
                f"invalid verification methods: {cid}")
        require(type(criterion.get("ui")) is bool, f"UI classification required: {cid}")
        require(not criterion["ui"] or "browser" in methods, f"UI AC requires browser evidence: {cid}")
        if "inspection" in methods:
            require(isinstance(criterion.get("inspection_reason"), str) and
                    criterion["inspection_reason"].strip(), f"inspection rationale required: {cid}")
        if scope == epic or cid.split(".")[0] == scope:
            selected.append(criterion)
    require(selected, "scope has no acceptance criteria")
    return selected


def check_identity(report, expected, digest):
    require(report.get("version") == 1, "unsupported acceptance report")
    require(all(report.get(key) == value for key, value in expected.items()),
            "acceptance report has stale/wrong project, SHA, pipeline or scope")
    require(report.get("manifest_sha256") == digest, "acceptance manifest changed after evidence")


def indexed_rows(report):
    rows = report.get("criteria")
    require(isinstance(rows, list), "acceptance criteria report required")
    indexed = {}
    for row in rows:
        cid = row.get("id")
        require(isinstance(cid, str) and cid not in indexed, "duplicate/invalid AC in report")
        indexed[cid] = row
    return indexed


def validate_acceptance(manifest, digest, report, expected, browser=None):
    """One test may prove multiple ACs. Missing methods and skipped checks block."""
    criteria = selected_criteria(manifest, expected["scope"])
    check_identity(report, expected, digest)
    rows = deepcopy(indexed_rows(report))
    require(set(rows) == {c["id"] for c in criteria}, "acceptance coverage must match the requested scope")
    browser_ids = {c["id"] for c in criteria if "browser" in c["methods"]}
    if browser_ids:
        require(isinstance(browser, dict), "required browser report is missing")
        check_identity(browser, expected, digest)
        browser_rows = indexed_rows(browser)
        require(set(browser_rows) == browser_ids, "browser coverage must match UI requirements")
        for cid in browser_ids:
            # Browser CI is the producer; a builder's self-reported browser pass is insufficient.
            rows[cid].setdefault("evidence", {})["browser"] = browser_rows[cid].get("evidence", {}).get("browser")
    for criterion in criteria:
        cid = criterion["id"]
        row = rows[cid]
        require(row.get("status") == "passed" or
                (cid in browser_ids and row.get("status") == "pending-browser"), f"AC not passed: {cid}")
        require(isinstance(row.get("code"), str) and row["code"].strip(), f"code/document reference missing: {cid}")
        evidence = row.get("evidence")
        require(isinstance(evidence, dict), f"AC evidence missing: {cid}")
        for method in criterion["methods"]:
            check = evidence.get(method)
            require(isinstance(check, dict) and check.get("status") == "passed", f"{cid}: {method} not passed")
            require(https_url(check.get("url")), f"{cid}: {method} evidence URL missing")
            if method == "inspection":
                require(isinstance(check.get("reason"), str) and check["reason"].strip(),
                        f"{cid}: inspection result missing")
            else:
                ids = check.get("test_ids")
                require(isinstance(ids, list) and ids and all(isinstance(t, str) and t.strip() for t in ids),
                        f"{cid}: executed test IDs missing")
    return len(criteria)


def main():
    try:
        root = Path.cwd().resolve()
        path = (root / os.environ["CTX_AC_MANIFEST"]).resolve()
        require(path.is_relative_to(root) and path.is_file(), "manifest must be a committed repository file")
        # The outer workflow adapter checks a clean checkout/HEAD; prove this is tracked too.
        subprocess.run(["git", "ls-files", "--error-unmatch", str(path.relative_to(root))],
                       check=True, capture_output=True, cwd=root)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        manifest = json.loads(raw)
        expected = {"project_id": os.environ["CI_PROJECT_ID"],
                    "source_sha": os.environ["CTX_SOURCE_SHA"],
                    "pipeline_id": os.environ["CI_PIPELINE_ID"],
                    "scope": os.environ["CTX_AC_SCOPE"]}
        report = json.loads((root / ".ctx/acceptance.json").read_text())
        browser_path = root / ".ctx/browser/acceptance.json"
        browser = json.loads(browser_path.read_text()) if browser_path.is_file() else None
        count = validate_acceptance(manifest, digest, report, expected, browser)
        url = os.environ["CI_JOB_URL"]
        require(https_url(url), "CI_JOB_URL must be an HTTPS job URL")
        output = {"source_sha": expected["source_sha"], "passed": True,
                  "report_url": url, "criteria_total": count, "scope": expected["scope"],
                  "manifest_sha256": digest}
        Path(os.environ["CTX_OUTPUT"]).write_text(json.dumps(output, indent=2) + "\n")
        print(json.dumps(output))
        return 0
    except (Invalid, OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError) as exc:
        print(f"Acceptance blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
