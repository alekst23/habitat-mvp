import contextlib
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import re
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
        "acceptance": {"criteria_total": 2, "passed": True, "scope": "E2-1",
                       "manifest_sha256": "d" * 64},
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
        path = ".gitlab/duo/flows/ctx-development.yml"
        self.registration = catalog["flows"][path]
        self.flow = ctx.read_yaml(ROOT / path)

    def test_repository_contracts(self):
        self.assertEqual(ctx.validate_repository()["flows"], 3)

    def test_all_flow_prompts_use_epic_local_numbering(self):
        for path in (ROOT / ".gitlab/duo/flows").glob("*.yml"):
            flow = ctx.read_yaml(path)
            for prompt in flow["prompts"]:
                with self.subTest(flow=path.name, prompt=prompt["prompt_id"]):
                    text = prompt["prompt_template"]["system"]
                    self.assertIn("E<epic-issue-iid>-<ticket-number>", text)
                    self.assertIn("actual parent epic issue, never the intake issue", text)
                    self.assertNotIn("T-I<", text)
                    self.assertNotIn("EPIC-I<", text)

    def test_state_template_uses_new_numbering(self):
        state = json.loads((ROOT / ".gitlab/ctx/templates/state.json").read_text())
        state["project_id"] = "87271414"
        self.assertEqual(state["version"], 2)
        self.assertEqual(ctx.ready_wave(state)["ready"], ["E2-1"])

    def test_unknown_response_aborts(self):
        for route in self.flow["routers"]:
            self.assertEqual(route["condition"]["routes"]["default_route"], "abort")

    def test_review_terminal_contract_rejects_destination_and_missing_tokens(self):
        for declaration in ("[integrate, blocked]", "[ready]", "[ready, blocked, default_route]", None):
            with self.subTest(declaration=declaration):
                flow = deepcopy(self.flow)
                review = next(p for p in flow["prompts"] if p["prompt_id"] == "review_prompt")
                system = re.sub(r"(?m)^\s*Terminal tokens:.*$", "", review["prompt_template"]["system"])
                if declaration is not None:
                    system += f"\nTerminal tokens: {declaration}\n"
                review["prompt_template"]["system"] = system
                with self.assertRaisesRegex(ctx.Invalid, "terminal token"):
                    ctx.validate_flow(flow, self.registration)

    def test_router_cannot_drift_from_documented_outputs(self):
        review = next(r for r in self.flow["routers"] if r["from"] == "review")
        review["condition"]["routes"]["integrate"] = review["condition"]["routes"].pop("ready")
        with self.assertRaisesRegex(ctx.Invalid, "terminal token"):
            ctx.validate_flow(self.flow, self.registration)

    def test_catalog_and_review_skill_cannot_add_terminal_tokens(self):
        registration = deepcopy(self.registration)
        registration["terminal_tokens"]["review"].append("integrate")
        with self.assertRaisesRegex(ctx.Invalid, "catalog terminal tokens"):
            ctx.validate_flow(self.flow, registration)

        path = "skills/ctx-ticket-review/SKILL.md"
        text = (ROOT / path).read_text()
        self.assertEqual(ctx.documented_terminal_tokens(text, path), {"ready", "blocked"})
        review = next(p for p in self.flow["prompts"] if p["prompt_id"] == "review_prompt")
        flow = {"prompts": [review]}
        ctx.validate_skill_terminal_tokens(flow, {path: text})
        wrong = text.replace("Terminal tokens: [ready, blocked]", "Terminal tokens: [integrate, blocked]")
        with self.assertRaisesRegex(ctx.Invalid, "skill terminal tokens"):
            ctx.validate_skill_terminal_tokens(flow, {path: wrong})

    def test_review_verdict_uses_result_token_not_next_component(self):
        review = next(r for r in self.flow["routers"] if r["from"] == "review")["condition"]["routes"]
        self.assertEqual(review["ready"], "integrate")
        self.assertEqual(review.get("integrate", review["default_route"]), "abort")
        for token in ("ready\nMore details", "```ready```", "approved", "ready "):
            self.assertEqual(review.get(token, review["default_route"]), "abort")

    def test_tests_precede_implementation(self):
        routes = {r["from"]: r["condition"]["routes"] for r in self.flow["routers"]}
        self.assertEqual(routes["design"]["ready"], "tests")
        self.assertEqual(routes["tests"]["ready"], "implementation")
        self.assertEqual(routes["implementation"]["ready"], "browser")
        self.assertEqual(routes["browser"]["ready"], "review")
        self.assertEqual(routes["review"]["ready"], "integrate")
        self.assertEqual(routes["integrate"]["complete"], "epic_review")

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
        self.state = {"version": 2, "project_id": "87271414", "epic": "E2",
                      "epic_issue_iid": 2, "source_issue_iid": 1, "next_ticket_number": 4, "tickets": [
            {"id": "E2-1", "issue_iid": 3, "depends_on": [], "status": "pending"},
            {"id": "E2-2", "issue_iid": 4, "depends_on": [], "status": "pending"},
            {"id": "E2-3", "issue_iid": 8, "depends_on": ["E2-1", "E2-2"], "status": "pending"},
        ]}

    def mark_done(self, index):
        self.state["tickets"][index].update(status="done", integration={
            "source_sha": SHA, "epic_sha": "d" * 40,
            "pipeline_url": "https://gitlab.com/example/pipeline/1",
            "review_url": "https://gitlab.com/example/review/1"})

    def test_independent_tickets_share_wave(self):
        self.assertEqual(ctx.ready_wave(self.state)["ready"], ["E2-1", "E2-2"])

    def test_integration_unlocks_dependent(self):
        self.mark_done(0)
        self.mark_done(1)
        self.assertEqual(ctx.ready_wave(self.state)["ready"], ["E2-3"])

    def test_partial_epic_not_complete(self):
        self.mark_done(0)
        self.assertFalse(ctx.ready_wave(self.state)["complete"])

    def test_running_not_dispatched_again(self):
        self.state["tickets"][0].update(status="running", session_url="https://gitlab.com/session/1")
        result = ctx.ready_wave(self.state)
        self.assertEqual(result["ready"], ["E2-2"])
        self.assertEqual(result["in_flight"], ["E2-1"])

    def test_blocked_is_not_done(self):
        self.state["tickets"][0]["status"] = "blocked"
        self.assertEqual(ctx.ready_wave(self.state)["ready"], ["E2-2"])

    def test_done_requires_evidence(self):
        self.state["tickets"][0]["status"] = "done"
        with self.assertRaisesRegex(ctx.Invalid, "source SHA"):
            ctx.ready_wave(self.state)

    def test_unknown_dependency(self):
        self.state["tickets"][0]["depends_on"] = ["E2-999"]
        with self.assertRaisesRegex(ctx.Invalid, "unknown dependency"):
            ctx.ready_wave(self.state)

    def test_dependency_cycle(self):
        self.state["tickets"][0]["depends_on"] = ["E2-3"]
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

    def test_ticket_from_another_epic_rejected(self):
        self.state["tickets"][0]["id"] = "E9-1"
        with self.assertRaisesRegex(ctx.Invalid, "another epic"):
            ctx.ready_wave(self.state)

    def test_epic_identity_cannot_be_intake_identity(self):
        self.state["epic"] = "E1"
        with self.assertRaisesRegex(ctx.Invalid, "does not match"):
            ctx.ready_wave(self.state)

    def test_ticket_issue_identity_is_required_unique_and_not_the_epic(self):
        for value in (None, True, 0, -1, "3", 2, 4):
            with self.subTest(issue_iid=value):
                state = deepcopy(self.state)
                state["tickets"][0]["issue_iid"] = value
                with self.assertRaises(ctx.Invalid):
                    ctx.ready_wave(state)

    def test_malformed_numbering_rejected(self):
        for tid in (None, [], 3, "T-I3", "E2-0", "E2-01", "E02-1", "E0-1", "E2--1"):
            with self.subTest(tid=tid):
                state = deepcopy(self.state)
                state["tickets"][0]["id"] = tid
                with self.assertRaises(ctx.Invalid):
                    ctx.ready_wave(state)

    def test_invalid_counter_rejected(self):
        for counter in (None, True, 0, -1, "4", 3):
            state = deepcopy(self.state)
            state["next_ticket_number"] = counter
            with self.assertRaises(ctx.Invalid):
                ctx.ready_wave(state)

    def test_numeric_wave_order_and_reordering_does_not_renumber(self):
        self.state["tickets"].append({"id": "E2-10", "issue_iid": 99,
                                      "depends_on": [], "status": "pending"})
        self.state["next_ticket_number"] = 11
        self.state["tickets"].reverse()
        before = deepcopy(self.state)
        self.assertEqual(ctx.ready_wave(self.state)["ready"], ["E2-1", "E2-2", "E2-10"])
        self.assertEqual(self.state, before)

    def test_addition_uses_counter_not_issue_iid(self):
        before = deepcopy(self.state)
        result = ctx.add_ticket(self.state, 103, ["E2-1"])
        self.assertEqual(result["tickets"][-1], {"id": "E2-4", "issue_iid": 103,
                                               "depends_on": ["E2-1"], "status": "pending"})
        self.assertEqual(result["next_ticket_number"], 5)
        self.assertEqual(self.state, before)

    def test_repeated_addition_is_idempotent(self):
        result = ctx.add_ticket(self.state, 103, ["E2-1"])
        self.assertEqual(ctx.add_ticket(result, 103), result)
        self.assertEqual(ctx.add_ticket(result, 103, ["E2-1"]), result)
        with self.assertRaisesRegex(ctx.Invalid, "dependencies differ"):
            ctx.add_ticket(result, 103, ["E2-2"])

    def test_closed_and_retired_numbers_are_not_reused(self):
        self.mark_done(0)
        self.state["tickets"][1]["status"] = "blocked"
        self.state["next_ticket_number"] = 7
        result = ctx.add_ticket(self.state, 90)
        self.assertEqual(result["tickets"][-1]["id"], "E2-7")
        self.assertEqual(result["next_ticket_number"], 8)
        self.assertEqual(result["tickets"][:-1], self.state["tickets"])

    def test_other_epic_has_independent_sequence(self):
        other = {"version": 2, "project_id": "87271414", "epic": "E20",
                 "epic_issue_iid": 20, "source_issue_iid": 1, "next_ticket_number": 2,
                 "tickets": [{"id": "E20-1", "issue_iid": 70, "depends_on": [], "status": "pending"}]}
        self.assertEqual(ctx.add_ticket(other, 91)["tickets"][-1]["id"], "E20-2")
        self.assertEqual(ctx.add_ticket(self.state, 92)["tickets"][-1]["id"], "E2-4")

    def test_addition_rejects_unknown_dependencies_and_epic_issue(self):
        with self.assertRaisesRegex(ctx.Invalid, "unknown dependency"):
            ctx.add_ticket(self.state, 103, ["E9-1"])
        with self.assertRaisesRegex(ctx.Invalid, "epic issue"):
            ctx.add_ticket(self.state, 2)


class NumberingMigrationTests(unittest.TestCase):
    def setUp(self):
        self.legacy = {"version": 1, "project_id": "87271414", "epic": "EPIC-I2", "tickets": [
            {"id": "T-I3", "depends_on": [], "status": "pending"},
            {"id": "T-I4", "depends_on": ["T-I3"], "status": "pending"},
            {"id": "T-I5", "depends_on": ["T-I4"], "status": "pending"},
            {"id": "T-I6", "depends_on": ["T-I5"], "status": "pending"},
            {"id": "T-I7", "depends_on": ["T-I5"], "status": "pending"},
            {"id": "T-I8", "depends_on": ["T-I6", "T-I7"], "status": "pending"},
        ]}

    def test_legacy_wave_remains_readable_without_mutation(self):
        before = deepcopy(self.legacy)
        self.assertEqual(ctx.ready_wave(self.legacy)["ready"], ["T-I3"])
        self.assertEqual(self.legacy, before)

    def test_existing_six_ticket_plan_migration(self):
        before = deepcopy(self.legacy)
        result = ctx.migrate_numbering(self.legacy, 2, 1)
        self.assertEqual(result["epic"], "E2")
        self.assertEqual(result["source_issue_iid"], 1)
        self.assertEqual(result["epic_issue_iid"], 2)
        self.assertEqual(result["legacy_epic_id"], "EPIC-I2")
        self.assertEqual(result["next_ticket_number"], 7)
        for number, ticket in enumerate(result["tickets"], 1):
            self.assertEqual(ticket["id"], f"E2-{number}")
            self.assertEqual(ticket["issue_iid"], number + 2)
            self.assertEqual(ticket["legacy_id"], f"T-I{number + 2}")
        self.assertEqual(result["tickets"][-1]["depends_on"], ["E2-4", "E2-5"])
        self.assertEqual(ctx.ready_wave(result)["ready"], ["E2-1"])
        self.assertEqual(self.legacy, before)

    def test_migration_preserves_metadata_status_and_evidence(self):
        self.legacy["branch"] = "ctx/epic-i2"
        self.legacy["tickets"][0].update(status="done", integration={
            "source_sha": SHA, "epic_sha": "d" * 40,
            "pipeline_url": "https://gitlab.com/example/pipeline/1",
            "review_url": "https://gitlab.com/example/review/1"},
            branch="ctx/ticket-i3", mr_iid=11)
        result = ctx.migrate_numbering(self.legacy, 2, 1)
        self.assertEqual(result["branch"], self.legacy["branch"])
        for field in ("integration", "status", "branch", "mr_iid"):
            self.assertEqual(result["tickets"][0][field], self.legacy["tickets"][0][field])
        self.assertEqual(ctx.ready_wave(result)["ready"], ["E2-2"])

    def test_migration_uses_explicit_epic_not_old_intake_suffix(self):
        self.legacy["epic"] = "EPIC-I1"
        self.assertEqual(ctx.migrate_numbering(self.legacy, 2, 1)["epic"], "E2")

    def test_migration_uses_plan_order_not_issue_number_arithmetic(self):
        self.legacy["tickets"] = [
            {"id": "T-I100", "depends_on": ["T-I4"], "status": "pending"},
            {"id": "T-I4", "depends_on": [], "status": "pending"},
        ]
        result = ctx.migrate_numbering(self.legacy, 2, 1)
        self.assertEqual([t["issue_iid"] for t in result["tickets"]], [100, 4])
        self.assertEqual(result["tickets"][0]["depends_on"], ["E2-2"])

    def test_migration_repeated_is_idempotent_and_conflicts_fail(self):
        result = ctx.migrate_numbering(self.legacy, 2, 1)
        self.assertEqual(ctx.migrate_numbering(result, 2, 1), result)
        for epic, source in ((9, 1), (2, 8)):
            with self.assertRaisesRegex(ctx.Invalid, "identity conflict"):
                ctx.migrate_numbering(result, epic, source)

    def test_migration_rejects_conflicting_ticket_mapping(self):
        self.legacy["tickets"][0]["issue_iid"] = 40
        with self.assertRaisesRegex(ctx.Invalid, "identity conflict"):
            ctx.migrate_numbering(self.legacy, 2, 1)

    def test_migration_rejects_invalid_legacy_graph(self):
        self.legacy["tickets"][0]["depends_on"] = ["T-I999"]
        with self.assertRaisesRegex(ctx.Invalid, "unknown dependency"):
            ctx.migrate_numbering(self.legacy, 2, 1)

    def test_legacy_addition_requires_explicit_migration(self):
        with self.assertRaisesRegex(ctx.Invalid, "migrate numbering"):
            ctx.add_ticket(self.legacy, 103)

    def test_migration_cli_is_preview_only(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            original = json.dumps(self.legacy)
            state_file.write_text(original)
            result = subprocess.run([sys.executable, str(ROOT / "scripts/ctx_workflow.py"),
                                     "migrate-numbering", str(state_file), "--epic-issue-iid", "2",
                                     "--source-issue-iid", "1"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["tickets"][0]["id"], "E2-1")
            self.assertEqual(state_file.read_text(), original)


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
