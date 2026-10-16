"""Native session admission and journal simulation, not live Duo acceptance."""
import hashlib
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
from test_ctx_development import receipt


class NativeAdmissionTests(unittest.TestCase):
    def test_interrupted_review_guidance_keeps_complete_verdict_and_bounded_reads(self):
        review = (ROOT / "skills/ctx-ticket-review/SKILL.md").read_text()
        for text in ("exact candidate SHA", "once per path", "one corrected request",
                     "save_by", "Partial notes are progress evidence, never approval",
                     "complete independent review", "Terminal tokens: [ready, blocked]"):
            self.assertIn(text, review)
        guide = (ROOT / "docs/development/single-shot-development.md").read_text()
        for text in ("resume-interrupted", "ONE recovery per", "transition consumes one",
                     "source-security",
                     "not the unchanged `ctx/ticket-i13`", "stream_lost"):
            self.assertIn(text, guide)

    def test_owner_continues_unrelated_work_before_questions_and_reconciles_retry(self):
        run = dev.claim(dev.new_run(repair_request()), "E2-1")
        run = dev.record(run, receipt(run, response="blocked", blocker_kind="decision",
            reason="Signup eligibility", decisions=[{"id": "Q6", "question": "Who may sign up?"}]))
        self.assertEqual(dev.next_actions(run)["owner_action"]["target"], "E2-2")
        run = dev.claim(run, "E2-2")
        run = dev.record(run, receipt(run, response="blocked", blocker_kind="transient", reason="Runner interrupted"))
        self.assertEqual(dev.next_actions(run)["owner_action"]["action"], "reconcile_retry")
        run = dev.retry(run, "E2-2", "https://gitlab.com/group/showcase/-/issues/10#note_200")
        run = dev.claim(run, "E2-2")
        run = dev.record(run, receipt(run, response="blocked", blocker_kind="transient", reason="Still unavailable"))
        self.assertEqual(dev.next_actions(run)["owner_action"]["questions"],
                         [{"target": "E2-1", "id": "Q6", "question": "Who may sign up?"}])
        dev.verify_journal(run)

    def test_owner_selects_recovery_and_repairs_without_a_human_dispatch_plan(self):
        run = dev.new_run(repair_request())
        self.assertEqual(dev.next_actions(run).get("owner_action"),
                         {"action": "delegate", "target": "E2-1", "phase": "design", "component": "design"})
        run = dev.claim(run, "E2-1")
        self.assertEqual(dev.next_actions(run)["owner_action"]["action"], "reconcile_active")
        for _ in range(3):
            run = dev.record(run, success(run))
            run = dev.claim(run, "E2-1")
        run = dev.record(run, defect(run))
        self.assertEqual(dev.next_actions(run)["owner_action"], {"action": "repair", "target": "E2-1"})
        run = dev.repair(run, "E2-1")
        self.assertEqual(dev.next_actions(run)["owner_action"]["phase"], "implementation")

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
                     "Native sessions do not auto-restart", "scripts/ctx_owner.py resume/next",
                     "ctx-owner-handoff:v1", "next.owner_action", "NEXT AGENT RUN",
                     "CTX_OWNER_HANDOFF_V1_BEGIN", "CTX_OWNER_HANDOFF_V1_END",
                     "--legacy-note-id", "never HTML comments", "ctx_checkpoint.py",
                     "NEVER model-retyped JSON", "exact body/payload equality",
                     "no POST retry/model transcription", "without deletion"):
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
        self.assertEqual(catalog["catalog_version"], "1.12.0")
        self.assertNotIn("candidate_catalog_version", catalog)
        self.assertNotIn("candidate_status", catalog)
        self.assertIn("live two-run acceptance pending", catalog["publication_status"])
        self.assertEqual(catalog["definition_sha256"], catalog["published_definition_sha256"])
        self.assertEqual(catalog["published_definition_sha256"],
                         "3442cb93da7b416a1d4b11fdd2c75bfee65cca2b752fa287d8c654475bd6d34e")
        self.assertEqual(catalog["catalog_saved_definition_sha256"],
                         "349ba308ffbe9cb80a89fc6ffd6b6ee63e7490340025bd0ae926a2c1e1da85b3")
        self.assertEqual(catalog["catalog_saved_definition_sha256"],
                         hashlib.sha256(flow_path.read_bytes().removesuffix(b"\n")).hexdigest())
        self.assertEqual(catalog["definition_sha256"], hashlib.sha256(flow_path.read_bytes()).hexdigest())
        self.assertLessEqual(len(flow_path.read_bytes()), 40960)
        self.assertIn("resume-interrupted", flow_path.read_text())
        self.assertEqual(catalog["published_source_commit"], "c7b38df4ff28d22db539feb1670c267952369b1a")
        self.assertTrue(catalog["source_merge_request"].endswith("/merge_requests/64"))
        self.assertEqual(catalog["publication_history"][-1]["catalog_version"], "1.11.0")
        self.assertEqual(catalog["publication_history"][-1]["published_definition_sha256"],
                         "edd61f87b3de0732683b7a47db4e16d77455d25a3d96449a252c9523145f4899")
        self.assertEqual(catalog["publication_history"][-2]["catalog_version"], "1.10.0")
        self.assertIn("pipeline 2956291204 finished FAILED overall", catalog["publication_history"][-1]["verification"])
        self.assertIn("source-security remains unconfigured and unwaived", catalog["verification"])
        self.assertNotIn("final-candidate CI remains pending", catalog["verification"])
        controller = json.loads((ROOT / ".gitlab/ctx/controller.json").read_text())
        self.assertFalse(controller["enabled"])


if __name__ == "__main__":
    unittest.main()
