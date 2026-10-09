"""Single-shot orchestration checks; not proof of live Duo execution or parallelism."""

import json
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ctx_workflow as ctx
import ctx_development as dev

SHA = "a" * 40
PROJECT = "https://gitlab.com/group/showcase"


def request():
    state = {"version": 2, "project_id": "87329027", "epic": "E2", "epic_issue_iid": 2,
             "source_issue_iid": 10, "next_ticket_number": 4, "tickets": [
                 {"id": "E2-1", "issue_iid": 3, "depends_on": [], "status": "pending"},
                 {"id": "E2-2", "issue_iid": 4, "depends_on": [], "status": "pending"},
                 {"id": "E2-3", "issue_iid": 5, "depends_on": ["E2-1", "E2-2"], "status": "pending"}]}
    return {"version": 1, "project_id": "87329027", "project_path": "group/showcase",
            "source_issue_iid": 10, "run_id": "session-123", "session_url": PROJECT + "/-/automate/agent-sessions/123",
            "epics": [{"state": state, "branch": "ctx/epic-i2", "base_sha": SHA, "design_sha": "b" * 40}]}


def receipt(run, **overrides):
    active = run["active"]
    value = {**active, "response": "ready", "report_url": PROJECT + f"/-/issues/10#note_{run['actions']}",
             "report_readback": True}
    if active["phase"] == "integrate":
        value.update(response="more", integration={
            "source_sha": active["candidate_sha"], "epic_sha": "c" * 40,
            "pipeline_url": PROJECT + "/-/pipelines/99",
            "review_url": run["nodes"][active["target"]]["review_url"]})
    value.update(overrides)
    return value


def finish_target(run, target):
    while run["nodes"][target]["status"] != "done":
        run = dev.claim(run, target)
        run = dev.record(run, receipt(run))
    return run


class SupervisorFlowTests(unittest.TestCase):
    def test_catalog_rejects_unsupported_logging_events(self):
        flow = ctx.read_yaml(ROOT / ".gitlab/duo/flows/ctx-development.yml")
        registration = json.loads((ROOT / ".gitlab/ctx/catalog.json").read_text())["flows"][".gitlab/duo/flows/ctx-development.yml"]
        for events in (["on_delegation_error"], "on_agent_final_answer", ["on_delegation", "on_delegation"], [{}]):
            changed = deepcopy(flow)
            changed["components"][0]["ui_log_events"] = events
            with self.subTest(events=events), self.assertRaisesRegex(ctx.Invalid, "log events"):
                ctx.validate_flow(changed, registration)

    def test_development_is_a_bounded_supervisor_not_a_single_ticket_chain(self):
        self.assertLessEqual((ROOT / ".gitlab/duo/flows/ctx-development.yml").stat().st_size, ctx.MAX_FLOW_BYTES)
        flow = ctx.read_yaml(ROOT / ".gitlab/duo/flows/ctx-development.yml")
        owner = next(c for c in flow["components"] if c["name"] == "coordinate")
        self.assertTrue(owner.get("subagents"), "development still stops after one ticket")
        self.assertEqual(owner.get("max_delegations"), 64)
        prompt = next(p for p in flow["prompts"] if p["prompt_id"] == owner["prompt_id"])
        self.assertIn("delegate_task", prompt["prompt_template"]["system"])
        self.assertIn("final_response_tool", prompt["prompt_template"]["system"])
        self.assertIn("scripts/ctx_development.py", prompt["prompt_template"]["system"])

    def test_native_registration_and_guardrails(self):
        flow = ctx.read_yaml(ROOT / ".gitlab/duo/flows/ctx-development.yml")
        registration = json.loads((ROOT / ".gitlab/ctx/catalog.json").read_text())["flows"][".gitlab/duo/flows/ctx-development.yml"]
        ctx.validate_flow(flow, registration)
        for mutation in ("unbounded", "unknown_child", "duplicate_child", "review_writes", "child_router", "token_drift"):
            with self.subTest(mutation=mutation), self.assertRaises(ctx.Invalid):
                changed = deepcopy(flow)
                owner = changed["components"][0]
                if mutation == "unbounded":
                    owner["max_delegations"] = 10000
                elif mutation == "unknown_child":
                    owner["subagents"][0]["name"] = "unknown"
                elif mutation == "duplicate_child":
                    owner["subagents"].append(owner["subagents"][0])
                elif mutation == "review_writes":
                    next(c for c in changed["components"] if c["name"] == "review")["toolset"].append("run_command")
                elif mutation == "child_router":
                    changed["routers"].append({"from": "review", "to": "end"})
                else:
                    p = next(p for p in changed["prompts"] if p["prompt_id"] == "review_prompt")
                    p["prompt_template"]["system"] = p["prompt_template"]["system"].replace("[ready, blocked]", "[integrate, blocked]")
                ctx.validate_flow(changed, registration)

    def test_supervisor_final_adapter_normalizes_without_confusing_checkpoint_and_completion(self):
        from test_ctx_workflow import FlowTests
        probe = FlowTests("test_summary_then_token_reaches_next_agent")
        probe.flow = ctx.read_yaml(ROOT / ".gitlab/duo/flows/ctx-development.yml")
        self.assertEqual(probe.route_response("coordinate", "Saved report.\ncomplete\n"), "end")
        self.assertEqual(probe.route_response("coordinate", "checkpoint"), "end")
        self.assertEqual(probe.route_response("coordinate", "Saved detailed note.\ncheckpoint\n", wrapped=True), "end")
        for failure in ("stale", "tampered", "write_error"):
            self.assertEqual(probe.route_response("coordinate", "checkpoint", wrapped=True, **{failure: True}), "abort")
        for response in ("blocked", "ready", "checkpoint\ncomplete", "unknown"):
            self.assertEqual(probe.route_response("coordinate", response), "abort")


class ProgressTests(unittest.TestCase):
    def test_all_tickets_and_whole_epic_close_in_one_journal(self):
        run = dev.new_run(request())
        self.assertEqual([r["target"] for r in dev.next_actions(run)["ready"]], ["E2-1", "E2-2"])
        with self.assertRaises(ctx.Invalid):
            dev.claim(run, "E2-3")
        for target in ("E2-1", "E2-2", "E2-3"):
            run = finish_target(run, target)
            self.assertFalse(dev.next_actions(run)["complete"])
        self.assertEqual(dev.next_actions(run)["ready"], [{"target": "E2", "phase": "docs"}])
        run = finish_target(run, "E2")
        self.assertTrue(dev.next_actions(run)["complete"])
        self.assertEqual(run["actions"], 21)
        dev.verify_journal(run)
        self.assertEqual([r["phase"] for r in run["events"][-3:]], ["docs", "epic_review", "close"])

    def test_blocker_does_not_abort_independent_work_or_unlock_dependents(self):
        run = dev.claim(dev.new_run(request()), "E2-1")
        run = dev.record(run, receipt(run, response="blocked", reason="missing intent", blocker_kind="decision"))
        run = finish_target(run, "E2-2")
        state = dev.next_actions(run)
        self.assertFalse(state["complete"])
        self.assertTrue(state["checkpoint"])
        self.assertEqual(state["waiting"]["E2-3"], ["E2-1"])
        with self.assertRaises(ctx.Invalid):
            dev.retry(run, "E2-1", PROJECT + "/-/issues/10#note_22")

    def test_receipt_identity_readback_unknown_tokens_and_replay_fail_closed(self):
        run = dev.claim(dev.new_run(request()), "E2-1")
        for override in ({"target": "E2-2"}, {"attempt": 99}, {"run_id": "another"},
                         {"phase": "integrate"}, {"report_readback": False},
                         {"report_url": PROJECT + "/-/issues/2#note_1"},
                         {"response": "ready\nblocked"}, {"response": "integrate"}):
            with self.subTest(override=override), self.assertRaises((ctx.Invalid, dev.RoutingError)):
                dev.record(run, receipt(run, **override))
        saved = receipt(run, response="Report saved.\nready\n")
        advanced = dev.record(run, saved)
        self.assertEqual(dev.next_actions(advanced)["ready"][0]["phase"], "tests")
        with self.assertRaises(ctx.Invalid):
            dev.record(advanced, saved)

    def test_candidate_sha_is_pinned_for_independent_review_and_integration(self):
        run = dev.new_run(request())
        for _ in range(4):
            run = dev.claim(run, "E2-1")
            run = dev.record(run, receipt(run))
        run = dev.claim(run, "E2-1")
        self.assertEqual(run["active"]["phase"], "review")
        with self.assertRaises(ctx.Invalid):
            dev.record(run, receipt(run, candidate_sha="d" * 40))
        run = dev.record(run, receipt(run))
        run = dev.claim(run, "E2-1")
        wrong = receipt(run)
        wrong["integration"]["review_url"] = PROJECT + "/-/issues/10#note_999"
        with self.assertRaises(ctx.Invalid):
            dev.record(run, wrong)
        self.assertFalse(dev.next_actions(run)["complete"])

    def test_bounded_retry_budget_and_active_claim_survive_resume(self):
        run = dev.claim(dev.new_run(request()), "E2-1")
        restored = json.loads(json.dumps(run))
        dev.verify_journal(restored)
        self.assertEqual(dev.next_actions(restored)["active"], run["active"])
        with self.assertRaises(ctx.Invalid):
            dev.claim(restored, "E2-2")
        run = dev.record(run, receipt(run, response="blocked", reason="waiting", blocker_kind="ci_pending"))
        run = dev.retry(run, "E2-1", PROJECT + "/-/pipelines/55")
        run = dev.claim(run, "E2-1")
        run = dev.record(run, receipt(run, response="blocked", reason="still waiting", blocker_kind="ci_pending"))
        with self.assertRaises(ctx.Invalid):
            dev.retry(run, "E2-1", PROJECT + "/-/pipelines/56")
        run["actions"] = dev.MAX_ACTIONS
        self.assertTrue(dev.next_actions(run)["checkpoint"])
        with self.assertRaises(ctx.Invalid):
            dev.claim(run, "E2-2")

    def test_explicit_ticket_scope_does_not_expand_or_close_epic(self):
        value = request()
        value["epics"][0]["ticket_ids"] = ["E2-2"]
        run = dev.new_run(value)
        self.assertEqual(dev.next_actions(run)["ready"], [{"target": "E2-2", "phase": "design"}])
        self.assertNotIn("E2", run["nodes"])
        run = finish_target(run, "E2-2")
        self.assertTrue(dev.next_actions(run)["complete"])
        run["request"]["epics"][0]["ticket_ids"].append("E2-1")
        with self.assertRaises(ctx.Invalid):
            dev.next_actions(run)

    def test_project_scope_and_in_flight_work(self):
        value = request()
        second = deepcopy(value["epics"][0])
        second["state"].update(epic="E20", epic_issue_iid=20, next_ticket_number=2,
                               tickets=[{"id": "E20-1", "issue_iid": 21, "depends_on": [], "status": "pending"}])
        second["branch"] = "ctx/epic-i20"
        value["epics"].append(second)
        value["epics"][0]["state"]["tickets"][0].update(status="running", session_url=PROJECT + "/-/automate/agent-sessions/99")
        run = dev.new_run(value)
        self.assertEqual([x["target"] for x in dev.next_actions(run)["ready"]], ["E2-2", "E20-1"])
        with self.assertRaises(ctx.Invalid):
            dev.claim(run, "E2-1")
        second["state"]["project_id"] = "123"
        with self.assertRaises(ctx.Invalid):
            dev.new_run(value)

    def test_cli_atomic_journal_refuses_reset_and_path_escape(self):
        script = str(ROOT / "scripts/ctx_development.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "request.json").write_text(json.dumps(request()))
            def call(*args):
                return subprocess.run([sys.executable, script, *args], cwd=root,
                                      capture_output=True, text=True, timeout=10)
            journal = ".ctx/development/run.json"
            self.assertEqual(call("init", journal, "request.json").returncode, 0)
            before = (root / journal).read_bytes()
            self.assertEqual(call("init", journal, "request.json").returncode, 2)
            self.assertEqual((root / journal).read_bytes(), before)
            self.assertEqual(call("init", ".ctx/development/../../escape.json", "request.json").returncode, 2)
            (root / ".ctx/development/link.json").symlink_to(root / journal)
            self.assertEqual(call("claim", ".ctx/development/link.json", "E2-1").returncode, 2)
            children = [subprocess.Popen([sys.executable, script, "claim", journal, target],
                                         cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        for target in ("E2-1", "E2-2")]
            for child in children:
                child.communicate(timeout=10)
            self.assertEqual(sorted(child.returncode for child in children), [0, 2])
            self.assertEqual(json.loads((root / journal).read_text())["actions"], 1)
            tampered = json.loads((root / journal).read_text())
            tampered["nodes"]["E2-3"]["status"] = "done"
            (root / journal).write_text(json.dumps(tampered))
            self.assertEqual(call("next", journal).returncode, 2)


if __name__ == "__main__":
    unittest.main()
