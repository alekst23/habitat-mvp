"""Design completion is a reviewed result, not a structural CI pass."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("closure", ROOT / "scripts/ctx_design_closure.py")
closure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(closure)
SHA = "a" * 40
NEXT = "b" * 40
BASE = "https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase"


def record():
    return {"version": 1, "mode": "design-closure", "project_id": 87329027,
            "source_issue_iid": 10, "epic": "E2", "branch": "ctx/epic-i2",
            "candidate_sha": SHA, "structural_sha": SHA, "handoff_sha": SHA,
            "review": {"sha": SHA, "report_url": BASE + "/-/issues/10#note_123",
                       "reviewer": "epic_review/session-42", "verdict": "ready", "findings": []},
            "repairs": [], "research_attempts": [], "active": None}


def finding(kind="technical"):
    result = {"id": "DR1", "kind": kind, "summary": "Contract is missing",
              "tickets": ["E2-2"], "owner": "design", "action": "Define typed contract"}
    if kind == "research":
        result.update({"question": "Which scopes are required?", "source_urls": ["https://developers.reddit.com/docs/"],
                       "deliverable": "docs/design/connectors/research.md", "fallback": "Connector disabled"})
    if kind == "enablement":
        result["safeguard"] = "Live connector disabled; fixture-only work allowed"
    return result


class DesignClosureTests(unittest.TestCase):
    def test_failed_reservation_is_reconciled_without_freeing_its_repair_budget(self):
        data = record()
        data["active"] = {"kind": "repair", "base_sha": SHA, "finding_ids": ["DR1"], "session_id": 9282723}
        observation = {"session_id": 9282723, "project_id": 87329027, "status": "failed", "observed_head": SHA}
        self.assertTrue(callable(getattr(closure, "reconcile_interrupted", None)), "terminal reservation recovery missing")
        with self.assertRaises(ValueError):
            closure.reconcile_interrupted(data, observation | {"status": "running"}, BASE + "/-/issues/10#note_200")
        with self.assertRaises(ValueError):
            closure.reconcile_interrupted(data, observation | {"session_id": 1}, BASE + "/-/issues/10#note_200")
        restored = closure.reconcile_interrupted(data, observation, BASE + "/-/issues/10#note_200")
        self.assertIsNone(restored["active"])
        self.assertEqual(len(restored["repairs"]), 1)
        self.assertEqual(restored["repairs"][0]["outcome"], "interrupted")
        self.assertEqual(restored["repairs"][0]["base_sha"], restored["repairs"][0]["result_sha"])
        self.assertEqual(closure.assess(restored, SHA)["action"], "validate")
        self.assertIsNotNone(data["active"])
        partial = closure.reconcile_interrupted(data, observation | {"observed_head": NEXT}, BASE + "/-/issues/10#note_201")
        self.assertEqual(partial["candidate_sha"], NEXT)
        self.assertEqual(partial["review"], data["review"])
        partial["structural_sha"] = NEXT
        self.assertEqual(closure.assess(partial, NEXT)["action"], "review", "new SHA must not reuse old review")
        partial["repairs"] = []
        with self.assertRaisesRegex(ValueError, "budget"):
            closure.assess(partial, NEXT)

    def test_saved_or_structurally_valid_is_not_complete(self):
        data = record()
        data["review"] = None
        result = closure.assess(data, SHA)
        self.assertEqual(result["action"], "review")
        self.assertFalse(result["design_complete"])
        data["review"] = record()["review"]
        data["candidate_sha"] = NEXT
        self.assertEqual(closure.assess(data, NEXT)["action"], "validate")
        data["structural_sha"] = NEXT
        self.assertEqual(closure.assess(data, NEXT)["action"], "review")

    def test_repair_precedes_human_question_and_re_review_is_required(self):
        data = record()
        data["review"].update(verdict="blocked", findings=[finding("decision"), {**finding(), "id": "DR2"}])
        result = closure.assess(data, SHA)
        self.assertEqual(result["action"], "repair")
        self.assertEqual(result["finding_ids"], ["DR2"])
        self.assertFalse(result["implementation_authorized"])
        data["active"] = {"kind": "repair", "base_sha": SHA, "finding_ids": ["DR2"]}
        self.assertEqual(closure.assess(data, SHA)["action"], "reconcile_active")

    def test_repair_budget_survives_new_sha_and_resume(self):
        data = record()
        data["review"].update(verdict="blocked", findings=[finding()])
        data["repairs"] = [{"base_sha": "c" * 40, "result_sha": "d" * 40,
                            "report_url": BASE + "/-/issues/10#note_123"}] * 3
        self.assertEqual(closure.assess(data, SHA)["action"], "checkpoint")

    def test_research_needs_actionable_task_and_does_not_repeat_forever(self):
        data = record()
        data["review"].update(verdict="blocked", findings=[finding("research")])
        self.assertEqual(closure.assess(data, SHA)["action"], "research")
        data["research_attempts"] = ["DR1", "DR1"]
        self.assertEqual(closure.assess(data, SHA)["action"], "request_access")
        del data["review"]["findings"][0]["question"]
        with self.assertRaisesRegex(ValueError, "research"):
            closure.assess(data, SHA)

    def test_enablement_is_separate_but_unknown_behavior_is_not(self):
        data = record()
        data["review"]["findings"] = [finding("enablement")]
        result = closure.assess(data, SHA)
        self.assertTrue(result["design_complete"])
        self.assertFalse(result["implementation_authorized"])
        self.assertEqual(result["enablement_gates"], ["DR1"])
        data["review"].update(verdict="blocked", findings=[finding("decision")])
        self.assertEqual(closure.assess(data, SHA)["action"], "request_decision")

    def test_review_without_final_handoff_check_is_not_complete(self):
        data = record()
        data["handoff_sha"] = None
        self.assertEqual(closure.assess(data, SHA)["action"], "validate_handoff")
        data["handoff_sha"] = NEXT
        self.assertFalse(closure.assess(data, SHA)["design_complete"])

    def test_unknown_ambiguous_stale_or_cross_project_records_fail_closed(self):
        for mutation in ("mode", "epic", "verdict", "duplicate", "cross_project", "stale", "missing_safeguard"):
            with self.subTest(mutation=mutation):
                data = deepcopy(record())
                if mutation == "mode": data["mode"] = "implementation"
                if mutation == "epic": data["epic"] = "E10"
                if mutation == "verdict": data["review"]["verdict"] = "approved-ish"
                if mutation == "duplicate": data["review"].update(verdict="blocked", findings=[finding(), finding()])
                if mutation == "cross_project": data["review"]["report_url"] = "https://example.com/note"
                if mutation == "stale": data["candidate_sha"] = NEXT
                if mutation == "missing_safeguard": data["review"]["findings"] = [finding("enablement")]; del data["review"]["findings"][0]["safeguard"]
                with self.assertRaises(ValueError): closure.assess(data, SHA)


if __name__ == "__main__":
    unittest.main()
