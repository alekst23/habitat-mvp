"""Native session admission and journal simulation, not live Duo acceptance."""
import json
import subprocess
import sys
import time
import unittest
from test_ctx_development import ROOT
from ctx_execution_budget import admission
import ctx_development as dev
import ctx_workflow as workflow
from test_ctx_development_repairs import repair_request, success, defect


class NativeAdmissionTests(unittest.TestCase):
    def test_native_run_can_continue_past_the_old_one_slice_window(self):
        self.assertTrue(admission(100, 100 + 601)["delegate"])

    def test_time_and_count_bounds_keep_headroom_in_both_modes(self):
        for mode, cutoff, limit, deadline in (("native", 2400, 64, 3000),
                                               ("controller", 600, 1, 1800)):
            with self.subTest(mode=mode):
                result = admission(100, 100 + cutoff - 1, mode=mode, delegations=limit - 1)
                self.assertTrue(result["delegate"])
                self.assertEqual(result["save_by"], 100 + deadline)
                self.assertFalse(admission(100, 100 + cutoff, mode=mode)["delegate"])
                self.assertFalse(admission(100, 101, mode=mode, delegations=limit)["delegate"])
        self.assertEqual(admission(100, 200)["save_by"], 1100)

    def test_invalid_budget_and_cli_fail_closed(self):
        for start, now, kwargs in (
            (100, 99, {}), (-1, 100, {}), (True, 100, {}), (100, float("nan"), {}),
            (float("inf"), 100, {}), (100, 101, {"mode": "unlimited"}),
            (100, 101, {"delegations": -1}), (100, 101, {"delegations": True}),
            (100, 101, {"delegations": 0.5}),
        ):
            with self.subTest(start=start, now=now, kwargs=kwargs), self.assertRaises(ValueError):
                admission(start, now, **kwargs)
        script = str(ROOT / "scripts/ctx_execution_budget.py")
        for args, code in (([], 0), (["--mode", "native"], 2), (["--delegations", "0"], 2),
                           (["--mode", "native", "--delegations", "0"], 0),
                           (["--mode", "native", "--delegations", "64"], 2),
                           (["--mode", "controller", "--delegations", "1"], 2)):
            result = subprocess.run([sys.executable, script, "--started-at", str(int(time.time())), *args],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, code, result.stderr)
            self.assertEqual(json.loads(result.stdout)["delegate"], code == 0)
            if not args:
                self.assertEqual(json.loads(result.stdout)["mode"], "controller")

    def test_native_loop_keeps_full_journal_through_fix_and_subsequent_tickets(self):
        original = repair_request()
        run = dev.new_run(original)
        failed = False
        repaired = False
        delegated = []
        # Fast synthetic workers; not a claim that real workers fit this time budget.
        while not dev.next_actions(run)["complete"]:
            count = len(delegated)
            self.assertTrue(admission(100, 100 + count * 30, delegations=count)["delegate"])
            frontier = dev.next_actions(run)
            if frontier["repairable"]:
                run = dev.repair(run, frontier["repairable"][0])
                frontier = dev.next_actions(run)
            self.assertTrue(frontier["ready"], frontier)
            target = frontier["ready"][0]["target"]
            run = dev.claim(run, target)
            phase = run["active"]["phase"]
            delegated.append((target, phase))
            if target == "E2-1" and phase == "verify" and not failed:
                result = defect(run)
                failed = True
            else:
                result = success(run)
                if target == "E2-1" and phase == "implementation" and failed and not repaired:
                    result.update(candidate_sha="d" * 40, resolved_findings=["regression-1"])
                    repaired = True
            run = dev.record(run, result)
            # Simulate complete source-state readback between steps, not a new run.
            run = json.loads(json.dumps(run))
            dev.verify_journal(run)
            self.assertEqual(run["request"], original)
        self.assertTrue(repaired)
        self.assertEqual(run["nodes"]["E2-1"]["repairs"], 1)
        self.assertEqual([p for t, p in delegated if t == "E2-1"][-4:],
                         ["implementation", "verify", "review", "integrate"])
        self.assertEqual([p for t, p in delegated if t == "E2"],
                         ["docs", "verify", "epic_review", "close"])
        self.assertEqual({t for t, _ in delegated}, {"E2-1", "E2-2", "E2-3", "E2"})
        self.assertEqual(run["actions"], len(delegated))
        # A new session budget cannot refresh an exhausted cumulative journal budget.
        capped = dev.new_run(original)
        capped["actions"] = dev.MAX_ACTIONS
        self.assertTrue(admission(10000, 10001, delegations=0)["delegate"])
        self.assertTrue(dev.next_actions(capped)["checkpoint"])
        with self.assertRaises(ValueError):
            dev.claim(capped, "E2-1")

    def test_native_contract_and_publication_metadata_do_not_require_controller_setup(self):
        flow_path = ROOT / ".gitlab/duo/flows/ctx-development.yml"
        flow = workflow.read_yaml(flow_path)
        prompt = flow["prompts"][0]["prompt_template"]["system"]
        for term in ("No controller installation is required", "Before EVERY",
                     "--delegations RESERVED_COUNT", "integrate.more means continue here",
                     "Native sessions do not auto-restart"):
            self.assertIn(term, prompt)
        worker = next(p for p in flow["prompts"] if p["prompt_id"] == "design_prompt")["prompt_template"]["system"]
        self.assertIn("For mode=technical-addendum or mode=decision-application", worker)
        self.assertIn("do NOT execute the stub-preparation instructions below", worker)
        for name in ("ctx-project", "ctx-design"):
            prompt = (ROOT / f".gitlab/duo/agents/{name}.md").read_text().lower()
            self.assertIn("no controller installation", prompt)
            self.assertIn("human", prompt)
        catalog = json.loads((ROOT / ".gitlab/ctx/catalog.json").read_text())["flows"][
            ".gitlab/duo/flows/ctx-development.yml"]
        self.assertNotIn("pending_catalog_version", catalog)
        self.assertEqual(catalog["catalog_version"], "1.7.0")
        self.assertEqual(catalog["definition_sha256"], catalog["published_definition_sha256"])
        self.assertEqual(catalog["publication_history"][-1]["catalog_version"], "1.6.0")
        controller = json.loads((ROOT / ".gitlab/ctx/controller.json").read_text())
        self.assertFalse(controller["enabled"])


if __name__ == "__main__":
    unittest.main()
