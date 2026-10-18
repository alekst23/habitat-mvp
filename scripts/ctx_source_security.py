"""Source, dependency and secret scan adapter for the existing mandatory CI gate.

Uses Bandit, pip-audit and Trivy at reviewed versions. Raw scanner output is kept
in private temporary files; only normalized locations and identifiers are retained.
No deployment or packaging authority. Missing scans, invalid evidence and blocking
findings fail closed. Adapted from the separately reviewed GCP delivery foundation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{40}")
VERSIONS = {"bandit": "1.9.4", "pip-audit": "2.10.1", "trivy": "0.76.0"}
SCHEMA_VERSION = "15.2.0"


class Blocked(ValueError):
    """Safe, deliberately static diagnostic suitable for public job logs."""


def require(condition, message):
    if not condition:
        raise Blocked(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def safe_path(root, relative):
    path = root / relative
    require(path.is_relative_to(root), "path must stay in checkout")
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink path refused")
    return path


def read_json(path):
    require(path.is_file() and not path.is_symlink(), "required JSON input absent")
    require(path.stat().st_size <= 50 * 1024 * 1024, "JSON input exceeds size limit")
    try:
        return json.loads(path.read_text(), object_pairs_hook=unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Blocked("malformed JSON tool response") from exc


def configuration_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def write_json(root, relative, value):
    path = safe_path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(configuration_bytes(value))
    return path


def run(argv, root, env, *, accepted=(0,), timeout=600):
    """Never shell-parse arguments or print potentially secret subprocess output."""
    # Project/pipeline variables must not silently suppress findings, skip files,
    # replace rules or enable ignore-unfixed.
    tool_env = {key: value for key, value in env.items()
                if not key.startswith(("TRIVY_", "BANDIT_", "PIP_AUDIT_"))}
    try:
        result = subprocess.run(argv, cwd=root, env=tool_env, capture_output=True,
                                text=True, check=False, timeout=timeout, shell=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Blocked("required security tool unavailable or timed out") from exc
    require(result.returncode in accepted, "security tool failed; no passing receipt emitted")
    return result


def check_version(tool, root, env):
    value = run([tool, "--version"], root, env, timeout=30).stdout
    require(re.search(r"(?<![0-9.])" + re.escape(VERSIONS[tool]) + r"(?![0-9.])", value),
            "security tool version differs from reviewed pin")


def identity(env):
    sha = env.get("CTX_SOURCE_SHA", "")
    require(SHA.fullmatch(sha), "CTX_SOURCE_SHA must identify the reviewed candidate")
    require(env.get("CI_COMMIT_SHA") == sha, "candidate does not match CI commit")
    project, pipeline, job = (env.get(key, "") for key in ("CI_PROJECT_ID", "CI_PIPELINE_ID", "CI_JOB_ID"))
    require(all(re.fullmatch(r"[1-9][0-9]*", value) for value in (project, pipeline, job)),
            "actual GitLab project, pipeline and job identity required")
    url = env.get("CI_PROJECT_URL", "")
    require(re.fullmatch(r"https://[^/?#@:]+/(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+", url),
            "canonical HTTPS GitLab project URL required")
    require(env.get("CI_JOB_URL") == url + "/-/jobs/" + job, "job URL does not match project identity")
    return {"source_sha": sha, "report_url": env["CI_JOB_URL"]}


def application(root):
    require(safe_path(root, "backend/aicl").is_dir(), "reviewed application backend absent")
    lock = safe_path(root, "backend/requirements.lock")
    require(lock.is_file() and "--hash=sha256:" in lock.read_text(),
            "hashed, fully resolved backend/requirements.lock required")
    require(any((root / "backend/aicl").rglob("*.py")), "application has no Python source")
    return lock


def artifact_link(env, relative):
    return env["CI_JOB_URL"] + "/artifacts/file/" + relative


def scanner_report(category, tool, findings, started, *, success=True):
    scanner = {"id": tool, "name": tool, "version": VERSIONS[tool],
               "vendor": {"name": "PyCQA" if tool == "bandit" else "PyPA" if tool == "pip-audit" else "Aqua Security"}}
    return {"version": SCHEMA_VERSION, "vulnerabilities": findings,
            "scan": {"type": category, "scanner": scanner,
                     "analyzer": {"id": "ctx-source-security", "name": "CTX source security adapter", "version": "1.0.0",
                                  "vendor": {"name": "Habitat"}},
                     "start_time": started, "end_time": utc_time(),
                     "status": "success" if success else "failure"}}


def utc_time():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def finding(category, identifier, location, severity, description):
    require(isinstance(identifier, str) and 0 < len(identifier) <= 200, "invalid scanner finding identity")
    severity = str(severity).capitalize()
    require(severity in {"Info", "Unknown", "Low", "Medium", "High", "Critical"}, "unknown finding severity")
    value = category + ":" + identifier + ":" + json.dumps(location, sort_keys=True)
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, value)), "category": category,
            "name": identifier, "description": description, "severity": severity,
            "identifiers": [{"type": category, "name": identifier, "value": identifier}],
            "location": location}


def source_location(value):
    require(isinstance(value, str), "scanner location missing")
    path = Path(value)
    require(not path.is_absolute() and ".." not in path.parts, "scanner location is outside repository")
    return str(path)


def bandit_findings(data):
    require(isinstance(data, dict) and data.get("errors") == [], "source scanner errors or incomplete report")
    metrics = data.get("metrics", {}).get("_totals", {})
    require(type(metrics.get("loc")) is int and metrics["loc"] > 0, "source scanner inspected no code")
    require(isinstance(data.get("results"), list), "source findings missing")
    findings = []
    for entry in data["results"]:
        location = {"file": source_location(entry["filename"]), "start_line": entry["line_number"]}
        require(type(location["start_line"]) is int and location["start_line"] > 0, "source finding line missing")
        findings.append(finding("sast", entry["test_id"], location, entry["issue_severity"],
                                "Bandit identified a potentially unsafe Python operation; inspect the referenced code."))
    return findings


def dependency_findings(data):
    require(isinstance(data, dict) and isinstance(data.get("dependencies"), list)
            and data["dependencies"], "dependency scanner inspected no dependencies")
    findings = []
    for dependency in data["dependencies"]:
        require(not dependency.get("skip_reason") and isinstance(dependency.get("vulns"), list),
                "dependency scan skipped or failed to audit a package")
        require(all(isinstance(dependency.get(key), str) and dependency[key] for key in ("name", "version")),
                "dependency package identity missing")
        for vulnerability in dependency["vulns"]:
            location = {"file": "backend/requirements.lock", "dependency": {
                "package": {"name": dependency["name"]}, "version": dependency["version"]}}
            findings.append(finding("dependency_scanning", vulnerability["id"], location, "Unknown",
                                    "pip-audit identified a published vulnerability in this locked dependency."))
    return findings


def trivy_results(data, expected_type):
    require(isinstance(data, dict) and data.get("SchemaVersion") == 2,
            "unsupported or incomplete Trivy report")
    require(data.get("ArtifactType") == expected_type, "Trivy scanned the wrong artifact type")
    results = data.get("Results", [])
    require(isinstance(results, list), "Trivy result list missing")
    return results


def secret_findings(data, sha):
    findings = []
    for result in trivy_results(data, "filesystem"):
        for secret in result.get("Secrets", []):
            location = {"file": source_location(result["Target"]), "commit": {"sha": sha},
                        "start_line": secret["StartLine"]}
            require(type(location["start_line"]) is int and location["start_line"] > 0, "secret location missing")
            # Never copy Match, Code, Text, Title or arbitrary scanner strings containing secret bytes.
            findings.append(finding("secret_detection", secret["RuleID"], location, secret["Severity"],
                                    "Potential credential detected. Value redacted; rotate and remove it if confirmed."))
    return findings


def source_security(root, env):
    for category in ("sast", "dependency-scanning", "secret-detection"):
        safe_path(root, ".ctx/security/gl-" + category + "-report.json").unlink(missing_ok=True)
    base = identity(env)
    application(root)
    for tool in VERSIONS:
        check_version(tool, root, env)
    reports = []
    # Raw scanner files are outside artifacts and deleted even when parsing fails.
    with tempfile.TemporaryDirectory(prefix="ctx-scan-") as directory:
        raw = Path(directory)
        empty = raw / "empty.yaml"
        empty.write_text("{}\n")
        ini = raw / "empty.ini"
        ini.write_text("")
        ignore = raw / "empty.ignore"
        ignore.write_text("")
        # SAST covers the application package; synthetic test fixtures are not deployed.
        # Secret detection still scans the entire checkout (excluding tool/output directories).
        jobs = [
            ("sast", "bandit", ["bandit", "--ignore-nosec", "--ini", str(ini), "-c", str(empty), "-r", "backend/aicl", "-f", "json", "-o", str(raw / "sast.json")], bandit_findings),
            ("dependency_scanning", "pip-audit", ["pip-audit", "--strict", "--require-hashes", "-r", "backend/requirements.lock",
              "--format", "json", "--output", str(raw / "dependency_scanning.json")], dependency_findings),
            ("secret_detection", "trivy", ["trivy", "fs", "--config", str(empty), "--secret-config", str(empty),
              "--ignorefile", str(ignore), "--scanners", "secret", "--format", "json", "--exit-code", "0",
              "--skip-dirs", ".git,.ctx,.venv", "--output", str(raw / "secret_detection.json"), "."],
             lambda data: secret_findings(data, base["source_sha"])),
        ]
        for category, tool, argv, convert in jobs:
            started = utc_time()
            # Bandit/pip-audit return 1 for actual findings. A nonzero result without
            # findings or with skipped/error data remains a tool failure.
            result = run(argv, root, {**env, "PIP_ONLY_BINARY": ":all:"}, accepted=(0, 1) if tool != "trivy" else (0,))
            findings = convert(read_json(raw / (category + ".json")))
            require(result.returncode == 0 or findings, "scanner failed without usable findings")
            report = scanner_report(category, tool, findings, started)
            relative = ".ctx/security/gl-" + category.replace("_", "-") + "-report.json"
            write_json(root, relative, report)
            reports.append((category, findings, relative))
    blocking = sum(len(items) if category != "sast" else
                   sum(item["severity"] in {"Medium", "High", "Critical", "Unknown"} for item in items)
                   for category, items, _ in reports)
    require(blocking == 0, "blocking security findings; inspect redacted native reports")
    return {**base, "checks": {name: "passed" for name in ("source", "dependency", "secrets")},
            "blocking_findings": 0, "security_reports": [artifact_link(env, path) for _, _, path in reports]}



def main():
    try:
        env = dict(os.environ)
        expected = safe_path(ROOT, ".ctx/outputs/source-security.json")
        require(env.get("CTX_OUTPUT") == str(expected), "adapter requires workflow-owned output path")
        expected.unlink(missing_ok=True)
        result = source_security(ROOT, env)
        write_json(ROOT, ".ctx/outputs/source-security.json", result)
        print(json.dumps({"step": "source-security", "status": "passed"}))
        return 0
    except Blocked as exc:
        print(json.dumps({"step": "source-security", "status": "blocked", "reason": str(exc)}))
        return 2
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print(json.dumps({"step": "source-security", "status": "blocked",
                          "reason": "invalid or unavailable security tool evidence"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
