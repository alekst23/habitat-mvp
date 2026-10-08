"""Reconcile delivery evidence. No network, deployment, approval or signing authority.

This checks receipt consistency, NOT whether a remote job ran or an approval is
authentic. Protected jobs and independent GitLab readback remain mandatory.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from ctx_workflow import (ROOT, STEPS, IDENTITY_KEYS, SHA, Invalid, https_url,
                          matches, positive_integer, require, validate_evidence)

STAGES = ("plan", "create", "verify", "package", "secure", "release", "configure", "monitor", "govern")
CONTROLS = ("license", "dco", "branch_protection", "merge_policy", "environment_protection")
EXTRA = {
    "plan": (), "create": ("plan",),
    "govern": (*STEPS, "plan", "create"),
    "release-staging": ("govern",),
    "monitor-staging": ("release-staging",),
    "configure-production": ("govern",),
    "approval-production": ("monitor-staging", "configure-production"),
    "release-production": ("approval-production",),
    "monitor-production": ("release-production",),
}
PHASES = {
    "candidate": (*STEPS, "plan", "create", "govern"),
    "staging": (*STEPS, "plan", "create", "govern", "release-staging", "monitor-staging"),
}
PHASES["promotion"] = (*PHASES["staging"], "configure-production", "approval-production")
PHASES["production"] = (*PHASES["promotion"], "release-production", "monitor-production")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def same_project_url(value, project_url, suffix=r".+"):
    return isinstance(value, str) and re.fullmatch(re.escape(project_url) + r"/-/" + suffix, value) is not None


def timestamp(value):
    require(isinstance(value, str), "timestamp required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None, "timestamp must have timezone")
    return result


def extra_evidence(name, evidence, passed, identity, project_url):
    def link(field, suffix=r".+"):
        require(same_project_url(evidence.get(field), project_url, suffix), f"invalid {field}")

    if name == "plan":
        link("source_issue_url", r"(?:issues|work_items)/[1-9][0-9]*")
        link("epic_url", r"(?:issues|work_items)/[1-9][0-9]*")
        require(matches(SHA, evidence.get("spec_sha")), "committed spec SHA required")
        require(evidence.get("design_confirmed") is True, "design confirmation missing")
    elif name == "create":
        link("merge_request_url", r"merge_requests/[1-9][0-9]*")
        require(evidence.get("merged") is True and evidence.get("merge_sha") == identity["source_sha"],
                "candidate is not the recorded merged release SHA")
    elif name == "govern":
        require(evidence.get("checks") == {key: "passed" for key in CONTROLS}, "governance controls incomplete")
        for control in CONTROLS:
            require(same_project_url(evidence.get("control_urls", {}).get(control), project_url),
                    f"missing governance evidence URL: {control}")
        require(evidence.get("environment") == "staging", "staging controls required")
        require(evidence.get("configuration_revision") == passed["configure"]["evidence"]["configuration_revision"],
                "governance configuration mismatch")
        require(evidence.get("artifact_digest") == passed["package"]["evidence"]["artifact_digest"],
                "governance artifact mismatch")
    else:
        environment = name.rsplit("-", 1)[1]
        require(evidence.get("environment") == environment, "target environment mismatch")
        require(evidence.get("artifact_digest") == passed["package"]["evidence"]["artifact_digest"],
                "candidate artifact mismatch")
        if name == "configure-production":
            require(matches(re.compile(r"[0-9a-f]{64}"), evidence.get("configuration_revision")),
                    "production configuration hash required")
            require(evidence.get("passed") is True and evidence.get("protected_environment") is True,
                    "production configuration/protection not verified")
            link("controls_url")
            return
        config = passed["configure" if environment == "staging" else "configure-production"]["evidence"]
        require(evidence.get("configuration_revision") == config["configuration_revision"],
                "effective configuration mismatch")
        require(positive_integer(evidence.get("deployment_id")), "deployment ID required")
        if name == "approval-production":
            require(evidence.get("approval_kind") == "protected_environment", "MR/manual-button approval is insufficient")
            require(evidence.get("decision") == "approved", "human outcome approval missing")
            approver, initiator = evidence.get("approver_id"), evidence.get("initiator_id")
            require(positive_integer(approver) and positive_integer(initiator) and approver != initiator,
                    "independent human approver required")
            link("approval_url", r"environments/[1-9][0-9]*(?:/deployments/[1-9][0-9]*)?")
            timestamp(evidence.get("approved_at"))
        elif name.startswith("release-"):
            require(evidence.get("deployed") is True and evidence.get("configuration_applied") is True,
                    "actual deployment and applied configuration required")
            require(https_url(evidence.get("environment_url")), "environment URL required")
            link("deployment_url", r"environments/[1-9][0-9]*(?:/deployments/[1-9][0-9]*)?")
            deployed_at = timestamp(evidence.get("deployed_at"))
            if environment == "production":
                approval = passed["approval-production"]["evidence"]
                require(evidence["deployment_id"] == approval["deployment_id"], "approval is for another deployment")
                require(deployed_at >= timestamp(approval["approved_at"]), "deployment predates approval")
        elif name.startswith("monitor-"):
            deployment = passed[f"release-{environment}"]["evidence"]
            require(evidence["deployment_id"] == deployment["deployment_id"], "health evidence names another deployment")
            require(evidence.get("environment_url") == deployment["environment_url"], "health target mismatch")
            require(evidence.get("checks") == {key: "passed" for key in ("health", "smoke", "logs", "metrics")},
                    "health/smoke/logs/metrics evidence incomplete")
            start, end = timestamp(evidence.get("observed_from")), timestamp(evidence.get("observed_until"))
            require(timestamp(deployment.get("deployed_at")) <= start < end,
                    "invalid post-deployment observation window")


def assess(reports, identity, project_url, phase="candidate"):
    require(phase in PHASES, "unknown assessment phase")
    require(isinstance(reports, dict), "reports must be an object")
    require(matches(SHA, identity.get("source_sha")), "invalid release SHA")
    require(all(re.fullmatch(r"[1-9][0-9]*", str(identity.get(key, "")))
                for key in ("project_id", "pipeline_id")), "real project/pipeline IDs required")
    require(https_url(project_url) and re.fullmatch(r"https://[^/?#]+/(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+", project_url),
            "canonical project URL required")
    passed, gaps = {}, {}
    dependencies = {s: STEPS[:i] for i, s in enumerate(STEPS)} | EXTRA
    for name in dependencies:
        try:
            report = reports.get(name)
            require(isinstance(report, dict), "missing report")
            require(report.get("step") == name and report.get("status") == "passed", "report not passed")
            require(all(report.get(key) == identity[key] for key in IDENTITY_KEYS), "wrong project, SHA or pipeline")
            require(all(dep in passed for dep in dependencies[name]), "prerequisite evidence incomplete")
            evidence = report.get("evidence")
            require(isinstance(evidence, dict), "evidence object required")
            require(evidence.get("source_sha") == identity["source_sha"], "evidence SHA mismatch")
            require(same_project_url(evidence.get("report_url"), project_url, r"jobs/[1-9][0-9]*(?:/artifacts/.+)?"),
                    "same-project CI evidence URL required")
            if name in STEPS:
                validate_evidence(name, evidence, identity, passed)
            else:
                extra_evidence(name, evidence, passed, identity, project_url)
            passed[name] = report
        except (Invalid, ValueError, TypeError, KeyError, AttributeError) as exc:
            gaps[name] = str(exc)
    environment = "production" if phase == "production" else "staging"
    stage_requirements = {
        "plan": ("plan",), "create": ("create",), "verify": ("verify", "acceptance"),
        "package": ("package",), "secure": ("source-security", "artifact-security"),
        "release": (f"release-{environment}",),
        "configure": (f"release-{environment}",),  # Validation is not application.
        "monitor": (f"monitor-{environment}",),
        "govern": ("govern",) + (("approval-production",) if phase in ("promotion", "production") else ()),
    }
    stages = {stage: {"status": "evidence_complete" if all(s in passed for s in needs) else "incomplete",
                      "reports": list(needs),
                      "evidence_urls": [passed[s]["evidence"]["report_url"] for s in needs if s in passed]}
              for stage, needs in stage_requirements.items()}
    required_gaps = {name: gaps[name] for name in PHASES[phase] if name in gaps}
    return {"version": 1, **identity, "project_url": project_url, "phase": phase,
            "status": "blocked" if required_gaps else "evidence_complete",
            "authorizes_deployment": False, "remote_verification": "required",
            "artifact_digest": passed.get("package", {}).get("evidence", {}).get("artifact_digest"),
            "configuration_revisions": {env: passed[name]["evidence"]["configuration_revision"]
                                        for env, name in (("staging", "configure"), ("production", "configure-production"))
                                        if name in passed},
            "stages": stages, "blockers": required_gaps,
            "missing_evidence": gaps,
            "nine_stage_evidence_complete": all(s["status"] == "evidence_complete" for s in stages.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=PHASES, default="candidate")
    args = parser.parse_args()
    output = ROOT / ".ctx/reports/delivery-readiness.json"
    if any(p.is_symlink() for p in (output, *output.parents)):
        print(json.dumps({"status": "blocked", "reason": "symlink report/output path refused",
                          "authorizes_deployment": False}))
        return 2
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        identity = {"project_id": os.environ.get("CI_PROJECT_ID"), "source_sha": os.environ.get("CI_COMMIT_SHA"),
                    "pipeline_id": os.environ.get("CI_PIPELINE_ID")}
        require(head == identity["source_sha"], "checkout must match release pipeline SHA")
        require(os.environ.get("CI_DEFAULT_BRANCH") and
                os.environ.get("CI_COMMIT_BRANCH") == os.environ["CI_DEFAULT_BRANCH"],
                "release assessment requires the actual default branch")
        require(not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"],
                                            cwd=ROOT, text=True).strip(),
                "candidate checkout is dirty; commit before evaluating SHA-bound receipts")
        reports = {}
        for name in (*STEPS, *EXTRA):
            path = output.parent / f"{name}.json"
            require(not path.is_symlink(), "symlink report refused")
            if path.is_file():
                require(path.stat().st_size <= 1024 * 1024, "report exceeds 1 MiB")
                reports[name] = json.loads(path.read_text(), object_pairs_hook=unique_object)
        result = assess(reports, identity, os.environ.get("CI_PROJECT_URL", ""), args.phase)
    except (Invalid, OSError, ValueError, TypeError, subprocess.CalledProcessError) as exc:
        result = {"status": "blocked", "reason": str(exc), "authorizes_deployment": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "evidence_complete" else 2


if __name__ == "__main__":
    sys.exit(main())
