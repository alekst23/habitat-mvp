"""Delivery control tests use synthetic receipts, never real deployment evidence."""

from copy import deepcopy
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ctx_workflow as workflow
import ctx_delivery as delivery

PROJECT = "https://gitlab.com/example/showcase"


def receipts():
    from test_ctx_workflow import reports, IDENTITY, DIGEST
    result = reports()
    config = "c" * 64
    fields = {
        "plan": {"source_issue_url": PROJECT + "/-/issues/10", "epic_url": PROJECT + "/-/issues/2",
                 "spec_sha": "d" * 40, "design_confirmed": True},
        "create": {"merged": True, "merge_sha": IDENTITY["source_sha"], "merge_request_url": PROJECT + "/-/merge_requests/7"},
        "govern": {"checks": {key: "passed" for key in delivery.CONTROLS},
                   "control_urls": {key: PROJECT + "/-/jobs/15" for key in delivery.CONTROLS}},
        "configure-production": {"passed": True, "protected_environment": True, "controls_url": PROJECT + "/-/jobs/16"},
        "approval-production": {"approval_kind": "protected_environment", "decision": "approved",
                                "approver_id": 2, "initiator_id": 1, "approved_at": "2026-10-08T11:00:00Z",
                                "approval_url": PROJECT + "/-/environments/2/deployments/43"},
    }
    for env in ("staging", "production"):
        fields[f"release-{env}"] = {"deployed": True, "configuration_applied": True,
                                   "deployment_url": PROJECT + "/-/environments/2/deployments/43",
                                   "environment_url": f"https://{env}.example.com",
                                   "deployed_at": "2026-10-08T12:00:00Z"}
        fields[f"monitor-{env}"] = {"checks": {key: "passed" for key in ("health", "smoke", "logs", "metrics")},
                                   "environment_url": f"https://{env}.example.com",
                                   "observed_from": "2026-10-08T12:00:01Z", "observed_until": "2026-10-08T12:01:00Z"}
    for name, value in fields.items():
        environment = "production" if name.endswith("production") else "staging"
        evidence = {"source_sha": IDENTITY["source_sha"], "artifact_digest": DIGEST,
                    "configuration_revision": "e" * 64 if environment == "production" else config,
                    "environment": environment, "deployment_id": 43, **value}
        result[name] = {**IDENTITY, "step": name, "status": "passed", "evidence": evidence}
    for report in result.values():
        report["evidence"]["report_url"] = PROJECT + "/-/jobs/14/artifacts/file/evidence.json"
    return result, IDENTITY


class DeliveryCITests(unittest.TestCase):
    def test_workflow_checks_run_without_opt_in_on_mrs_and_default_branch(self):
        ci = workflow.read_yaml(ROOT / ".gitlab-ci.yml")
        for job in ("ctx:workflow-validate", "ctx:workflow-tests"):
            rules = ci[job]["rules"]
            self.assertIn({"if": '$CI_PIPELINE_SOURCE == "merge_request_event"'}, rules)
            self.assertIn({"if": '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'}, rules)

    def test_readiness_job_collects_all_prerequisites_without_deploying(self):
        jobs = workflow.read_yaml(ROOT / ".gitlab/ci/delivery.yml")
        job = jobs["ctx:delivery-readiness"]
        self.assertEqual(set(job["needs"]), {f"ctx:{s}" for s in workflow.STEPS})
        self.assertEqual(job["when"], "always")
        self.assertEqual(job["rules"], [{"if": '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH',
                                        "exists": ["docs/plan/E*/state.json"]}])
        self.assertEqual(job["script"], ["python scripts/ctx_ci_context.py delivery-readiness"])
        self.assertNotIn("environment", job)

    def test_automatic_application_jobs_are_not_excluded_from_mr_pipelines(self):
        jobs = workflow.read_yaml(ROOT / ".gitlab/ci/delivery.yml")
        self.assertIn({"if": '$CI_PIPELINE_SOURCE == "merge_request_event"',
                       "exists": ["docs/plan/E*/state.json"]},
                      jobs[".ctx-check"].get("rules", []))


class DeliveryEvidenceTests(unittest.TestCase):
    def test_candidate_is_not_deployed_or_nine_stage_complete(self):
        data, identity = receipts()
        data = {key: value for key, value in data.items() if key in delivery.PHASES["candidate"]}
        result = delivery.assess(data, identity, PROJECT)
        self.assertEqual(result["status"], "evidence_complete")
        self.assertFalse(result["authorizes_deployment"])
        self.assertFalse(result["nine_stage_evidence_complete"])
        for stage in ("release", "configure", "monitor"):
            self.assertEqual(result["stages"][stage]["status"], "incomplete")
        result = delivery.assess(data, identity, PROJECT, "staging")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("release-staging", result["blockers"])

    def test_staging_and_production_have_distinct_evidence_and_human_gate(self):
        data, identity = receipts()
        for phase in delivery.PHASES:
            result = delivery.assess(data, identity, PROJECT, phase)
            self.assertEqual(result["status"], "evidence_complete", result["blockers"])
            self.assertFalse(result["authorizes_deployment"])
            self.assertEqual(result["remote_verification"], "required")
        data["approval-production"]["evidence"]["decision"] = "pending"
        self.assertEqual(delivery.assess(data, identity, PROJECT, "staging")["status"], "evidence_complete")
        self.assertEqual(delivery.assess(data, identity, PROJECT, "promotion")["status"], "blocked")
        self.assertEqual(delivery.assess(data, identity, PROJECT, "production")["status"], "blocked")

    def test_wrong_pipeline_sha_or_project_and_missing_scans_block_candidate(self):
        data, identity = receipts()
        for field, value in (("project_id", "999"), ("pipeline_id", "99"), ("source_sha", "f" * 40), ("status", "skipped")):
            with self.subTest(field=field):
                bad = deepcopy(data)
                bad["verify"][field] = value
                result = delivery.assess(bad, identity, PROJECT)
                self.assertEqual(result["status"], "blocked")
                self.assertIn("verify", result["blockers"])
                self.assertIn("package", result["blockers"])
        del data["source-security"]["evidence"]["checks"]["dependency"]
        self.assertEqual(delivery.assess(data, identity, PROJECT)["status"], "blocked")

    def test_changed_artifact_configuration_or_deployment_invalidates_downstream(self):
        original, identity = receipts()
        for name, field, value in (
            ("package", "artifact_digest", "sha256:" + "f" * 64),
            ("configure", "configuration_revision", "f" * 64),
            ("configure-production", "configuration_revision", "f" * 64),
            ("monitor-production", "deployment_id", 44),
            ("release-production", "deployment_id", 44),
            ("release-staging", "configuration_applied", False),
        ):
            with self.subTest(name=name, field=field):
                data = deepcopy(original)
                data[name]["evidence"][field] = value
                result = delivery.assess(data, identity, PROJECT, "production")
                self.assertEqual(result["status"], "blocked")
                self.assertFalse(result["nine_stage_evidence_complete"])

    def test_foreign_links_self_approval_and_predeployment_health_fail(self):
        original, identity = receipts()
        for name, field, value in (
            ("verify", "report_url", "https://gitlab.com/foreign/repo/-/jobs/14"),
            ("approval-production", "approver_id", 1),
            ("approval-production", "approval_kind", "mr"),
            ("approval-production", "approval_url", PROJECT + "/-/merge_requests/7"),
            ("monitor-staging", "observed_from", "2026-10-08T11:00:00Z"),
            ("monitor-production", "observed_until", "2026-10-08T12:00:00Z"),
            ("release-production", "deployed_at", "2026-10-08T10:00:00Z"),
        ):
            with self.subTest(name=name, field=field):
                data = deepcopy(original)
                data[name]["evidence"][field] = value
                self.assertEqual(delivery.assess(data, identity, PROJECT, "production")["status"], "blocked")

    def test_missing_receipts_and_duplicate_json_fail_closed(self):
        _, identity = receipts()
        result = delivery.assess({}, identity, PROJECT)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(set(result["stages"]), set(delivery.STAGES))
        self.assertTrue(all(stage["status"] == "incomplete" for stage in result["stages"].values()))
        with self.assertRaisesRegex(workflow.Invalid, "duplicate JSON"):
            json.loads('{"status":"failed","status":"passed"}', object_pairs_hook=delivery.unique_object)

    def test_cli_retains_readiness_and_blocked_diagnostics(self):
        data, identity = receipts()
        env = {"CI_PROJECT_ID": identity["project_id"], "CI_PIPELINE_ID": identity["pipeline_id"],
               "CI_COMMIT_SHA": identity["source_sha"], "CI_PROJECT_URL": PROJECT,
               "CI_COMMIT_BRANCH": "main", "CI_DEFAULT_BRANCH": "main"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            reports = root / ".ctx/reports"
            reports.mkdir(parents=True)
            for name, report in data.items():
                (reports / f"{name}.json").write_text(json.dumps(report))
            with patch.object(delivery, "ROOT", root), patch.dict(os.environ, env, clear=True), \
                    patch.object(sys, "argv", ["ctx_delivery.py"]), contextlib.redirect_stdout(io.StringIO()):
                with patch.object(delivery.subprocess, "check_output", side_effect=[identity["source_sha"], ""]):
                    self.assertEqual(delivery.main(), 0)
                saved = json.loads((reports / "delivery-readiness.json").read_text())
                self.assertEqual(saved["source_sha"], identity["source_sha"])
                self.assertFalse(saved["authorizes_deployment"])
                (reports / "verify.json").write_text('{"status":"failed","status":"passed"}')
                with patch.object(delivery.subprocess, "check_output", side_effect=[identity["source_sha"], ""]):
                    self.assertEqual(delivery.main(), 2)
                self.assertIn("duplicate JSON", json.loads((reports / "delivery-readiness.json").read_text())["reason"])
                with patch.object(delivery.subprocess, "check_output", side_effect=[identity["source_sha"], " M app.py"]):
                    self.assertEqual(delivery.main(), 2)
                self.assertIn("dirty", json.loads((reports / "delivery-readiness.json").read_text())["reason"])


if __name__ == "__main__":
    unittest.main()
