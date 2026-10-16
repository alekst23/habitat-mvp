import contextlib
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("ctx_workflow", ROOT / "scripts/ctx_workflow.py")
ctx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctx)
spec = importlib.util.spec_from_file_location("ctx_routing", ROOT / "scripts/ctx_routing.py")
routing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routing)
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
        # Preserve the original routing-regression tests against the retained chain.
        path = ".gitlab/duo/legacy/ctx-development-single-ticket.yml"
        self.registration = json.loads((ROOT / "tests/workflow/fixtures/single-ticket-registration.json").read_text())
        self.flow = ctx.read_yaml(ROOT / path)

    def route_response(self, source, response, *, stale=False, tampered=False, write_error=False, wrapped=False):
        """Exercise the actual YAML graph, including fixed tools, without GitLab writes."""
        components = {c["name"]: c for c in self.flow["components"]}
        routers = {r["from"]: r for r in self.flow["routers"]}
        state = {source: {"final_answer": response}}

        def value(key):
            result = state
            for part in key.removeprefix("context:").split("."):
                result = result[part]
            return result

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            parser = ROOT / "scripts/ctx_routing.py"
            if parser.exists():
                (root / "scripts/ctx_routing.py").write_bytes(parser.read_bytes())
            if tampered:
                (root / "scripts/ctx_routing.py").write_text('print("design", end="")')
            if stale:
                (root / f"ctx-routing-{source}.input").write_text("design")
            current = source
            for _ in range(10):
                router = routers[current]
                if "to" in router:
                    target = router["to"]
                else:
                    condition = router["condition"]
                    routes = condition["routes"]
                    target = routes.get(value(condition["input"]), routes["default_route"])
                if target in ("end", "abort") or components[target]["type"] == "AgentComponent":
                    return target
                component = components[target]
                args = {i["as"]: i["from"] if i.get("literal") else value(i["from"])
                        for i in component["inputs"]}
                if component["tool_name"] == "create_file_with_contents":
                    if write_error:
                        output = "Action error: file is gitignored"
                        success = False
                    else:
                        (root / args["file_path"]).write_text(args["contents"])
                        output = "File written successfully"
                        success = True
                else:
                    self.assertEqual(component["tool_name"], "run_command")
                    self.assertEqual(args["program"], "python3")
                    process = subprocess.run([sys.executable, *shlex.split(args["args"])],
                                             cwd=root, text=True, capture_output=True, timeout=10)
                    output = process.stdout if process.returncode == 0 else process.stderr
                    success = process.returncode == 0
                state[target] = {"tool_responses": f"<tool_output>{output}</tool_output>" if wrapped else output,
                                 "execution_result": "success" if success else "failed"}
                current = target
            self.fail("routing adapter did not terminate")

    def test_summary_then_token_reaches_next_agent(self):
        self.assertEqual(self.route_response("coordinate", "## Operation report\nSaved and verified.\n\ndesign\n\n"),
                         "design")

    def test_routing_adapter_failures_cannot_reuse_success(self):
        for failure in ("stale", "tampered", "write_error"):
            with self.subTest(failure=failure):
                self.assertEqual(self.route_response("coordinate", "design", **{failure: True}), "abort")

    def test_routing_adapter_and_report_contract_cannot_be_bypassed(self):
        for mutation in ("command", "source", "gate", "readback"):
            with self.subTest(mutation=mutation):
                flow = deepcopy(self.flow)
                if mutation == "command":
                    helper = next(c for c in flow["components"] if c["name"] == "review_routing_token")
                    helper["inputs"][1]["from"] = "scripts/untrusted.py"
                elif mutation == "source":
                    next(r for r in flow["routers"] if r["from"] == "review")["to"] = "integrate"
                elif mutation == "gate":
                    gate = next(r for r in flow["routers"] if r["from"] == "review_routing_capture")
                    gate["condition"]["routes"]["Action error"] = "review_routing_token"
                else:
                    prompt = flow["prompts"][0]["prompt_template"]
                    prompt["system"] = prompt["system"].replace("Read the saved note back", "Assume the note exists")
                with self.assertRaises(ctx.Invalid):
                    ctx.validate_flow(flow, self.registration)

    def test_repository_contracts(self):
        self.assertEqual(ctx.validate_repository()["flows"], 3)
        catalog_path = Path(".gitlab/ctx/catalog.json")
        catalog = json.loads((ROOT / catalog_path).read_text())
        tokens = {token for flow in [*catalog["flows"].values(), self.registration]
                  for allowed in {**flow["terminal_tokens"], **flow.get("managed_terminal_tokens", {})}.values()
                  for token in allowed}
        self.assertEqual(tokens, routing.TOKENS)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [catalog_path, *(Path(path) for path in catalog["flows"])]
            before = {path: (ROOT / path).read_bytes() for path in paths}
            for path, contents in before.items():
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_bytes(contents)
            ctx.sync_routing(root)
            self.assertEqual({path: (root / path).read_bytes() for path in paths}, before)

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
            if "condition" in route:
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
        review = next(r for r in self.flow["routers"] if r["from"] == "review_routing_token")
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
        for response in ("ready", "Verdict: approved; note saved.\nready \n", '{"routing_token":"ready"}'):
            self.assertEqual(self.route_response("review", response), "integrate")
        for response in ("integrate", "ready\nMore details", "```ready```", "approved", "blocked\nready"):
            self.assertEqual(self.route_response("review", response), "abort")

    def test_tests_precede_implementation(self):
        routes = {r["from"].removesuffix("_routing_token"): r["condition"]["routes"]
                  for r in self.flow["routers"] if r["from"].endswith("_routing_token")}
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
        next(r for r in self.flow["routers"] if r["from"] == "design_routing_token")["condition"]["routes"]["ready"] = "missing"
        with self.assertRaisesRegex(ctx.Invalid, "routing target"):
            ctx.validate_flow(self.flow, self.registration)

    def test_cycles_rejected(self):
        self.flow["routers"][-1]["condition"]["routes"]["ready"] = "design"
        with self.assertRaisesRegex(ctx.Invalid, "cycle"):
            ctx.validate_flow(self.flow, self.registration)

    def test_blocked_cannot_continue(self):
        next(r for r in self.flow["routers"] if r["from"] == "design_routing_token")["condition"]["routes"]["blocked"] = "tests"
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


class RoutingTests(unittest.TestCase):
    def test_normalization_preserves_information_separately(self):
        self.assertEqual(routing.normalize_response("## Report\r\nSaved.\r\n\t design \r\n\r\n", {"design"}),
                         {"routing_token": "design", "informational_output": "## Report\nSaved."})
        structured = '{"routing_token":"ready","informational_output":"Verdict: approved"}'
        self.assertEqual(routing.normalize_response(structured, {"ready"}), json.loads(structured))
        self.assertEqual(routing.normalize_response("Examples:\n```\nblocked\n```\nready", {"ready"})["routing_token"],
                         "ready")

    def test_unknown_ambiguous_and_malformed_signals_rejected(self):
        for response in ("", "ready\nmore details", "unknown", "READY", "ready or blocked", "**ready**",
                         "```\nready\n```", "```\nready", "blocked\nready", "integrate\nready",
                         'routing_token: blocked\nready', '{"routing_token":"ready"}\nblocked',
                         '{"routing_token":"ready","routing_token":"blocked"}',
                         '{"routing_token":"unknown"}', '{"routing_token":["ready"]}',
                         '{"routing_token":"ready","next":"integrate"}',
                         '{"routing_token":"ready","informational_output":false}', "x" * (256 * 1024 + 1)):
            with self.subTest(response=response[:80]):
                with self.assertRaises(routing.RoutingError):
                    routing.normalize_response(response, {"ready", "blocked"})

    def test_cli_structured_result_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "ctx-routing-review.input"
            args = [sys.executable, str(ROOT / "scripts/ctx_routing.py"), "normalize",
                    "--component", "review", "--allowed", "ready,blocked"]
            path.write_text("Saved review.\nready\n")
            result = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout),
                             {"routing_token": "ready", "informational_output": "Saved review."})
            self.assertFalse(path.exists())
            target = root / "user-file"
            target.write_text("ready")
            path.symlink_to(target)
            result = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertEqual(target.read_text(), "ready")


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
        self.context = {"scope": "E2-1", "manifest": "docs/plan/E2/acceptance.json",
                        "manifest_sha256": "d" * 64}
        scope_patch = patch.object(ctx, "resolve_context", return_value=self.context)
        scope_patch.start()
        self.addCleanup(scope_patch.stop)
        (self.root / ".ctx").mkdir()
        self.ac_report = {
            "version": 1, "project_id": "local", "pipeline_id": "local", "source_sha": SHA,
            "scope": "E2-1", "manifest_sha256": "d" * 64, "criteria": []}
        (self.root / ".ctx/acceptance.json").write_text(json.dumps(self.ac_report))

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
        script = ("import os,pathlib; pathlib.Path('.ctx/acceptance.json').write_text(" +
                  repr(json.dumps(self.ac_report)) + "); pathlib.Path(os.environ['CTX_OUTPUT']).write_text(" +
                  repr(json.dumps(evidence("verify"))) + ")")
        code, report = self.run_step([sys.executable, "-c", script])
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "passed")

    def test_wrong_scope_adapter_output_fails_verify_before_acceptance(self):
        script = ("import os,pathlib,json; p=pathlib.Path('.ctx/acceptance.json'); "
                  "p.write_text(" + repr(json.dumps({**self.ac_report, "scope": "E2-2"})) + "); "
                  "pathlib.Path(os.environ['CTX_OUTPUT']).write_text(" + repr(json.dumps(evidence("verify"))) + ")")
        code, report = self.run_step([sys.executable, "-c", script])
        self.assertEqual(code, 2)
        self.assertIn("scope", report["reason"])

    def test_legacy_adapter_receives_only_resolved_scope_not_project_variables(self):
        script = ("import os,pathlib; assert os.environ['CTX_AC_SCOPE']=='E2-1'; "
                  "assert os.environ['CTX_AC_MANIFEST']=='docs/plan/E2/acceptance.json'; "
                  "pathlib.Path('.ctx/acceptance.json').write_text(" + repr(json.dumps(self.ac_report)) + "); "
                  "pathlib.Path(os.environ['CTX_OUTPUT']).write_text(" + repr(json.dumps(evidence("verify"))) + ")")
        # Keep this fixture's identity independent of the enclosing GitLab job.
        with patch.dict(os.environ, {"PATH": os.environ["PATH"], "CTX_AC_SCOPE": "E99-9",
                                     "CTX_AC_MANIFEST": "bad.json"}, clear=True):
            self.config["commands"]["verify"]["argv"] = [sys.executable, "-c", script]
            (self.root / ".gitlab/ctx/commands.yml").write_text(yaml.safe_dump(self.config))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ctx.execute_step("verify", self.root), 0)

    def test_stale_acceptance_output_cannot_be_reused(self):
        script = "import os,pathlib; pathlib.Path(os.environ['CTX_OUTPUT']).write_text(" + repr(json.dumps(evidence("verify"))) + ")"
        code, report = self.run_step([sys.executable, "-c", script])
        self.assertEqual(code, 2)
        self.assertIn("no fresh acceptance", report["reason"])

    def test_proven_maintenance_is_not_an_application_pass(self):
        maintenance = {"mode": "maintenance", "reason": "Verified workflow-only ancestor diff"}
        with patch.object(ctx, "resolve_context", return_value=maintenance):
            code, report = self.run_step()  # No fabricated application adapter needed.
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "not_applicable")
        self.assertNotIn("evidence", report)
        with self.assertRaisesRegex(ctx.Invalid, "not passed"):
            ctx.validate_prior("acceptance", {"verify": report}, IDENTITY)

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
