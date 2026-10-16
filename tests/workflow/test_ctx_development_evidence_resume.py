"""Evidence recovery protocol fixtures; not attestation of remote CI or note reads."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_ctx_development import PROJECT, receipt, request
from test_ctx_development_repairs import advance, defect, repair_request, success, verification
import ctx_development as dev


def evidence_block(target="E2-1", spent_repair=False, ticket_only=True):
    value = repair_request()
    if ticket_only:
        value["epics"][0]["ticket_ids"] = [target]
    run = dev.claim(advance(dev.new_run(value), target, "implementation"), target)
    run = dev.record(run, receipt(run, response="blocked", blocker_kind="transient",
                                  reason="Worker terminated; saved candidate reconciled"))
    run = dev.retry(run, target, PROJECT + "/-/pipelines/77")
    if spent_repair:
        run = dev.claim(run, target)
        run = dev.repair(dev.record(run, defect(run)), target)
        run = dev.claim(run, target)
        run = dev.record(run, receipt(run, candidate_sha="d" * 40, resolved_findings=["regression-1"]))
    run = dev.claim(advance(run, target, "verify"), target)
    wrong_scope = verification(run)
    wrong_scope["acceptance"]["scope"] = "E2-99"
    return dev.record(run, receipt(run, response="blocked", blocker_kind="evidence",
                                   reason="CI emitted acceptance for another ticket", verification=wrong_scope))


def recovery_receipt(run, target="E2-1", serial=1000):
    blocked = next(e for e in reversed(run["events"]) if e.get("target") == target)
    # Reuse the existing full CI fixture without actually claiming this blocked work.
    observed = deepcopy(run)
    observed["active"] = {"target": target, "candidate_sha": blocked["candidate_sha"], "attempt": serial}
    return {"run_id": run["request"]["run_id"], "target": target, "phase": "verify",
            "blocked_attempt": blocked["attempt"], "blocked_report_url": blocked["report_url"],
            "candidate_sha": blocked["candidate_sha"], "report_readback": True,
            "report_url": PROJECT + f"/-/issues/10#note_{serial}", "verification": verification(observed)}


def maintenance_receipt(run, target="E2-1"):
    value = recovery_receipt(run, target)
    sha = "e" * 40
    observed = deepcopy(run)
    observed["active"] = {"target": target, "candidate_sha": sha, "attempt": 1000}
    value.update(candidate_sha=sha, verification=verification(observed), candidate_update={
        "previous_sha": run["nodes"][target]["candidate_sha"], "reviewed_sha": sha,
        "changed_paths": ["scripts/ctx_ci_context.py", ".gitlab/ci/browser.yml",
                          ".gitlab/ctx/verification-context.json"],
        "acceptance_manifest_sha256": dev.scoped_manifest(run, target)[1],
        "review_url": PROJECT + "/-/merge_requests/99#note_998",
        "authorization_url": PROJECT + "/-/issues/10#note_997", "remote_readback": True,
        "verification_context": {"version": 1, "project_id": "87329027", "epic": "E2", "scope": target}})
    return value


def integration_block():
    run = evidence_block(spent_repair=True, ticket_only=False)
    run = dev.resume_evidence(run, "E2-1", recovery_receipt(run))
    run = advance(run, "E2-2")
    run = dev.claim(advance(run, "E2-1", "integrate"), "E2-1")
    return dev.record(run, receipt(run, response="blocked", blocker_kind="evidence",
                                   reason="Merge API denied; verified ticket awaits human merge"))


def integration_recovery(run):
    target = "E2-1"
    blocked = run["events"][-1]
    source, merged = run["nodes"][target]["candidate_sha"], "f" * 40
    observed = deepcopy(run)
    observed["active"] = {"target": target, "candidate_sha": merged, "attempt": 2000}
    bundle = verification(observed)
    return {"run_id": run["request"]["run_id"], "target": target, "phase": "integrate",
            "blocked_attempt": blocked["attempt"], "blocked_report_url": blocked["report_url"],
            "candidate_sha": source, "report_url": PROJECT + "/-/issues/10#note_2000",
            "report_readback": True, "remote_readback": True, "ownership_verified": True,
            "merge_request": {"url": PROJECT + "/-/merge_requests/59", "project_id": "87329027",
                             "state": "merged", "source_branch": "ctx/ticket-i3", "target_branch": "ctx/epic-i2",
                             "source_sha": source, "merge_sha": merged, "target_head_sha": merged},
            "integration": {"source_sha": source, "epic_sha": merged, "pipeline_url": bundle["pipeline_url"],
                            "review_url": run["nodes"][target]["review_url"], "verification": bundle}}


class EvidenceResumeTests(unittest.TestCase):
    def resume(self, run, value=None, target="E2-1"):
        self.assertTrue(callable(getattr(dev, "resume_evidence", None)), "bounded evidence-resume transition missing")
        return dev.resume_evidence(run, target, value if value is not None else recovery_receipt(run, target))

    def test_spent_retry_and_repair_survive_resume_then_verify_and_independent_review(self):
        run = evidence_block(spent_repair=True)
        dev.verify_journal(run)  # Existing v2 history remains readable unchanged.
        before = deepcopy(run)
        self.assertEqual(dev.next_actions(run)["owner_action"]["action"], "reconcile_evidence")
        with self.assertRaises(ValueError):
            dev.retry(run, "E2-1", PROJECT + "/-/pipelines/999")
        saved = recovery_receipt(run)
        resumed = self.resume(run, saved)
        self.assertEqual(run, before)
        self.assertEqual(resumed["request"], before["request"])
        self.assertEqual(resumed["actions"], before["actions"])
        self.assertEqual(resumed["events"][:-1], before["events"])
        node = resumed["nodes"]["E2-1"]
        self.assertEqual((node["retries"], node["repairs"], dev.phase(node)), (1, 1, "verify"))
        self.assertEqual(node["candidate_sha"], before["nodes"]["E2-1"]["candidate_sha"])
        self.assertNotIn("verification_url", node)
        self.assertNotIn("review_url", node)
        self.assertNotIn("E2", resumed["nodes"])
        dev.verify_journal(resumed)
        with self.assertRaises(ValueError):
            self.resume(resumed, saved)
        claimed = dev.claim(resumed, "E2-1")
        self.assertEqual(claimed["actions"], before["actions"] + 1)
        with self.assertRaises(ValueError):
            dev.record(claimed, receipt(claimed, phase="integrate"))
        with self.assertRaises(ValueError):
            dev.record(claimed, receipt(claimed))  # Resume was not successful verification.
        checked = dev.record(claimed, success(claimed) | {"verification": saved["verification"]})
        self.assertEqual(dev.phase(checked["nodes"]["E2-1"]), "review")
        reviewed = dev.claim(checked, "E2-1")
        with self.assertRaises(ValueError):
            dev.record(reviewed, receipt(reviewed))  # Independent review still binds its own verify report.
        reviewed = dev.record(reviewed, success(reviewed))
        self.assertEqual(dev.phase(reviewed["nodes"]["E2-1"]), "integrate")
        self.assertFalse(dev.next_actions(reviewed)["complete"])
        dev.verify_journal(reviewed)

    def test_receipt_binds_block_identity_saved_source_note_and_full_current_evidence(self):
        run = evidence_block("E2-2")  # Includes mandatory independent browser evidence.
        value = recovery_receipt(run, "E2-2")
        mutations = [
            lambda r: r.update(run_id="another-run"),
            lambda r: r.update(target="E2-1"),
            lambda r: r.update(phase="review"),
            lambda r: r.update(blocked_attempt=r["blocked_attempt"] - 1),
            lambda r: r.update(blocked_report_url=PROJECT + "/-/issues/10#note_999"),
            lambda r: r.update(candidate_sha="f" * 40),
            lambda r: r.update(report_readback=False),
            lambda r: r.update(report_url=PROJECT + "/-/issues/2#note_1000"),
            lambda r: r.update(report_url="https://gitlab.com/foreign/project/-/issues/10#note_1000"),
            lambda r: r.update(report_url=PROJECT + "/-/work_items/10#note_1"),
            lambda r: r.pop("verification"),
            lambda r: r["verification"]["jobs"]["ctx:verify"].update(project_id="999"),
            lambda r: r["verification"]["jobs"]["ctx:verify"].update(source_sha="f" * 40),
            lambda r: r["verification"]["acceptance"].update(scope="E2-1"),
            lambda r: r["verification"]["acceptance"].update(manifest_sha256="f" * 64),
            lambda r: r["verification"].update(browser=None),
        ]
        for index, mutate in enumerate(mutations):
            changed = deepcopy(value)
            mutate(changed)
            with self.subTest(case=index), self.assertRaises(ValueError):
                self.resume(run, changed, "E2-2")
        dev.verify_journal(self.resume(run, value, "E2-2"))

    def test_epic_resume_keeps_integrated_tickets_and_requires_whole_epic_review(self):
        run = dev.new_run(repair_request())
        for target in ("E2-1", "E2-2", "E2-3"):
            run = advance(run, target)
        run = dev.claim(advance(run, "E2", "verify"), "E2")
        run = dev.record(run, receipt(run, response="blocked", blocker_kind="evidence",
                                      reason="Whole-epic acceptance evidence missing"))
        tickets = {target: deepcopy(node) for target, node in run["nodes"].items() if target != "E2"}
        value = maintenance_receipt(run, "E2")
        resumed = self.resume(run, value, target="E2")
        self.assertEqual({t: n for t, n in resumed["nodes"].items() if t != "E2"}, tickets)
        self.assertEqual(resumed["epic_heads"]["E2"], value["candidate_sha"])
        self.assertEqual(resumed["request"], run["request"])
        claimed = dev.claim(resumed, "E2")
        self.assertEqual(claimed["active"]["phase"], "verify")
        checked = dev.record(claimed, success(claimed))
        self.assertEqual(dev.phase(checked["nodes"]["E2"]), "epic_review")
        self.assertFalse(dev.next_actions(checked)["complete"])
        dev.verify_journal(checked)

    def test_reviewed_maintenance_adopts_new_sha_without_scope_manifest_or_budget_reset(self):
        run = evidence_block(spent_repair=True)
        before = deepcopy(run)
        value = maintenance_receipt(run)
        value["candidate_update"]["changed_paths"].extend([
            "AGENTS.md", "skills/ctx-project-go/SKILL.md", "skills/ctx-ci-check/SKILL.md",
            "skills/ctx-browser-check/SKILL.md", "docs/development/automatic-acceptance.md",
            "docs/development/gitlab-workflow.md", ".gitlab/ctx/catalog.json",
            ".gitlab/duo/agents/ctx-project.md", ".gitlab/duo/agents/ctx-project.json",
            ".gitlab/duo/flows/ctx-development.yml", "tests/workflow/test_ctx_agents.py",
            "tests/workflow/test_ctx_native_execution.py",
        ])
        resumed = self.resume(run, value)
        self.assertEqual(run, before)
        self.assertEqual(resumed["nodes"]["E2-1"]["candidate_sha"], value["candidate_sha"])
        for field in ("request", "request_sha256", "required_targets", "epic_heads", "actions"):
            self.assertEqual(resumed[field], before[field])
        self.assertEqual(resumed["events"][:-1], before["events"])
        self.assertEqual(resumed["events"][-1]["receipt"], value)
        node = resumed["nodes"]["E2-1"]
        self.assertEqual((node["retries"], node["repairs"], dev.phase(node)), (1, 1, "verify"))
        self.assertNotIn("verification", node)
        self.assertNotIn("review_url", node)
        dev.verify_journal(resumed)
        claimed = dev.claim(resumed, "E2-1")
        self.assertEqual(claimed["active"]["candidate_sha"], value["candidate_sha"])
        with self.assertRaises(ValueError):
            dev.record(claimed, success(claimed) | {"candidate_sha": before["nodes"]["E2-1"]["candidate_sha"]})
        checked = dev.record(claimed, success(claimed))
        self.assertEqual(dev.phase(checked["nodes"]["E2-1"]), "review")
        dev.verify_journal(checked)

    def test_maintenance_requires_exact_review_authority_paths_manifest_and_context(self):
        run = evidence_block()
        value = maintenance_receipt(run)
        mutations = [
            lambda r: r.pop("candidate_update"),
            lambda r: r["candidate_update"].update(previous_sha="f" * 40),
            lambda r: r["candidate_update"].update(reviewed_sha="f" * 40),
            lambda r: r["candidate_update"].update(review_url=PROJECT + "/-/issues/10#note_998"),
            lambda r: r["candidate_update"].update(review_url="https://gitlab.com/foreign/project/-/merge_requests/99#note_998"),
            lambda r: r["candidate_update"].update(authorization_url=PROJECT + "/-/issues/2#note_997"),
            lambda r: r["candidate_update"].update(remote_readback=False),
            lambda r: r["candidate_update"].update(acceptance_manifest_sha256="f" * 64),
            lambda r: r["candidate_update"].update(changed_paths=[]),
            lambda r: r["candidate_update"]["changed_paths"].append("scripts/ctx_ci_context.py"),
            lambda r: r["candidate_update"].pop("verification_context"),
            lambda r: r["candidate_update"]["verification_context"].update(scope="E2-2"),
            lambda r: r["candidate_update"]["verification_context"].update(project_id="999"),
            lambda r: r["candidate_update"]["verification_context"].update(epic="E20"),
        ]
        forbidden = ["backend/app.py", "tests/app/test_app.py", "docs/plan/E2/state.json",
                     "docs/plan/E2/acceptance.json", ".gitlab/ctx/commands.yml", "scripts/ctx_checkpoint.py",
                     ".gitlab/ctx/checkpoint-exclusions.json", ".env", "scripts/../scripts/ctx_ci_context.py",
                     ".gitlab/duo/agents/ctx-design.md", "skills/ctx-ticket-start/SKILL.md"]
        for path in forbidden:
            mutations.append(lambda r, path=path: r["candidate_update"]["changed_paths"].append(path))
        for index, mutate in enumerate(mutations):
            changed = deepcopy(value)
            mutate(changed)
            with self.subTest(case=index), self.assertRaises(ValueError):
                self.resume(run, changed)
        unchanged = recovery_receipt(run)
        with self.assertRaises(ValueError):
            self.resume(run, unchanged | {"candidate_update": value["candidate_update"]})
        # A helper-only sync does not require invented context-file contents.
        helper_only = deepcopy(value)
        helper_only["candidate_update"]["changed_paths"] = ["scripts/ctx_development.py"]
        helper_only["candidate_update"].pop("verification_context")
        dev.verify_journal(self.resume(run, helper_only))
        forged = self.resume(run, value)
        forged["events"][-1]["receipt"]["candidate_update"]["reviewed_sha"] = "f" * 40
        with self.assertRaises(ValueError):
            dev.verify_journal(forged)

    def test_only_idle_in_scope_v2_evidence_blocked_verify_can_resume(self):
        run = evidence_block()
        for name, mutate in (
            ("legacy", lambda r: r.update(version=1)),
            ("active", lambda r: r.update(active={"target": "E2-2"})),
            ("exhausted", lambda r: r.update(actions=dev.MAX_ACTIONS)),
            ("outside-focus", lambda r: r["required_targets"].remove("E2-1")),
            ("already-pending", lambda r: r["nodes"]["E2-1"].update(status="pending")),
            ("wrong-phase", lambda r: r["nodes"]["E2-1"].update(phase_index=2)),
            ("decision", lambda r: r["nodes"]["E2-1"].update(blocker_kind="decision")),
            ("conflict", lambda r: r["nodes"]["E2-1"].update(blocker_kind="conflict")),
            ("no-block-receipt", lambda r: r["events"].pop()),
        ):
            changed = deepcopy(run)
            mutate(changed)
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.resume(changed, recovery_receipt(run))
        exhausted = deepcopy(run)
        exhausted["actions"] = dev.MAX_ACTIONS
        self.assertEqual(dev.next_actions(exhausted)["owner_action"]["action"], "checkpoint")
        legacy = dev.claim(dev.new_run(request()), "E2-1")
        legacy = dev.record(legacy, receipt(legacy, response="blocked", blocker_kind="evidence", reason="missing"))
        dev.verify_journal(legacy)
        self.assertNotEqual(dev.next_actions(legacy)["owner_action"]["action"], "reconcile_evidence")

    def test_new_block_cannot_reuse_old_resume_receipt_pipeline_or_source_note(self):
        run = evidence_block()
        original = recovery_receipt(run)
        resumed = self.resume(run, original)
        run = dev.claim(resumed, "E2-1")
        run = dev.record(run, receipt(run, response="blocked", blocker_kind="evidence",
                                      reason="Newly observed missing evidence", report_url=PROJECT + "/-/issues/10#note_1001"))
        new = recovery_receipt(run, serial=2000)
        for changed in (original, new | {"verification": original["verification"]},
                        new | {"report_url": original["report_url"].replace("/issues/", "/work_items/")}):
            with self.subTest(receipt=changed["report_url"]), self.assertRaises(ValueError):
                self.resume(run, changed)
        restored = self.resume(run, new)
        self.assertEqual(restored["actions"], resumed["actions"] + 1)
        self.assertEqual(restored["nodes"]["E2-1"]["retries"], 1)
        dev.verify_journal(restored)
        forged = deepcopy(restored)
        forged["events"][-1]["receipt"]["blocked_attempt"] -= 1
        with self.assertRaises(ValueError):
            dev.verify_journal(forged)
        forged = deepcopy(restored)
        forged["nodes"]["E2-1"]["retries"] = 0
        with self.assertRaises(ValueError):
            dev.verify_journal(forged)

    def test_human_merge_reopens_read_only_integration_without_completing_or_refunding(self):
        run = integration_block()
        before = deepcopy(run)
        dev.verify_journal(run)
        self.assertEqual(dev.next_actions(run)["owner_action"]["action"], "reconcile_integration")
        value = integration_recovery(run)
        resumed = dev.resume_integration(run, "E2-1", value)
        self.assertEqual(run, before)
        for field in ("request", "request_sha256", "required_targets", "epic_heads", "actions"):
            self.assertEqual(resumed[field], before[field])
        self.assertEqual(resumed["events"][:-1], before["events"])
        node = resumed["nodes"]["E2-1"]
        self.assertEqual((node["retries"], node["repairs"], node["status"], dev.phase(node)), (1, 1, "pending", "integrate"))
        self.assertEqual(node["review_url"], before["nodes"]["E2-1"]["review_url"])
        self.assertFalse(dev.next_actions(resumed)["complete"])
        self.assertEqual(dev.next_actions(resumed)["waiting"]["E2-3"], ["E2-1"])
        self.assertEqual(dev.next_actions(resumed)["owner_action"]["mode"], "read-only-reconciliation")
        dev.verify_journal(resumed)
        with self.assertRaises(ValueError):
            dev.resume_integration(resumed, "E2-1", value)
        claimed = dev.claim(resumed, "E2-1")
        self.assertEqual(claimed["actions"], before["actions"] + 1)
        self.assertEqual(claimed["active"]["mode"], "read-only-reconciliation")
        with self.assertRaises(ValueError):
            dev.record(claimed, success(claimed))  # Cannot substitute another merge result.
        completed = dev.record(claimed, receipt(claimed, integration=value["integration"]))
        self.assertEqual(completed["nodes"]["E2-1"]["status"], "done")
        self.assertEqual(completed["epic_heads"]["E2"], value["merge_request"]["merge_sha"])
        self.assertIn("E2-3", [item["target"] for item in dev.next_actions(completed)["ready"]])
        dev.verify_journal(completed)

    def test_integration_resume_rejects_wrong_merge_review_ownership_evidence_and_block(self):
        self.assertTrue(callable(getattr(dev, "resume_integration", None)), "bounded integration resume missing")
        run = integration_block()
        value = integration_recovery(run)
        mutations = [
            lambda r: r.update(run_id="another"),
            lambda r: r.update(blocked_attempt=r["blocked_attempt"] - 1),
            lambda r: r.update(blocked_report_url=PROJECT + "/-/issues/10#note_999"),
            lambda r: r.update(candidate_sha="e" * 40),
            lambda r: r.update(report_readback=False),
            lambda r: r.update(remote_readback=False),
            lambda r: r.update(ownership_verified=False),
            lambda r: r.update(report_url=PROJECT + "/-/work_items/10#note_1000"),
            lambda r: r["merge_request"].update(state="opened"),
            lambda r: r["merge_request"].update(project_id="999"),
            lambda r: r["merge_request"].update(url="https://gitlab.com/foreign/project/-/merge_requests/59"),
            lambda r: r["merge_request"].update(source_branch="ctx/ticket-i4"),
            lambda r: r["merge_request"].update(target_branch="main"),
            lambda r: r["merge_request"].update(source_sha="e" * 40),
            lambda r: r["merge_request"].update(merge_sha="e" * 40),
            lambda r: r["merge_request"].update(target_head_sha="e" * 40),
            lambda r: r["integration"].update(review_url=PROJECT + "/-/issues/10#note_999"),
            lambda r: r["integration"]["verification"]["acceptance"].update(scope="E2-2"),
            lambda r: r["integration"]["verification"]["acceptance"].update(manifest_sha256="e" * 64),
            lambda r: r["integration"]["verification"]["jobs"]["ctx:verify"].update(source_sha=value["candidate_sha"]),
        ]
        for index, mutate in enumerate(mutations):
            changed = deepcopy(value)
            mutate(changed)
            with self.subTest(case=index), self.assertRaises(ValueError):
                dev.resume_integration(run, "E2-1", changed)
        for name, mutate in (
            ("legacy", lambda r: r.update(version=1)),
            ("active", lambda r: r.update(active={"target": "E2-1"})),
            ("exhausted", lambda r: r.update(actions=dev.MAX_ACTIONS)),
            ("wrong-phase", lambda r: r["nodes"]["E2-1"].update(phase_index=3)),
            ("conflict", lambda r: r["nodes"]["E2-1"].update(blocker_kind="conflict")),
            ("wrong-review", lambda r: r["nodes"]["E2-1"].update(review_url=PROJECT + "/-/issues/10#note_999")),
        ):
            changed = deepcopy(run)
            mutate(changed)
            with self.subTest(case=name), self.assertRaises(ValueError):
                dev.resume_integration(changed, "E2-1", value)
        forged = dev.resume_integration(run, "E2-1", value)
        forged["events"][-1]["receipt"]["merge_request"]["source_sha"] = "e" * 40
        with self.assertRaises(ValueError):
            dev.verify_journal(forged)

    def test_cli_integration_resume_is_atomic_and_replay_safe(self):
        run = integration_block()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / ".ctx/development/run.json"
            journal.parent.mkdir(parents=True)
            journal.write_text(json.dumps(run))
            evidence = root / "merge.json"
            evidence.write_text(json.dumps(integration_recovery(run)))
            command = [sys.executable, dev.__file__, "resume-integration", str(journal.relative_to(root)),
                       "E2-1", "--receipt", str(evidence)]
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["owner_action"]["mode"], "read-only-reconciliation")
            dev.verify_journal(json.loads(journal.read_text()))
            before = journal.read_bytes()
            rejected = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual(journal.read_bytes(), before)

    def test_cli_atomic_resume_and_rejected_replay_leave_journal_intact(self):
        run = evidence_block()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / ".ctx/development/run.json"
            journal.parent.mkdir(parents=True)
            journal.write_text(json.dumps(run))
            evidence = root / "evidence.json"
            evidence.write_text(json.dumps(recovery_receipt(run)))
            command = [sys.executable, dev.__file__, "resume-evidence", str(journal.relative_to(root)),
                       "E2-1", "--receipt", str(evidence)]
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["owner_action"]["phase"], "verify")
            dev.verify_journal(json.loads(journal.read_text()))
            before = journal.read_bytes()
            rejected = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual(journal.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
