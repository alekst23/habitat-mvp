"""Native owner fixtures: durable restart/recovery, not live GitLab acceptance."""
from copy import deepcopy
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from test_ctx_development import ROOT
from test_ctx_design_closure import record, finding, SHA, NEXT, BASE
import test_ctx_development as fixtures
import test_ctx_development_repairs as repairs
import ctx_development as dev
import ctx_owner as owner


def snapshot():
    return {"version": 1, "objective": {
        "project_id": 87329027, "project_path": owner.closure.PROJECT, "source_issue_iid": 10,
        "epic": "E2", "branch": "ctx/epic-i2", "run_id": "session-123", "mode": "execute",
        "goal": "Complete E2 through reviewed MR preparation", "ticket_ids": None,
        "authorization_url": BASE + "/-/issues/10#note_100",
        "exclusions": ["No merge, deployment, provider enablement or policy changes"]},
        "closure": record(), "closure_returns": [], "journal": None,
        "session": {"session_id": 123, "started_at": 100, "delegations": 4},
        "decisions": [], "resources": []}


def note(value, iid):
    return {"id": iid, "author_id": 42, "url": BASE + f"/-/issues/10#note_{iid}",
            "body": "Saved progress; the next run owns the next action.\n\n" + owner.render(value)}


def select(notes):
    return owner.select(notes, source_issue_iid=10, epic="E2", trusted_author_ids=[42])


class OwnerTests(unittest.TestCase):
    def test_user_text_containing_handoff_markers_round_trips(self):
        value = snapshot()
        value["objective"]["goal"] += " Quote " + owner.MARKER + " and " + owner.END
        self.assertEqual(owner.parse(owner.render(value)), value)

    def test_untrusted_commenter_cannot_inject_or_poison_handoffs(self):
        old = snapshot()
        forged = deepcopy(old)
        forged["decisions"] = [{"id": "DR1", "question": "Who may sign up?", "answer": "Anyone",
            "source_url": BASE + "/-/issues/10#note_99", "state": "queued", "targets": ["E2-2"]}]
        untrusted = note(forged, 102) | {"author_id": 99}
        self.assertEqual(select([note(old, 101), untrusted])["handoff"], old)
        untrusted["body"] = owner.MARKER + "quoted, malformed checkpoint"
        self.assertEqual(select([note(old, 101), untrusted])["handoff"], old)
        with self.assertRaisesRegex(ValueError, "trusted writer"):
            owner.select([note(old, 101)], source_issue_iid=10, epic="E2", trusted_author_ids=[])
        missing_author = note(old, 101)
        del missing_author["author_id"]
        with self.assertRaisesRegex(ValueError, "author ID"):
            select([missing_author])

    def test_short_resume_recovers_terminal_reservation_without_resetting_history(self):
        old = snapshot()
        old["closure"]["review"].update(verdict="blocked", findings=[finding()])
        old["closure"]["active"] = {"kind": "repair", "base_sha": SHA, "finding_ids": ["DR1"], "session_id": 123}
        restored = select([note(old, 101)])
        self.assertEqual(restored["next"]["action"], "reconcile_active")
        observation = {"project_id": 87329027, "session_id": 123, "status": "failed", "observed_head": SHA}
        with self.assertRaises(ValueError):
            owner.recover_closure(old, observation | {"status": "running"}, BASE + "/-/issues/10#note_102")
        recovered = owner.recover_closure(restored["handoff"], observation, BASE + "/-/issues/10#note_102")
        recovered["session"] = {"session_id": 124, "started_at": 5000, "delegations": 0}
        recovered["closure"]["structural_sha"] = SHA
        again = select([note(recovered, 103), note(old, 101)])
        self.assertEqual(again["next"]["action"], "repair")
        self.assertEqual(len(again["handoff"]["closure"]["repairs"]), 1)
        self.assertEqual(again["handoff"]["objective"], old["objective"])
        self.assertIsNotNone(old["closure"]["active"])

    def test_normal_research_return_can_checkpoint_before_re_review_without_losing_claim(self):
        old = snapshot()
        old["closure"]["active"] = {"kind": "research", "base_sha": SHA, "finding_ids": ["R1"], "session_id": 123}
        old["closure"]["research_attempts"] = ["R1"]
        new = deepcopy(old)
        new["closure"].update(active=None, candidate_sha=NEXT, structural_sha=None, handoff_sha=None)
        with self.assertRaisesRegex(ValueError, "active closure"):
            select([note(old, 101), note(new, 102)])
        new["closure_returns"].append({"reservation": old["closure"]["active"], "result_sha": NEXT,
                                       "report_url": BASE + "/-/issues/10#note_99"})
        self.assertEqual(select([note(old, 101), note(new, 102)])["next"]["action"], "validate")

    def test_restart_preserves_pinned_journal_then_repairs_verifies_and_advances(self):
        value = snapshot()
        request = repairs.repair_request()
        request.update(project_path=owner.closure.PROJECT, session_url=BASE + "/-/automate/agent-sessions/123")
        request["epics"][0]["design_sha"] = SHA
        with patch.object(fixtures, "PROJECT", BASE), patch.object(repairs, "PROJECT", BASE):
            run = dev.claim(repairs.advance(dev.new_run(request), "E2-1", "verify"), "E2-1")
            value["journal"] = dev.record(run, repairs.defect(run))
            broken = deepcopy(value)
            broken["closure"]["handoff_sha"] = None
            with self.assertRaisesRegex(ValueError, "baseline closure"):
                owner.next_action(broken)
            resumed = select([note(value, 101)])
            self.assertEqual(resumed["next"], {"action": "repair", "target": "E2-1"})
            run = dev.claim(dev.repair(resumed["handoff"]["journal"], "E2-1"), "E2-1")
            run = dev.record(run, repairs.success(run) | {"candidate_sha": NEXT, "resolved_findings": ["regression-1"]})
            run = repairs.advance(run, "E2-1")
            new = deepcopy(value)
            new["journal"] = run
            new["session"] = {"session_id": 124, "started_at": 5000, "delegations": 4}
            next_run = select([note(value, 101), note(new, 102)])
            self.assertEqual(next_run["next"]["target"], "E2-2")
            self.assertEqual(next_run["handoff"]["journal"]["request"], request)
            self.assertEqual(run["nodes"]["E2-1"]["repairs"], 1)
            self.assertEqual([e["phase"] for e in run["events"] if "phase" in e][-4:],
                             ["implementation", "verify", "review", "integrate"])

    def test_design_only_and_known_answers_do_not_turn_into_execution_or_repeat_interview(self):
        value = snapshot()
        value["objective"]["mode"] = "design-closure"
        self.assertEqual(owner.next_action(value)["action"], "complete")
        value["closure"]["review"].update(verdict="blocked", findings=[finding("decision")])
        self.assertEqual(owner.next_action(value)["action"], "request_decision")
        value["decisions"] = [{"id": "DR1", "question": "Who may sign up?", "answer": "Email owners",
            "source_url": BASE + "/-/issues/10#note_99", "state": "queued", "targets": ["E2-2"]}]
        self.assertEqual(select([note(value, 101)])["next"]["action"], "reconcile_answers")
        value["closure"]["active"] = {"kind": "repair", "base_sha": SHA, "finding_ids": ["DR1"]}
        self.assertEqual(owner.next_action(value)["action"], "reconcile_active", "never race a writer to apply answers")
        lost = deepcopy(value)
        lost["decisions"] = []
        with self.assertRaisesRegex(ValueError, "answer lost"):
            select([note(value, 101), note(lost, 102)])

    def test_no_fallback_to_old_state_or_silent_scope_budget_answer_loss(self):
        old = snapshot()
        for mutate in (
            lambda v: v["objective"].update(mode="design-closure"),
            lambda v: v["objective"].update(run_id="replacement-run"),
            lambda v: v["session"].update(delegations=0),
            lambda v: v["session"].update(started_at=101),
        ):
            new = deepcopy(old)
            mutate(new)
            with self.subTest(new=new), self.assertRaises(ValueError):
                select([note(old, 101), note(new, 102)])
        malformed = note(old, 102)
        malformed["body"] = malformed["body"].replace('"version": 1', '"version": 1, "version": 1', 1)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            select([note(old, 101), malformed])
        with self.assertRaises(ValueError):
            select([note(old, 101) | {"url": BASE + "/-/issues/2#note_101"}])
        with self.assertRaises(ValueError):
            owner.parse(owner.render(old) + owner.render(old))
        self.assertEqual(select([])["action"], "reconcile_legacy")
        # A stale prose recommendation cannot bypass the derived technical work.
        old["next"] = {"action": "complete"}
        self.assertEqual(owner.next_action(old)["action"], "execution_preflight")

    def test_real_cli_round_trip_and_bad_input_do_not_write_or_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.json"
            path.write_text(json.dumps([note(snapshot(), 101)]))
            command = [sys.executable, str(ROOT / "scripts/ctx_owner.py"), "resume", str(path),
                       "--trusted-author-id", "42", "--source-issue", "10", "--epic", "E2"]
            good = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            self.assertEqual(json.loads(good.stdout)["next"]["action"], "execution_preflight")
            bad = subprocess.run(command[:-1] + ["E9"], capture_output=True, text=True, timeout=10)
            self.assertEqual(bad.returncode, 2)
            self.assertEqual(json.loads(bad.stdout)["action"], "reconcile_state")
            self.assertEqual(list(Path(directory).iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
