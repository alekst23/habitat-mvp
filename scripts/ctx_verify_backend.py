"""Reviewed `verify` adapter: run backend pytest and write SHA-bound evidence.

Fail closed. Evidence is written to CTX_OUTPUT only after a real pytest run whose
JUnit XML reports at least one test and no failure, error or skip. The count comes
from that XML, never a constant. No application code, shell, network or database
service is involved; the E11 application uses SQLite under pytest's temporary paths.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
import json
import xml.etree.ElementTree as ET

BACKEND = "backend"
TESTS = "backend/tests"


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


def junit_totals(path):
    if not path.is_file():
        return 0, 0
    suites = ET.parse(path).getroot()
    suites = [suites] if suites.tag == "testsuite" else suites.findall("testsuite")
    total = bad = 0
    for suite in suites:
        total += int(suite.get("tests", 0))
        bad += sum(int(suite.get(k, 0)) for k in ("failures", "errors", "skipped"))
    return total, bad


def main():
    output = None
    try:
        root = Path.cwd().resolve()
        output = Path(os.environ["CTX_OUTPUT"]) if os.environ.get("CTX_OUTPUT") else None
        sha = os.environ.get("CTX_SOURCE_SHA", "")
        require(output is not None and len(sha) == 40, "CTX_OUTPUT and CTX_SOURCE_SHA are required")
        output.unlink(missing_ok=True)
        require_clean_candidate(root, sha, "before tests")
        require((root / TESTS).is_dir(),
                f"no collected tests: {TESTS}/ does not exist (application foundation required)")
        job = urlparse(os.environ.get("CI_JOB_URL", ""))
        require(job.scheme == "https" and job.hostname and not job.username and not job.password,
                "CI_JOB_URL must be the HTTPS URL of the real CI job")
        with tempfile.TemporaryDirectory(prefix="ctx-verify-") as scratch:
            junit = Path(scratch) / "junit.xml"
            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(root / BACKEND)}
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", TESTS, "-p", "no:cacheprovider", "-q",
                 f"--junitxml={junit}"], cwd=root, env=env, check=False)
            total, bad = junit_totals(junit)
        require(total > 0, "no collected tests: pytest reported zero tests")
        require(completed.returncode == 0 and bad == 0,
                f"application tests did not pass (exit {completed.returncode}, {bad} failed/errored/skipped)")
        require_clean_candidate(root, sha, "after tests")
        evidence = {"source_sha": sha, "report_url": job.geturl(), "tests_total": total,
                    "passed": True, "runner": "pytest", "scope": TESTS}
        output.write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(evidence))
        return 0
    except (Blocked, OSError, ValueError, ET.ParseError, subprocess.CalledProcessError) as exc:
        if output is not None:
            output.unlink(missing_ok=True)
        print(f"Verify blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
