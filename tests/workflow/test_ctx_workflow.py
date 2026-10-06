import contextlib
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ctx_workflow", ROOT / "scripts/ctx_workflow.py")
ctx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctx)
SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64
IDENTITY = {"project_id": "87271414", "source_sha": SHA, "pipeline_id": "42"}


def evidence(step):
    result = {"source_sha": SHA, "report_url": "https://gitlab.com/example/job/1"}
    result.update({
        "verify": {"tests_total": 5, "passed": True},
        "source-security": {"checks": {"source": "passed", "dependency": "passed", "secrets": "passed"},
                            "blocking_findings": 0},
        "package": {"artifact_digest": DIGEST, "artifact_url": "https://registry.example/artifact",
                    "sbom_url": "https://gitlab.com/example/sbom"},
        "artifact-security": {"artifact_digest": DIGEST, "blocking_findings": 0, "passed": True},
        "configure": {"artifact_digest": DIGEST, "configuration_revision": "c" * 64,
                      "environment": "staging", "passed": True},
    }[step])
    return result


def reports():
    return {s: {**IDENTITY, "step": s, "status": "passed", "evidence": evidence(s)} for s in ctx.STEPS}


class FlowTests(unittest.TestCase):
    def setUp(self):
        catalog = json.loads((ROOT / ".gitlab/ctx/catalog.json").read_text())
        path = ".gitlab/duo/flows/ctx-ticket.yml"
        self.registration = catalog["flows"][path]
        self.flow = ctx.read_yaml(ROOT / path)

    def test_repository_contracts(self):
        self.assertEqual(ctx.validate_repository()["flows"], 5)

    def test_unknown_response_aborts(self):
        for route in self.flow["routers"]:
            self.assertEqual(route["condition"]["routes"]["default_route"], "abort")

    def test_tests_precede_implementation(self):
        routes = {r["from"]: r["condition"]["routes"] for r in self.flow["routers"]}
        self.assertEqual(routes["design"]["ready"], "tests")
        self.assertEqual(routes["tests"]["ready"], "implementation")
        self.assertEqual(routes["implementation"]["ready"], "review")
        self.assertEqual(routes["review"]["ready"], "close")

    def test_review_cannot_mutate_code(self):
        for component in self.flow["components"]:
            if component["name"] == "review":
                component["toolset"].append("run_command")
        with self.assertRaisesRegex(ctx.Invalid, "reviewer"):
            ctx.validate_flow(self.flow, self.registration)

    def test_restricted_custom_flow_field_rejected(self):
        self.flow["name"] = "not allowed in custom flows"
        with self.assertRaises(ctx.Invalid):
            ctx.validate_flow(self.flow, self.registration)

    def test_missing_project_identity_rejected(self):
        self.flow["components"][0]["inputs"].pop()
        with self.assertRaisesRegex(ctx.Invalid, "inputs"):
            ctx.validate_flow(self.flow, self.registration)

    def test_unknown_tool_rejected(self):
        self.flow["components"][0]["toolset"].append("invented_tool")
        with self.assertRaisesRegex(ctx.Invalid, "unknown tool"):
            ctx.validate_flow(self.flow, self.registration)

    def test_unknown_target_rejected(self):
        self.flow["routers"][1]["condition"]["routes"]["ready"] = "missing"
        with self.assertRaisesRegex(ctx.Invalid, "routing target"):
            ctx.validate_flow(self.flow, self.registration)

    def test_cycles_rejected(self):
        self.flow["routers"][-1]["condition"]["routes"]["ready"] = "design"
        with self.assertRaisesRegex(ctx.Invalid, "cycle"):
            ctx.validate_flow(self.flow, self.registration)

    def test_blocked_cannot_continue(self):
        self.flow["routers"][1]["condition"]["routes"]["blocked"] = "tests"
        with self.assertRaisesRegex(ctx.Invalid, "abort"):
            ctx.validate_flow(self.flow, self.registration)

    def test_duplicate_yaml_keys_rejected(self):
        with self.assertRaisesRegex(ctx.Invalid, "duplicate YAML"):
            yaml.load("rules: blocked\nrules: passed\n", Loader=ctx.UniqueLoader)

    def test_shell_string_not_command_array(self):
        config = ctx.read_yaml(ROOT / ".gitlab/ctx/commands.yml")
        config["commands"]["verify"]["argv"] = "echo passed && deploy"
        with self.assertRaisesRegex(ctx.Invalid, "argument array"):
            ctx.validate_commands(config)


class WaveTests(unittest.TestCase):
    def setUp(self):
        self.state = {"version": 1, "project_id": "87271414", "epic": "EPIC-I1", "tickets": [
            {"id": "T-I2", "depends_on": [], "status": "pending"},
            {"id": "T-I3", "depends_on": [], "status": "pending"},
            {"id": "T-I4", "depends_on": ["T-I2", "T-I3"], "status": "pending"},
        ]}

    def mark_done(self, index):
        self.state["tickets"][index].update(status="done", integration={
            "source_sha": SHA, "epic_sha": "d" * 40,
            "pipeline_url": "https://gitlab.com/example/pipeline/1",
            "review_url": "https://gitlab.com/example/review/1"})

    def test_independent_tickets_share_wave(self):
        self.assertEqual(ctx.ready_wave(self.state)["ready"], ["T-I2", "T-I3"])

    def test_integration_unlocks_dependent(self):
        self.mark_done(0)
        self.mark_done(1)
        self.assertEqual(ctx.ready_wave(self.state)["ready"], ["T-I4"])

    def test_partial_epic_not_complete(self):
        self.mark_done(0)
        self.assertFalse(ctx.ready_wave(self.state)["complete"])

    def test_running_not_dispatched_again(self):
        self.state["tickets"][0].update(status="running", session_url="https://gitlab.com/session/1")
        result = ctx.ready_wave(self.state)
        self.assertEqual(result["ready"], ["T-I3"])
        self.assertEqual(result["in_flight"], ["T-I2"])

    def test_blocked_is_not_done(self):
        self.state["tickets"][0]["status"] = "blocked"
        self.assertEqual(ctx.ready_wave(self.state)["ready"], ["T-I3"])

    def test_done_requires_evidence(self):
        self.state["tickets"][0]["status"] = "done"
        with self.assertRaisesRegex(ctx.Invalid, "source SHA"):
            ctx.ready_wave(self.state)

    def test_unknown_dependency(self):
        self.state["tickets"][0]["depends_on"] = ["T-I999"]
        with self.assertRaisesRegex(ctx.Invalid, "unknown dependency"):
            ctx.ready_wave(self.state)

    def test_dependency_cycle(self):
        self.state["tickets"][0]["depends_on"] = ["T-I4"]
        with self.assertRaisesRegex(ctx.Invalid, "cycle"):
            ctx.ready_wave(self.state)

    def test_premature_integration_rejected(self):
        self.mark_done(2)
        with self.assertRaisesRegex(ctx.Invalid, "before dependency"):
            ctx.ready_wave(self.state)

    def test_duplicate_ticket_rejected(self):
        self.state["tickets"].append(deepcopy(self.state["tickets"][0]))
        with self.assertRaisesRegex(ctx.Invalid, "duplicate"):
            ctx.ready_wave(self.state)


class EvidenceTests(unittest.TestCase):
    def test_malformed_evidence_and_urls_rejected(self):
        for url in (None, 123, "https://", "http://insecure.example", "https://user:secret@example.com"):
            with self.subTest(url=url):
                data = evidence("verify")
                data["report_url"] = url
                with self.assertRaises(ctx.Invalid):
                    ctx.validate_evidence("verify", data, IDENTITY, {})
        for value in (None, [], "passed"):
            data = evidence("source-security")
            data["checks"] = value
            with self.assertRaises(ctx.Invalid):
                ctx.validate_evidence("source-security", data, IDENTITY, {})

    def test_matching_evidence_chain(self):
        ctx.validate_prior("configure", reports(), IDENTITY)
        ctx.validate_evidence("configure", evidence("configure"), IDENTITY, reports())

    def test_stale_sha_wrong_project_and_pipeline_rejected(self):
        for key in ctx.IDENTITY_KEYS:
            with self.subTest(key=key):
                previous = reports()
                previous["verify"][key] = "different"
                with self.assertRaisesRegex(ctx.Invalid, "stale"):
                    ctx.validate_prior("package", previous, IDENTITY)

    def test_missing_and_failed_prerequisites(self):
        for status in (None, "blocked", "failed", "skipped"):
            with self.subTest(status=status):
                previous = reports()
                if status is None:
                    del previous["verify"]
                else:
                    previous["verify"]["status"] = status
                with self.assertRaises(ctx.Invalid):
                    ctx.validate_prior("package", previous, IDENTITY)

    def test_no_tests_not_passing(self):
        for total in (0, -1, True, "5"):
            data = evidence("verify")
            data["tests_total"] = total
            with self.assertRaises(ctx.Invalid):
                ctx.validate_evidence("verify", data, IDENTITY, {})

    def test_missing_secret_scan_blocks_package(self):
        previous = reports()
        del previous["source-security"]["evidence"]["checks"]["secrets"]
        with self.assertRaisesRegex(ctx.Invalid, "secrets"):
            ctx.validate_prior("package", previous, IDENTITY)

    def test_digest_mismatch_blocks_scan_and_config(self):
        for step in ("artifact-security", "configure"):
            data = evidence(step)
            data["artifact_digest"] = "sha256:" + "f" * 64
            with self.assertRaisesRegex(ctx.Invalid, "digest mismatch"):
                ctx.validate_evidence(step, data, IDENTITY, reports())

    def test_mutable_tag_not_artifact_digest(self):
        data = evidence("package")
        data["artifact_digest"] = "habitat:latest"
        with self.assertRaisesRegex(ctx.Invalid, "immutable"):
            ctx.validate_evidence("package", data, IDENTITY, {})

    def test_production_config_not_supported(self):
        data = evidence("configure")
        data["environment"] = "production"
        with self.assertRaisesRegex(ctx.Invalid, "staging"):
            ctx.validate_evidence("configure", data, IDENTITY, reports())


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ctx-test-")
        self.root = Path(self.temp.name)
        self.config = ctx.read_yaml(ROOT / ".gitlab/ctx/commands.yml")
        (self.root / ".gitlab/ctx").mkdir(parents=True)
        self.git = patch.object(ctx.subprocess, "check_output", side_effect=lambda args, **kw:
                                SHA + "\n" if args[1] == "rev-parse" else "")
        self.git.start()

    def tearDown(self):
        self.git.stop()
        self.temp.cleanup()

    def run_step(self, argv=None):
        self.config["commands"]["verify"]["argv"] = argv
        (self.root / ".gitlab/ctx/commands.yml").write_text(yaml.safe_dump(self.config))
        with contextlib.redirect_stdout(io.StringIO()):
            code = ctx.execute_step("verify", self.root, {"PATH": os.environ["PATH"]})
        return code, json.loads((self.root / ".ctx/reports/verify.json").read_text())

    def test_missing_command_emits_blocked_report(self):
        code, report = self.run_step()
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("not configured", report["reason"])

    def test_success_without_evidence_is_blocked(self):
        code, report = self.run_step([sys.executable, "-c", "pass"])
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "blocked")

    def test_command_failure_retained(self):
        code, report = self.run_step([sys.executable, "-c", "raise SystemExit(9)"])
        self.assertEqual(code, 1)
        self.assertEqual(report["exit_code"], 9)

    def test_stale_output_not_reused(self):
        (self.root / ".ctx/outputs").mkdir(parents=True)
        (self.root / ".ctx/outputs/verify.json").write_text(json.dumps(evidence("verify")))
        code, _ = self.run_step([sys.executable, "-c", "pass"])
        self.assertEqual(code, 2)

    def test_real_command_and_fresh_evidence_pass(self):
        script = "import os,pathlib; pathlib.Path(os.environ['CTX_OUTPUT']).write_text(" + repr(json.dumps(evidence("verify"))) + ")"
        code, report = self.run_step([sys.executable, "-c", script])
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "passed")

    def test_timeout_fails(self):
        with patch.object(ctx.subprocess, "run", side_effect=subprocess.TimeoutExpired("adapter", 1)):
            code, report = self.run_step([sys.executable, "-c", "pass"])
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "failed")

    def test_dirty_checkout_blocks_execution(self):
        with patch.object(ctx.subprocess, "check_output", side_effect=[SHA + "\n", " M app.py\n"]):
            code, report = self.run_step([sys.executable, "-c", "pass"])
        self.assertEqual(code, 2)
        self.assertIn("dirty", report["reason"])

    def test_adapter_cannot_change_candidate(self):
        with patch.object(ctx.subprocess, "check_output", side_effect=[SHA + "\n", "", "d" * 40]):
            code, report = self.run_step([sys.executable, "-c", "pass"])
        self.assertEqual(code, 2)
        self.assertIn("changed the candidate", report["reason"])


if __name__ == "__main__":
    unittest.main()
