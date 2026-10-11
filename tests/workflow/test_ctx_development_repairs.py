"""Protocol fixtures, not assertions that an agent or application ran live."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_ctx_development import PROJECT, SHA, request, receipt
import ctx_development as dev
import ctx_execution as execution
import ctx_workflow as ctx


def repair_request():
    value = request()
    value["version"] = 2
    value["epics"][0]["acceptance_manifest"] = json.dumps({
        "version": 1, "epic": "E2", "criteria": [
            {"id": f"E2-{i}.AC1", "statement": "Approved behavior", "ui": i == 2,
             "methods": ["test", "browser"] if i == 2 else ["test"]}
            for i in range(1, 4)]}, indent=2) + "\n"
    return value


def verification(run, sha=None):
    active = run["active"]
    scope = active["target"]
    sha = sha or active["candidate_sha"]
    raw = run["request"]["epics"][0]["acceptance_manifest"]
    criteria = [c for c in json.loads(raw)["criteria"] if scope == "E2" or c["id"].startswith(scope + ".")]
    expected = {"project_id": "87329027", "source_sha": sha,
                "pipeline_id": str(100 + active["attempt"]), "scope": scope}
    identity = {"version": 1, **expected, "manifest_sha256": hashlib.sha256(raw.encode()).hexdigest()}
    jobs = {name: {k: v for k, v in expected.items() if k != "scope"} | {
        "status": "success", "allow_failure": False, "url": PROJECT + f"/-/jobs/{active['attempt'] * 10 + i}"}
        for i, name in enumerate(("ctx:verify", "ctx:acceptance", "ctx:browser"), 1)}
    rows, browser_rows = [], []
    for c in criteria:
        rows.append({"id": c["id"], "status": "passed", "code": "app.py:12", "evidence": {
            "test": {"status": "passed", "test_ids": ["test_behavior"], "url": jobs["ctx:verify"]["url"]}}})
        if c["ui"]:
            browser_rows.append({"id": c["id"], "evidence": {"browser": {
                "status": "passed", "test_ids": ["journey"], "url": jobs["ctx:browser"]["url"]}}})
    if not browser_rows:
        jobs.pop("ctx:browser")
    return {"pipeline_url": PROJECT + "/-/pipelines/" + expected["pipeline_id"],
            "pipeline_id": expected["pipeline_id"], "jobs": jobs,
            "acceptance": {**identity, "criteria": rows},
            "browser": {**identity, "criteria": browser_rows} if browser_rows else None}


def success(run):
    value = receipt(run)
    operation = run["active"]["phase"]
    if operation == "verify":
        value["verification"] = verification(run)
    if operation in {"review", "epic_review"}:
        value["verification_url"] = run["nodes"][run["active"]["target"]]["verification_url"]
    if operation == "integrate":
        value["integration"]["verification"] = verification(run, "c" * 40)
        value["integration"]["pipeline_url"] = value["integration"]["verification"]["pipeline_url"]
    if operation == "close":
        value["review_url"] = run["nodes"][run["active"]["target"]]["review_url"]
    return value


def advance(run, target, until=None):
    while run["nodes"][target]["status"] != "done" and dev.phase(run["nodes"][target]) != until:
        run = dev.claim(run, target)
        run = dev.record(run, success(run))
    return run


def defect(run):
    target = run["active"]["target"]
    return receipt(run, response="blocked", blocker_kind="defect", reason="AC regression",
                   findings=[{"id": "regression-1", "ac_ids": [f"{target if '-' in target else target + '-1'}.AC1"],
                              "summary": "Expected approved behavior; observed assertion failure",
                              "evidence_url": PROJECT + "/-/jobs/88"}])


class RepairLoopTests(unittest.TestCase):
    def test_technical_design_repair_returns_through_independent_design_review(self):
        run = dev.claim(advance(dev.new_run(repair_request()), "E2-1", "verify"), "E2-1")
        blocked = defect(run) | {"blocker_kind": "technical_design"}
        run = dev.record(run, blocked)
        original = deepcopy(run["request"])
        run = dev.repair(run, "E2-1")
        self.assertEqual(dev.next_actions(run)["ready"][0]["component"], "design")
        self.assertEqual(dev.phase(run["nodes"]["E2-1"]), "design_revision")
        run = dev.claim(run, "E2-1")
        doc_receipt = receipt(run, candidate_sha="d" * 40, resolved_findings=["regression-1"],
            changed_paths=["docs/design/trust-core/technical.md"], affected_targets=["E2-1"],
            acceptance_manifest_sha256=dev.scoped_manifest(run, "E2-1")[1])
        with self.assertRaises(ValueError):
            dev.record(run, doc_receipt | {"changed_paths": [".gitlab-ci.yml"]})
        with self.assertRaises(ValueError):
            dev.record(run, doc_receipt | {"acceptance_manifest_sha256": "f" * 64})
        with self.assertRaises(ValueError):
            dev.record(run, doc_receipt | {"affected_targets": ["E2-1", "E2-2"]})
        run = dev.record(run, doc_receipt)
        self.assertEqual(dev.phase(run["nodes"]["E2-1"]), "design_review")
        self.assertEqual(dev.next_actions(run)["ready"][0]["component"], "epic_review")
        run = dev.claim(run, "E2-1")
        with self.assertRaises(ValueError):
            dev.record(run, receipt(run, candidate_sha="c" * 40))
        run = dev.record(run, receipt(run, design_report_url=doc_receipt["report_url"],
            affected_targets=["E2-1"], acceptance_manifest_sha256=dev.scoped_manifest(run, "E2-1")[1]))
        self.assertEqual(dev.phase(run["nodes"]["E2-1"]), "tests")
        run = advance(run, "E2-1", "implementation")
        run = dev.claim(run, "E2-1")
        run = dev.record(run, receipt(run, candidate_sha="e" * 40, resolved_findings=["regression-1"]))
        run = advance(run, "E2-1")
        self.assertEqual(run["request"], original)
        self.assertEqual(run["nodes"]["E2-1"]["repairs"], 1)
        dev.verify_journal(run)
        tampered = deepcopy(run)
        tampered["nodes"]["E2-1"]["repairs"] = 0
        with self.assertRaises(ValueError):
            dev.verify_journal(tampered)

    def test_answered_decision_resumes_same_journal_without_reusing_old_evidence(self):
        run = dev.claim(advance(dev.new_run(repair_request()), "E2-1", "verify"), "E2-1")
        questions = [{"id": "Q6", "question": "Who may create an account?"}]
        run = dev.record(run, receipt(run, response="blocked", blocker_kind="decision",
                                      reason="Need product choice", decisions=questions))
        original, history = deepcopy(run["request"]), deepcopy(run["events"])
        answers = {"answers": [{"id": "Q6", "question": questions[0]["question"],
                               "answer": "Anyone with an email", "source_url": PROJECT + "/-/issues/10#note_200"}],
                   "candidate_sha": "d" * 40, "report_url": PROJECT + "/-/issues/10#note_201",
                   "report_readback": True, "changed_paths": ["docs/design/trust-core/spec.md"],
                   "affected_targets": ["E2-1"],
                   "acceptance_manifest_sha256": dev.scoped_manifest(run, "E2-1")[1]}
        self.assertTrue(callable(getattr(dev, "resume_decision", None)), "decision resume transition missing")
        with self.assertRaises(ValueError):
            dev.resume_decision(run, "E2-1", answers | {"answers": []})
        with self.assertRaises(ValueError):
            dev.resume_decision(run, "E2-1", answers | {"candidate_sha": run["nodes"]["E2-1"]["candidate_sha"]})
        run = dev.resume_decision(run, "E2-1", answers)
        self.assertEqual(dev.phase(run["nodes"]["E2-1"]), "design_review")
        self.assertNotIn("verification_url", run["nodes"]["E2-1"])
        self.assertEqual(run["request"], original)
        self.assertEqual(run["events"][:-1], history)
        dev.verify_journal(run)
        self.assertEqual(execution.decision_questions({"journal": run}), [])
        run = dev.claim(run, "E2-1")
        blocked = receipt(run, response="blocked", blocker_kind="decision", reason="A different product choice")
        legacy = dev.record(run, blocked)
        # Historical node fields must not turn a new prose-only blocker into Q6.
        dev.verify_journal(legacy)
        self.assertEqual(execution.decision_questions({"journal": legacy}), [])
        with self.assertRaisesRegex(ValueError, "recorded decision blocker"):
            dev.resume_decision(legacy, "E2-1", answers | {"candidate_sha": "e" * 40})
        questions = [{"id": "Q7", "question": "Which sign-in provider?"}]
        current = dev.record(run, blocked | {"decisions": questions})
        self.assertEqual(execution.decision_questions({"journal": current}), questions)
        dev.verify_journal(current)

    def test_manifest_is_pinned_and_covers_exact_planned_tickets(self):
        value = repair_request()
        dev.new_run(value)
        for mutation in (lambda v: v["epics"][0].pop("acceptance_manifest"),
                         lambda v: v["epics"][0].update(acceptance_manifest="{}"),
                         lambda v: v["epics"][0].update(acceptance_manifest=v["epics"][0]["acceptance_manifest"].replace("E2-3", "E2-99"))):
            changed = deepcopy(value)
            mutation(changed)
            with self.assertRaises((ValueError, ctx.Invalid)):
                dev.new_run(changed)

    def test_ticket_test_failure_repairs_then_revalidates_and_independently_reviews(self):
        run = dev.claim(advance(dev.new_run(repair_request()), "E2-1", "verify"), "E2-1")
        run = dev.record(run, defect(run))
        self.assertEqual(dev.next_actions(run)["repairable"], ["E2-1"])
        run = dev.repair(run, "E2-1")
        self.assertEqual(dev.phase(run["nodes"]["E2-1"]), "implementation")
        run = dev.claim(run, "E2-1")
        with self.assertRaisesRegex(ctx.Invalid, "new candidate"):
            dev.record(run, success(run))
        with self.assertRaisesRegex(ctx.Invalid, "resolved findings"):
            dev.record(run, receipt(run, candidate_sha="d" * 40, resolved_findings=[]))
        run = dev.record(run, receipt(run, candidate_sha="d" * 40, resolved_findings=["regression-1"]))
        self.assertEqual(dev.phase(run["nodes"]["E2-1"]), "verify")
        run = advance(run, "E2-1")
        dev.verify_journal(run)
        self.assertEqual(run["nodes"]["E2-1"]["repairs"], 1)
        self.assertEqual([e["phase"] for e in run["events"] if "phase" in e][-4:],
                         ["implementation", "verify", "review", "integrate"])

    def test_review_findings_invalidate_old_checks_and_cannot_skip_to_integration(self):
        run = dev.claim(advance(dev.new_run(repair_request()), "E2-1", "review"), "E2-1")
        old = deepcopy(run["nodes"]["E2-1"])
        run = dev.repair(dev.record(run, defect(run)), "E2-1")
        self.assertNotIn("verification_url", run["nodes"]["E2-1"])
        run = dev.claim(run, "E2-1")
        run = dev.record(run, receipt(run, candidate_sha="d" * 40, resolved_findings=["regression-1"]))
        run = dev.claim(run, "E2-1")
        stale = success(run)
        stale["verification"] = old["verification"]
        with self.assertRaises(ValueError):
            dev.record(run, stale)
        with self.assertRaises(ctx.Invalid):
            dev.record(run, receipt(run, phase="integrate"))

    def test_missing_skipped_stale_or_foreign_evidence_cannot_pass_verification(self):
        run = dev.claim(advance(dev.new_run(repair_request()), "E2-2", "verify"), "E2-2")
        mutations = [
            lambda r: r.pop("verification"),
            lambda r: r["verification"]["jobs"].pop("ctx:verify"),
            lambda r: r["verification"]["jobs"]["ctx:verify"].update(status="skipped"),
            lambda r: r["verification"]["jobs"]["ctx:verify"].update(allow_failure=True),
            lambda r: r["verification"]["jobs"]["ctx:acceptance"].update(source_sha="f" * 40),
            lambda r: r["verification"]["jobs"]["ctx:browser"].update(pipeline_id="99"),
            lambda r: r["verification"]["jobs"]["ctx:verify"].update(url="https://gitlab.com/other/project/-/jobs/12"),
            lambda r: r["verification"].update(browser=None),
            lambda r: r["verification"]["acceptance"].update(criteria=[]),
            lambda r: r["verification"]["acceptance"].update(manifest_sha256="f" * 64),
            lambda r: r["verification"]["acceptance"]["criteria"][0]["evidence"]["test"].update(url=PROJECT + "/-/jobs/999"),
        ]
        for i, mutate in enumerate(mutations):
            with self.subTest(case=i), self.assertRaises(ValueError):
                value = success(run)
                mutate(value)
                dev.record(run, value)
        dev.record(run, success(run))

    def test_whole_epic_failure_repairs_assembled_code_without_reopening_tickets(self):
        run = dev.new_run(repair_request())
        for tid in ("E2-1", "E2-2", "E2-3"):
            run = advance(run, tid)
        run = dev.claim(advance(run, "E2", "epic_review"), "E2")
        run = dev.repair(dev.record(run, defect(run)), "E2")
        self.assertTrue(all(run["nodes"][t]["status"] == "done" for t in ("E2-1", "E2-2", "E2-3")))
        run = dev.claim(run, "E2")
        run = dev.record(run, receipt(run, candidate_sha="d" * 40, resolved_findings=["regression-1"]))
        run = dev.claim(advance(run, "E2", "close"), "E2")
        with self.assertRaisesRegex(ctx.Invalid, "whole-epic review"):
            dev.record(run, success(run) | {"review_url": PROJECT + "/-/issues/10#note_999"})
        run = dev.record(run, success(run))
        self.assertTrue(dev.next_actions(run)["complete"])
        self.assertEqual(run["epic_heads"]["E2"], "d" * 40)
        self.assertEqual([e["phase"] for e in run["events"] if "phase" in e][-5:],
                         ["implementation", "docs", "verify", "epic_review", "close"])
        dev.verify_journal(run)

    def test_repairs_are_bounded_and_other_work_can_continue(self):
        run = advance(dev.new_run(repair_request()), "E2-1", "implementation")
        for i in range(4):
            run = dev.claim(run, "E2-1")
            run = dev.record(run, defect(run))
            if i < 3:
                run = dev.repair(run, "E2-1")
        self.assertEqual(dev.next_actions(run)["repairable"], [])
        with self.assertRaisesRegex(ctx.Invalid, "repair budget"):
            dev.repair(run, "E2-1")
        run = advance(run, "E2-2")
        self.assertTrue(dev.next_actions(run)["checkpoint"])
        self.assertEqual(dev.next_actions(run)["waiting"]["E2-3"], ["E2-1"])
        dev.verify_journal(run)

    def test_only_current_sha_in_scope_actionable_findings_allow_repair(self):
        run = dev.claim(advance(dev.new_run(repair_request()), "E2-1", "review"), "E2-1")
        for change in ({"findings": []}, {"candidate_sha": "f" * 40},
                       {"findings": [{"id": "bad", "ac_ids": ["E2-2.AC1"], "summary": "wrong scope", "evidence_url": PROJECT + "/-/jobs/1"}]}):
            value = defect(run)
            value.update(change)
            with self.subTest(change=change), self.assertRaises(ctx.Invalid):
                dev.record(run, value)
        for kind in ("decision", "evidence", "ci_pending", "transient", "conflict"):
            value = defect(run)
            value["blocker_kind"] = kind
            blocked = dev.record(run, value)
            with self.subTest(kind=kind), self.assertRaises(ctx.Invalid):
                dev.repair(blocked, "E2-1")
        legacy = dev.new_run(request())
        with self.assertRaises(ctx.Invalid):
            dev.repair(legacy, "E2-1")

    def test_review_and_close_bind_exact_evidence_and_integration_checks_new_sha(self):
        run = dev.claim(advance(dev.new_run(repair_request()), "E2-1", "review"), "E2-1")
        with self.assertRaises(ctx.Invalid):
            dev.record(run, success(run) | {"verification_url": PROJECT + "/-/issues/10#note_999"})
        run = dev.claim(dev.record(run, success(run)), "E2-1")
        value = success(run)
        value["integration"].pop("verification")
        with self.assertRaises(ValueError):
            dev.record(run, value)
        value = success(run)
        value["integration"]["verification"] = verification(run)  # Pre-merge evidence is stale.
        with self.assertRaises(ValueError):
            dev.record(run, value)

    def test_v2_phase_dispatch_stays_in_existing_flow_with_pinned_catalog_definition(self):
        root = Path(dev.__file__).resolve().parents[1]
        path = root / ".gitlab/duo/flows/ctx-development.yml"
        flow = ctx.read_yaml(path)
        owner = next(c for c in flow["components"] if c["name"] == "coordinate")
        workers = {s["name"] for s in owner["subagents"]}
        for phase in set(dev.V2_TICKET_PHASES + dev.V2_EPIC_PHASES + ("design_revision", "design_review")):
            self.assertIn(dev.component(phase), workers)
        prompt = next(p for p in flow["prompts"] if p["prompt_id"] == "coordinate_prompt")["prompt_template"]["system"]
        self.assertIn("VERSION 2", prompt)
        self.assertIn("repair JOURNAL TARGET", prompt)
        self.assertIn("blocker_kind=defect", prompt)
        catalog = json.loads((root / ".gitlab/ctx/catalog.json").read_text())["flows"][".gitlab/duo/flows/ctx-development.yml"]
        self.assertEqual(catalog["definition_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_pending_ci_preserves_committed_candidate_on_retry_and_global_cap_applies(self):
        run = dev.claim(advance(dev.new_run(repair_request()), "E2-1", "implementation"), "E2-1")
        run = dev.record(run, receipt(run, response="blocked", blocker_kind="ci_pending",
                                      candidate_sha="d" * 40, reason="candidate saved; CI pending"))
        run = dev.retry(run, "E2-1", PROJECT + "/-/pipelines/77")
        run = dev.claim(run, "E2-1")
        self.assertEqual(run["active"]["candidate_sha"], "d" * 40)
        run = dev.record(run, defect(run))
        dev.verify_journal(run)
        run["actions"] = dev.MAX_ACTIONS
        self.assertEqual(dev.next_actions(run)["repairable"], [])
        self.assertTrue(dev.next_actions(run)["checkpoint"])
        with self.assertRaises(ctx.Invalid):
            dev.repair(run, "E2-1")

    def test_cli_repair_resumes_and_replay_rejects_reset_repair_counter(self):
        script = str(Path(dev.__file__))
        run = dev.claim(advance(dev.new_run(repair_request()), "E2-1", "verify"), "E2-1")
        run = dev.record(run, defect(run))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / ".ctx/development/run.json"
            journal.parent.mkdir(parents=True)
            journal.write_text(json.dumps(run))
            def call(action, *args):
                return subprocess.run([sys.executable, script, action, str(journal.relative_to(root)), *args],
                                      cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(call("repair", "E2-1").returncode, 0)
            self.assertEqual(call("claim", "E2-1").returncode, 0)
            saved = json.loads(journal.read_text())
            dev.verify_journal(saved)
            self.assertEqual(saved["active"]["phase"], "implementation")
            before = journal.read_bytes()
            self.assertEqual(call("repair", "E2-1").returncode, 2)  # Never duplicate active work.
            self.assertEqual(journal.read_bytes(), before)
            saved["nodes"]["E2-1"]["repairs"] = 0
            journal.write_text(json.dumps(saved))
            self.assertEqual(call("next").returncode, 2)

    def test_ticket_only_repair_does_not_create_epic_consolidation(self):
        value = repair_request()
        value["epics"][0]["ticket_ids"] = ["E2-1"]
        run = dev.claim(advance(dev.new_run(value), "E2-1", "review"), "E2-1")
        run = dev.repair(dev.record(run, defect(run)), "E2-1")
        run = dev.claim(run, "E2-1")
        run = dev.record(run, receipt(run, candidate_sha="d" * 40, resolved_findings=["regression-1"]))
        run = advance(run, "E2-1")
        self.assertTrue(dev.next_actions(run)["complete"])
        self.assertNotIn("E2", run["nodes"])
        dev.verify_journal(run)


if __name__ == "__main__":
    unittest.main()
