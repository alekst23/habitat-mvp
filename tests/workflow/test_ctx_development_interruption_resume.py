"""Recovery protocol fixtures, not proof of remote ownership or platform failure."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_ctx_development import PROJECT, receipt, request
from test_ctx_development_repairs import advance, defect, repair_request, success
import ctx_development as dev


def blocked(run, target, session=900, note=900):
    run = dev.claim(run, target)
    claim = deepcopy(run["active"])
    report = PROJECT + f"/-/issues/10#note_{note}"
    interruption = {
        "project_id": "87329027", "session_id": str(session),
        "session_url": PROJECT + f"/-/automate/agent-sessions/{session}",
        "status": "failed", "job_url": PROJECT + f"/-/jobs/{session + 10000}",
        "job_status": "failed", "cause": "execution_limit", "result_absent": True,
        "terminal_reason": "execution_limit", "detail": "Runner reported execution limit reached",
        "evidence_url": PROJECT + f"/-/jobs/{session + 10000}#L20",
        "claim": claim | {"report_url": report},
    }
    return dev.record(run, receipt(run, response="blocked", blocker_kind="transient",
        reason="Worker hit execution limit; no valid saved result", report_url=report,
        interruption=interruption))


def interrupted(phase="review", spent_retry=True):
    value = repair_request()
    value["epics"][0]["ticket_ids"] = ["E2-1"]
    run = advance(dev.new_run(value), "E2-1", "implementation")
    if spent_retry:
        run = blocked(run, "E2-1", session=800, note=800)
        run = dev.retry(run, "E2-1", PROJECT + "/-/issues/10#note_801")
    return blocked(advance(run, "E2-1", phase), "E2-1")


def recovery(run, target="E2-1", note=1000):
    event = next(e for e in reversed(run["events"]) if e.get("target") == target)
    return {"run_id": run["request"]["run_id"], "target": target, "phase": event["phase"],
            "blocked_attempt": event["attempt"], "blocked_report_url": event["report_url"],
            "candidate_sha": event["candidate_sha"],
            "acceptance_manifest_sha256": dev.scoped_manifest(run, target)[1],
            "report_url": PROJECT + f"/-/issues/10#note_{note}", "report_readback": True,
            "remote_readback": True, "ownership_verified": True,
            "interruption": deepcopy(event["interruption"])}


def transferred_evidence(run):
    """An authenticated remote readback is a runner obligation, not a fixture claim."""
    value = recovery(run)
    obs = value["interruption"]
    obs.update(job_status="success", cause="stream_lost", terminal_reason="delegation_result_missing",
               detail="Observed lost stream and unfinished delegation", evidence_url=obs["job_url"])
    component = "browser" if value["phase"] == "verify" else "review"
    obs["log_evidence"] = {
        "version": 1, "observer": "ctx-project", "observer_author_id": "123",
        "access_path": "job_log_tool", "note_url": PROJECT + "/-/issues/10#note_950",
        "excerpt": f"Workflow {obs['session_id']} stream ended while still CREATED; the turn's tail was lost\n"
                   f"Run ended with the delegation to {component} still in progress; no result was returned.",
    }
    # Historic prose-only blocker: do not edit its saved history to add an observation.
    run["events"][-1].pop("interruption")
    return value


class InterruptionResumeTests(unittest.TestCase):
    def resume(self, run, value=None, target="E2-1"):
        self.assertTrue(callable(getattr(dev, "resume_interrupted", None)),
                        "bounded interrupted-phase recovery is missing")
        return dev.resume_interrupted(run, target, value if value is not None else recovery(run, target))

    def test_owner_requests_reconciliation_even_after_old_retry_is_spent(self):
        run = interrupted()
        self.assertEqual(run["nodes"]["E2-1"]["retries"], 1)
        advice = dev.next_actions(run)["owner_action"]
        self.assertEqual(advice["action"], "reconcile_interruption")
        self.assertEqual((advice["target"], advice["phase"]), ("E2-1", "review"))
        self.assertIn("verify", advice["reason"])

    def test_transferred_log_evidence_without_line_numbers_replays_and_preserves_budgets(self):
        for operation in ("review", "verify"):
            run = interrupted(operation)
            value = transferred_evidence(run)
            before = deepcopy(run)
            resumed = self.resume(run, value)
            dev.verify_journal(resumed)
            self.assertEqual(run, before)
            self.assertEqual(resumed["events"][:-1], before["events"])
            self.assertEqual(resumed["actions"], before["actions"] + 1)
            self.assertEqual(resumed["nodes"]["E2-1"]["retries"], 1)
            self.assertEqual(resumed["nodes"]["E2-1"]["repairs"], before["nodes"]["E2-1"]["repairs"])
            self.assertEqual(dev.claim(resumed, "E2-1")["active"]["phase"], operation)
            # Enrich a matching structured failure without mutating its original facts.
            run["events"][-1]["interruption"] = {k: deepcopy(v) for k, v in value["interruption"].items()
                                                if k != "log_evidence"}
            run["events"][-1]["interruption"]["evidence_url"] += "#L1976"
            dev.verify_journal(self.resume(run, value))

    def test_transferred_evidence_rejects_unbound_summary_or_missing_provenance(self):
        run = interrupted()
        value = transferred_evidence(run)
        evidence = value["interruption"]["log_evidence"]
        for change in ({"version": True}, {"observer": "human-confirmed"}, {"observer_author_id": "0"},
                       {"access_path": "agent_summary"}, {"excerpt": "Previous agent says this timed out"},
                       {"excerpt": evidence["excerpt"].replace("Workflow 900", "Workflow 901")},
                       {"excerpt": evidence["excerpt"].replace("delegation to review", "delegation to browser")},
                       {"note_url": PROJECT + "/-/issues/11#note_950"},
                       {"note_url": PROJECT + "/-/issues/10#note_900"},
                       {"note_url": PROJECT + "/-/issues/10#note_1000"}):
            changed = deepcopy(value)
            changed["interruption"]["log_evidence"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.resume(run, changed)
        for change in ({"evidence_url": PROJECT + "/-/jobs/10901"},
                       {"cause": "execution_limit", "terminal_reason": "execution_limit", "job_status": "failed"}):
            changed = deepcopy(value)
            changed["interruption"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.resume(run, changed)
        # No structured evidence cannot silently opt into the anchor-free path.
        changed = deepcopy(value)
        changed["interruption"].pop("log_evidence")
        with self.assertRaises(ValueError):
            self.resume(run, changed)

    def test_legacy_unmetered_history_replays_but_already_spends_the_new_cap(self):
        run = interrupted()
        historical = self.resume(run)
        # Pre-tightening serialized format: no action field or recovery charge.
        historical["events"][-1].pop("action")
        historical["actions"] -= 1
        before = deepcopy(historical)
        dev.verify_journal(historical)
        self.assertEqual(historical, before)
        again = blocked(historical, "E2-1", session=901, note=1100)
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            self.resume(again, recovery(again, note=1200))
        self.assertEqual(dev.next_actions(again)["owner_action"]["action"], "checkpoint")

    def test_recovery_charge_is_replayed_and_cannot_exceed_action_budget(self):
        run = interrupted()
        resumed = self.resume(run)
        for action in (True, resumed["actions"] - 1, resumed["actions"] + 1):
            changed = deepcopy(resumed)
            changed["events"][-1]["action"] = action
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, "next journal action"):
                dev.verify_journal(changed)
        # Lower the ceiling to the next action to test the boundary without
        # manufacturing or resetting any journal counts.
        with patch.object(dev, "MAX_ACTIONS", run["actions"] + 1):
            last = self.resume(run)
            dev.verify_journal(last)
            self.assertEqual(dev.next_actions(last)["owner_action"]["action"], "checkpoint")
            with self.assertRaises(ValueError):
                dev.claim(last, "E2-1")

    def test_recovery_keeps_evidence_history_and_budgets_and_claim_still_costs_action(self):
        run = interrupted()
        before = deepcopy(run)
        resumed = self.resume(run)
        self.assertEqual(run, before)
        self.assertEqual(resumed["events"][:-1], before["events"])
        expected_node = deepcopy(before["nodes"]["E2-1"])
        expected_node.update(status="pending", reason="")
        expected_node.pop("blocker_kind")
        self.assertEqual(resumed["nodes"]["E2-1"], expected_node)
        for key in ("request", "request_sha256", "epic_heads", "required_targets"):
            self.assertEqual(resumed[key], before[key])
        self.assertEqual(resumed["actions"], before["actions"] + 1)
        self.assertEqual(resumed["events"][-1]["action"], resumed["actions"])
        self.assertFalse(dev.next_actions(resumed)["complete"])
        dev.verify_journal(resumed)
        claimed = dev.claim(resumed, "E2-1")
        self.assertEqual(claimed["actions"], before["actions"] + 2)
        self.assertEqual(claimed["active"]["phase"], "review")
        with self.assertRaises(ValueError):
            dev.record(claimed, receipt(claimed))  # Still needs independent verification binding.
        reviewed = dev.record(claimed, success(claimed))
        self.assertEqual(dev.phase(reviewed["nodes"]["E2-1"]), "integrate")
        self.assertFalse(dev.next_actions(reviewed)["complete"])
        dev.verify_journal(reviewed)

    def test_spent_retry_with_43_actions_left_like_e11_and_legacy_replay(self):
        # Eleven legitimate actions on another ticket; no edits to derived counters.
        value = repair_request()
        run = blocked(dev.new_run(value), "E2-1", session=700, note=700)
        run = dev.retry(run, "E2-1", PROJECT + "/-/issues/10#note_701")
        for operation, sha in (("implementation", "d" * 40), ("review", "e" * 40)):
            run = dev.claim(advance(run, "E2-1", operation), "E2-1")
            run = dev.repair(dev.record(run, defect(run)), "E2-1")
            run = dev.claim(run, "E2-1")
            run = dev.record(run, receipt(run, candidate_sha=sha, resolved_findings=["regression-1"]))
        run = advance(run, "E2-1")
        run = blocked(advance(run, "E2-2", "implementation"), "E2-2", session=800, note=800)
        run = dev.retry(run, "E2-2", PROJECT + "/-/issues/10#note_801")
        run = blocked(advance(run, "E2-2", "review"), "E2-2")
        self.assertEqual(run["actions"], 17)
        self.assertEqual(dev.next_actions(run)["actions_remaining"], 43)
        self.assertEqual((run["nodes"]["E2-2"]["retries"], run["nodes"]["E2-2"]["repairs"]), (1, 0))
        # Historical receipts need not contain the new structured interruption.
        value = recovery(run, "E2-2")
        run["events"][-1].pop("interruption")
        dev.verify_journal(run)
        resumed = self.resume(run, value, "E2-2")
        self.assertEqual(resumed["actions"], 18)
        self.assertEqual(dev.claim(resumed, "E2-2")["actions"], 19)
        dev.verify_journal(resumed)
        legacy = dev.claim(dev.new_run(request()), "E2-1")
        legacy = dev.record(legacy, receipt(legacy, response="blocked", reason="worker interrupted", blocker_kind="transient"))
        legacy = dev.retry(legacy, "E2-1", PROJECT + "/-/issues/10#note_50")
        dev.verify_journal(legacy)  # No new serialized fields or changed old retry semantics.
        with self.assertRaises(ValueError):
            self.resume(legacy, value)

    def test_failed_session_successful_wrapper_stream_loss_requires_exact_log_evidence(self):
        run = interrupted()
        # Actual observed shape: wrapper exits 0 while the review stream lost its tail.
        obs = run["events"][-1]["interruption"]
        obs.update(session_id="9621826", session_url=PROJECT + "/-/automate/agent-sessions/9621826",
                   job_url=PROJECT + "/-/jobs/17244915866", job_status="success", cause="stream_lost",
                   terminal_reason="delegation_result_missing",
                   evidence_url=PROJECT + "/-/jobs/17244915866#L1976",
                   detail="Stream ended while CREATED; review delegation still in progress, no result returned")
        value = recovery(run)
        # Existing failure report is prose-only: observation is added in the new
        # recovery receipt after actual report/job readback, never patched into history.
        run["events"][-1].pop("interruption")
        dev.verify_journal(self.resume(run, value))
        for change in ({"cause": "execution_limit", "terminal_reason": "execution_limit"},
                       {"cause": "runner_failure", "terminal_reason": "runner_failure"},
                       {"terminal_reason": "timeout"}, {"detail": ""},
                       {"evidence_url": PROJECT + "/-/jobs/17244915867#L1976"},
                       {"evidence_url": PROJECT + "/-/jobs/17244915866"}):
            changed = deepcopy(value)
            changed["interruption"].update(change)
            candidate = deepcopy(run)
            candidate["events"][-1]["interruption"] = deepcopy(changed["interruption"])
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.resume(candidate, changed)

    def test_receipt_rejects_wrong_identity_ownership_and_non_platform_failures(self):
        run, value = interrupted(), recovery(interrupted())
        bad_fields = {"run_id": "other", "target": "E2-2", "phase": "integrate", "blocked_attempt": True,
                      "blocked_report_url": PROJECT + "/-/issues/10#note_800", "candidate_sha": "f" * 40,
                      "acceptance_manifest_sha256": "f" * 64, "report_readback": 1,
                      "remote_readback": False, "ownership_verified": False,
                      "report_url": PROJECT + "/-/issues/2#note_1000"}
        for key, bad in bad_fields.items():
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.resume(run, value | {key: bad})
        for change in ({"project_id": "999"}, {"session_id": "0"}, {"session_id": 900},
                       {"session_url": "https://gitlab.com/foreign/project/-/automate/agent-sessions/900"},
                       {"job_url": PROJECT + "/-/jobs/0"},
                       {"job_url": "https://gitlab.com/foreign/project/-/jobs/10900"},
                       {"status": "running"}, {"status": "unknown"}, {"status": "finished"},
                       {"job_status": "running"}, {"cause": "permission_denied"},
                       {"cause": "authentication_failure"}, {"cause": "ci_defect"},
                       {"result_absent": False}, {"claim": {}}, {"unknown": True}):
            changed = deepcopy(value)
            changed["interruption"].update(change)
            with self.subTest(observation=change), self.assertRaises(ValueError):
                self.resume(run, changed)
        for field in ("interruption", "ownership_verified"):
            changed = deepcopy(value)
            changed.pop(field)
            with self.assertRaises(ValueError):
                self.resume(run, changed)
        with self.assertRaises(ValueError):
            self.resume(run, value | {"candidate_update": {}})
        # A different same-project session cannot replace the one recorded by the blocker.
        changed = deepcopy(value)
        changed["interruption"].update(session_id="901", session_url=PROJECT + "/-/automate/agent-sessions/901")
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.resume(run, changed)

    def test_cap_survives_new_candidate_and_session_and_old_retry_cannot_bypass_it(self):
        run = interrupted(spent_retry=False)
        first = self.resume(run)
        again = blocked(first, "E2-1", session=901, note=1100)
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            self.resume(again, recovery(again, note=1200))
        with self.assertRaisesRegex(ValueError, "old retry"):
            dev.retry(again, "E2-1", PROJECT + "/-/issues/10#note_1101")
        # A real code repair and new SHA do not replenish interruption recoveries.
        active = dev.claim(first, "E2-1")
        run = dev.repair(dev.record(active, defect(active)), "E2-1")
        run = dev.claim(run, "E2-1")
        run = dev.record(run, receipt(run, candidate_sha="d" * 40, resolved_findings=["regression-1"]))
        run = blocked(advance(run, "E2-1", "review"), "E2-1", session=901, note=1100)
        self.assertEqual(dev.interruption_resumes(run, "E2-1", "review"), 1)
        self.assertEqual(run["nodes"]["E2-1"]["retries"], 0)
        advice = dev.next_actions(run)["owner_action"]
        self.assertEqual(advice["action"], "checkpoint")
        self.assertIn("interrupted-phase recovery budget exhausted", advice["reason"])
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            self.resume(run, recovery(run, note=1200))
        with self.assertRaisesRegex(ValueError, "old retry"):
            dev.retry(run, "E2-1", PROJECT + "/-/issues/10#note_1400")
        dev.verify_journal(run)
        changed = deepcopy(run)
        changed["events"] = [e for e in changed["events"] if "interruption_resume" not in e]
        with self.assertRaises(ValueError):
            dev.verify_journal(changed)

    def test_observations_and_source_notes_cannot_be_reused_even_inside_nested_recovery(self):
        first = self.resume(interrupted("verify"))
        first = advance(first, "E2-1", "review")
        old = next(e["receipt"]["interruption"] for e in first["events"] if "interruption_resume" in e)
        for same in ("session", "job"):
            run = blocked(first, "E2-1", session=901, note=1100)
            obs = run["events"][-1]["interruption"]
            if same == "session":
                obs.update(session_id=old["session_id"], session_url=old["session_url"])
            else:
                obs.update(job_url=old["job_url"], evidence_url=old["evidence_url"])
            with self.subTest(same=same), self.assertRaisesRegex(ValueError, "already used"):
                self.resume(run, recovery(run, note=1200))
        run = blocked(first, "E2-1", session=901, note=950)
        with self.assertRaisesRegex(ValueError, "fresh source report"):
            self.resume(run, recovery(run, note=1000))
        with self.assertRaisesRegex(ValueError, "fresh source report"):
            dev.require_fresh_recovery(run, "E2-1", PROJECT + "/-/work_items/10#note_1000", "9999")
        run["events"][-1]["prior_observation"] = {"receipt": {"source_url": PROJECT + "/-/work_items/10#note_2000"}}
        with self.assertRaisesRegex(ValueError, "fresh source report"):
            self.resume(run, recovery(run, note=1500))
        dev.verify_journal(self.resume(run, recovery(run, note=2001)))

    def test_only_latest_idle_transient_read_phase_and_remaining_budget_are_eligible(self):
        for operation in ("design", "tests", "implementation", "integrate", "close"):
            run = dev.new_run(repair_request())
            target = "E2-1"
            if operation == "close":
                for ticket in ("E2-1", "E2-2", "E2-3"):
                    run = advance(run, ticket)
                target = "E2"
            run = blocked(advance(run, target, operation), target)
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                self.resume(run, recovery(run, target), target)
        run = interrupted()
        for kind in ("decision", "defect", "evidence", "conflict", "ci_pending"):
            changed = deepcopy(run)
            changed["nodes"]["E2-1"]["blocker_kind"] = kind
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.resume(changed, recovery(run))
        stale = deepcopy(run)
        stale["events"][-1]["blocker_kind"] = "decision"  # Do not trust cached node classification.
        self.assertIsNone(dev.interruption_blocker(stale, "E2-1"))
        with self.assertRaises(ValueError):
            self.resume(stale, recovery(run))
        for change in ({"active": {"target": "E2-1"}}, {"actions": dev.MAX_ACTIONS}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.resume(run | change, recovery(run))
        self.assertEqual(dev.next_actions(run | {"actions": dev.MAX_ACTIONS})["owner_action"]["action"], "checkpoint")
        with self.assertRaises(ValueError):
            self.resume(run, recovery(run), "E2-2")

    def test_verify_and_review_retain_evidence_gates_and_other_reviews_are_excluded(self):
        verify = self.resume(interrupted("verify"))
        claim = dev.claim(verify, "E2-1")
        with self.assertRaises(ValueError):
            dev.record(claim, receipt(claim))  # Recovery never becomes a passing AC bundle.
        checked = dev.record(claim, success(claim))
        self.assertEqual(dev.phase(checked["nodes"]["E2-1"]), "review")
        dev.verify_journal(checked)
        for mutate in (lambda n: n.pop("verification_url"),
                       lambda n: n["verification"]["acceptance"].update(source_sha="f" * 40),
                       lambda n: n.update(verification_url=PROJECT + "/-/issues/10#note_999")):
            run = interrupted()
            mutate(run["nodes"]["E2-1"])
            with self.assertRaises(ValueError):
                self.resume(run)
        epic = dev.new_run(repair_request())
        for target in ("E2-1", "E2-2", "E2-3"):
            epic = advance(epic, target)
        epic = blocked(advance(epic, "E2", "epic_review"), "E2")
        with self.assertRaises(ValueError):
            self.resume(epic, recovery(epic, "E2"), "E2")
        run = dev.claim(advance(dev.new_run(repair_request()), "E2-1", "verify"), "E2-1")
        run = dev.repair(dev.record(run, defect(run) | {"blocker_kind": "technical_design"}), "E2-1")
        run = dev.claim(run, "E2-1")
        addendum = receipt(run, candidate_sha="d" * 40, resolved_findings=["regression-1"],
                           changed_paths=["docs/design/trust/technical.md"], affected_targets=["E2-1"],
                           acceptance_manifest_sha256=dev.scoped_manifest(run, "E2-1")[1])
        run = blocked(dev.record(run, addendum), "E2-1")
        with self.assertRaises(ValueError):
            self.resume(run)

    def test_cli_transition_is_atomic_replayable_and_rejects_repeated_or_invalid_resume(self):
        run = interrupted()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / ".ctx/development/run.json"
            journal.parent.mkdir(parents=True)
            journal.write_text(json.dumps(run))
            saved_receipt = root / "receipt.json"
            saved_receipt.write_text(json.dumps(recovery(run)))
            command = [sys.executable, dev.__file__, "resume-interrupted", str(journal.relative_to(root)), "E2-1",
                       "--receipt", str(saved_receipt)]
            before = journal.read_bytes()
            saved_receipt.write_text(json.dumps(recovery(run) | {"ownership_verified": False}))
            failed = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(failed.returncode, 2, failed.stdout + failed.stderr)
            self.assertEqual(journal.read_bytes(), before)
            saved_receipt.write_text(json.dumps(recovery(run)))
            completed = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(journal.read_text())
            dev.verify_journal(result)
            self.assertEqual(result["actions"], run["actions"] + 1)
            self.assertEqual(result["events"][-1]["interruption_resume"], "E2-1")
            before = journal.read_bytes()
            replay = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(replay.returncode, 2)
            self.assertEqual(journal.read_bytes(), before)
            self.assertEqual(list(journal.parent.glob("run.json.*")), [Path(str(journal) + ".lock")])

    def test_owner_handoff_round_trip_and_next_session_keep_recovery_and_claim(self):
        import test_ctx_development as fixtures
        import test_ctx_development_repairs as repairs
        from test_ctx_owner import BASE, SHA, note, owner, select, snapshot

        value = snapshot()
        spec = repair_request()
        spec.update(project_path=owner.closure.PROJECT, session_url=BASE + "/-/automate/agent-sessions/123")
        spec["epics"][0].update(design_sha=SHA, ticket_ids=["E2-1"])
        value["objective"]["ticket_ids"] = ["E2-1"]
        with patch.object(fixtures, "PROJECT", BASE), patch.object(repairs, "PROJECT", BASE), \
                patch.object(sys.modules[__name__], "PROJECT", BASE):
            value["journal"] = blocked(advance(dev.new_run(spec), "E2-1", "review"), "E2-1")
            restored = owner.parse(owner.render(value))
            self.assertEqual(restored, value)
            self.assertEqual(owner.next_action(restored)["action"], "reconcile_interruption")
            resumed = deepcopy(restored)
            resumed["journal"] = self.resume(restored["journal"])
            resumed["session"] = {"session_id": 901, "started_at": 5000, "delegations": 0}
            latest = select([note(value, 1001), note(resumed, 1002)])
            self.assertEqual(latest["next"]["action"], "delegate")
            self.assertEqual(latest["handoff"]["journal"]["events"][:-1], value["journal"]["events"])
            claimed = deepcopy(latest["handoff"])
            claimed["journal"] = dev.claim(claimed["journal"], "E2-1")
            claimed["session"]["delegations"] = 1
            handoff = select([note(value, 1001), note(resumed, 1002), note(claimed, 1003)])
            self.assertEqual(handoff["next"]["action"], "reconcile_active")
            self.assertEqual(owner.parse(owner.render(handoff["handoff"])), claimed)


if __name__ == "__main__":
    unittest.main()
