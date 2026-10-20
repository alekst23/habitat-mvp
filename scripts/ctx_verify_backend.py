"""Reviewed `verify` adapter: run backend pytest and write SHA-bound evidence.

Fail closed. Evidence is written to CTX_OUTPUT only after a real pytest run whose
JUnit XML reports at least one test and no failure, error or skip. The count comes
from that XML, never a constant. No application code, shell, network or database
service is involved; the E11 application uses SQLite under pytest's temporary paths.

The same run also writes `.ctx/acceptance.json` for CTX_AC_SCOPE (manifest CTX_AC_MANIFEST).
Tests declare the ACs they prove with `@pytest.mark.ac("E11-1.AC1", code="backend/path.py:symbol")`
(see scripts/ctx_pytest_ac.py); the mapping is read back from that run's JUnit XML.
Every failure removes both outputs and exits 2.
"""

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
import json
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ctx_acceptance  # noqa: E402  (reviewed sibling: manifest/scope validation)
from ctx_pytest_ac import PROPERTY  # noqa: E402

BACKEND = "backend"
TESTS = "backend/tests"
ACCEPTANCE = ".ctx/acceptance.json"


class Blocked(Exception):
    pass


def require(condition, message):
    if not condition:
        raise Blocked(message)


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def require_clean_candidate(root, sha, when):
    require(git(root, "rev-parse", "HEAD") == sha, f"HEAD does not match CTX_SOURCE_SHA {when}")
    require(not git(root, "status", "--porcelain", "--untracked-files=normal"),
            f"candidate checkout is dirty {when}")


def junit_suites(path):
    suites = ET.parse(path).getroot()
    return [suites] if suites.tag == "testsuite" else suites.findall("testsuite")


def junit_totals(path):
    if not path.is_file():
        return 0, 0
    total = bad = 0
    for suite in junit_suites(path):
        total += int(suite.get("tests", 0))
        bad += sum(int(suite.get(k, 0)) for k in ("failures", "errors", "skipped"))
    return total, bad


def passing_ac_tests(path):
    """Map AC id -> {test_ids, codes} from executed, passing JUnit test cases only."""
    mapped = {}
    for suite in junit_suites(path):
        for case in suite.iter("testcase"):
            declared = [p.get("value", "") for p in case.iter("property") if p.get("name") == PROPERTY]
            if not declared:
                continue
            require(not any(case.find(tag) is not None for tag in ("failure", "error", "skipped")),
                    f"mapped test did not pass: {case.get('name')}")
            file = case.get("file")
            require(file, "JUnit test case has no file; cannot name its test ID")
            module = file[:-3].replace("/", ".") if file.endswith(".py") else file
            classname = case.get("classname", "")
            require(classname == module or classname.startswith(module + "."), "unexpected JUnit class name")
            nested = classname[len(module) + 1:].replace(".", "::")
            test_id = "::".join(filter(None, [file, nested, case.get("name")]))
            for value in declared:
                ac_id, _, code = value.partition(" ")
                require(code, f"AC marker without code reference: {case.get('name')}")
                entry = mapped.setdefault(ac_id, {"test_ids": set(), "codes": set()})
                entry["test_ids"].add(test_id)
                entry["codes"].add(code)
    return mapped


def build_acceptance(root, sha, job_url, junit):
    """Return the acceptance report for CTX_AC_SCOPE; raise Blocked without evidence."""
    scope, name = os.environ.get("CTX_AC_SCOPE", ""), os.environ.get("CTX_AC_MANIFEST", "")
    require(scope and name, "CTX_AC_SCOPE and CTX_AC_MANIFEST are required")
    for key in ("CI_PROJECT_ID", "CI_PIPELINE_ID"):
        require(os.environ.get(key), f"{key} is required")
    path = (root / name).resolve()
    require(path.is_relative_to(root) and path.is_file(), "acceptance manifest must be a repository file")
    tracked = set(git(root, "ls-files").splitlines())
    require(str(path.relative_to(root)) in tracked, "acceptance manifest must be committed")
    raw = path.read_bytes()
    try:
        manifest = json.loads(raw)
        criteria = ctx_acceptance.selected_criteria(manifest, scope)
    except (ValueError, AttributeError, TypeError) as exc:  # includes ctx_acceptance.Invalid
        raise Blocked(f"acceptance manifest/scope invalid: {exc}")
    mapped = passing_ac_tests(junit)
    known = {c["id"] for c in manifest["criteria"]}
    require(set(mapped) <= known, f"unknown AC id in test markers: {sorted(set(mapped) - known)}")
    rows, problems = [], []
    for criterion in criteria:
        cid, methods = criterion["id"], criterion["methods"]
        found = mapped.get(cid)
        if "inspection" in methods:
            problems.append(f"{cid}: inspection evidence cannot be produced by the verify adapter")
            continue
        if not found:
            problems.append(f"{cid}: no passing test mapped to this AC")
            continue
        codes = sorted(found["codes"])
        bad = [c for c in codes if Path(c.split(":", 1)[0]).is_absolute() or c.split(":", 1)[0] not in tracked]
        if bad:
            problems.append(f"{cid}: code reference is not a tracked repository file: {bad}")
            continue
        row = {"id": cid, "status": "pending-browser" if "browser" in methods else "passed",
               "code": ", ".join(codes), "evidence": {}}
        if "test" in methods:  # a browser-only AC gets only its code reference from a passing test
            row["evidence"]["test"] = {"status": "passed", "test_ids": sorted(found["test_ids"]), "url": job_url}
        rows.append(row)
    require(not problems, "; ".join(problems))
    return {"version": 1, "project_id": os.environ["CI_PROJECT_ID"], "source_sha": sha,
            "pipeline_id": os.environ["CI_PIPELINE_ID"], "scope": scope,
            "manifest_sha256": hashlib.sha256(raw).hexdigest(), "criteria": rows}


def main():
    output = None
    try:
        root = Path.cwd().resolve()
        output = Path(os.environ["CTX_OUTPUT"]) if os.environ.get("CTX_OUTPUT") else None
        sha = os.environ.get("CTX_SOURCE_SHA", "")
        require(output is not None and len(sha) == 40, "CTX_OUTPUT and CTX_SOURCE_SHA are required")
        output.unlink(missing_ok=True)
        (root / ACCEPTANCE).unlink(missing_ok=True)
        require_clean_candidate(root, sha, "before tests")
        require((root / TESTS).is_dir(),
                f"no collected tests: {TESTS}/ does not exist (application foundation required)")
        job = urlparse(os.environ.get("CI_JOB_URL", ""))
        require(job.scheme == "https" and job.hostname and not job.username and not job.password,
                "CI_JOB_URL must be the HTTPS URL of the real CI job")
        with tempfile.TemporaryDirectory(prefix="ctx-verify-") as scratch:
            junit = Path(scratch) / "junit.xml"
            scripts = str(Path(__file__).resolve().parent)  # only for the reviewed ac-marker plugin
            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": os.pathsep.join([str(root / BACKEND), scripts])}
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", TESTS, "-p", "no:cacheprovider", "-p", "ctx_pytest_ac", "-q",
                 "-o", "junit_family=xunit1", f"--junitxml={junit}"], cwd=root, env=env, check=False)
            total, bad = junit_totals(junit)
            require(total > 0, "no collected tests: pytest reported zero tests")
            require(completed.returncode == 0 and bad == 0,
                    f"application tests did not pass (exit {completed.returncode}, {bad} failed/errored/skipped)")
            require_clean_candidate(root, sha, "after tests")
            acceptance = build_acceptance(root, sha, job.geturl(), junit)
        (root / ACCEPTANCE).parent.mkdir(exist_ok=True)
        (root / ACCEPTANCE).write_text(json.dumps(acceptance, indent=2) + "\n")
        evidence = {"source_sha": sha, "report_url": job.geturl(), "tests_total": total,
                    "passed": True, "runner": "pytest", "scope": TESTS}
        output.write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(evidence))
        return 0
    except (Blocked, OSError, ValueError, ET.ParseError, subprocess.CalledProcessError) as exc:
        if output is not None:
            output.unlink(missing_ok=True)
        (Path.cwd() / ACCEPTANCE).unlink(missing_ok=True)
        print(f"Verify blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
