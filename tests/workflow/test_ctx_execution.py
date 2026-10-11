"""Controller transition/transport tests, not evidence of native Duo execution."""
from copy import deepcopy
import base64
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import ctx_execution as execution
import ctx_execution_gitlab as transport
from ctx_execution_budget import admission

SHA = "a" * 40
CONFIG = {"version": 1, "enabled": True, "consumer_id": 77, "catalog_version_id": 88,
          "report_author_ids": [99], "agent_privileges": [1, 2, 3, 4, 5], "pre_approved_agent_privileges": []}


def request():
    return {"version": 1, "run_id": "e2-test", "project_id": execution.PROJECT_ID, "source_issue_iid": 10,
            "epic_issue_iid": 2, "branch": "ctx/epic-i2", "mode": "design-closure", "objective": "Close design only",
            "design_sha": SHA, "max_sessions": 4, "max_recoveries": 1}


class Store:
    def __init__(self):
        self.state = execution.new_run(request())
        self.revision = 1

    def load(self):
        return deepcopy(self.state), self.revision

    def save(self, state, revision):
        if revision != self.revision:
            raise ValueError("competing controller")
        self.state = deepcopy(state)
        self.revision += 1
        return self.revision


class API:
    def __init__(self):
        self.starts = []
        self.status = "running"
        self.saved_notes = []
        self.lost_response = False

    def start(self, goal, req, config):
        self.starts.append(goal)
        if self.lost_response:
            raise ValueError("transport/unknown outcome")
        return {"id": len(self.starts), "project_id": execution.PROJECT_ID}

    def sessions(self, session_id, marker):
        return [{"id": len(self.starts), "project_id": execution.PROJECT_ID,
                 "goal": self.starts[-1], "status": self.status}]

    def notes(self, issue):
        return deepcopy(self.saved_notes)

    def note(self, issue, note_id):
        return deepcopy(next(n for n in self.saved_notes if n["id"] == note_id))

    def head(self, branch):
        return SHA


def receipt(state, outcome="continue"):
    closure = {"version": 1, "mode": "design-closure", "project_id": execution.PROJECT_ID,
               "source_issue_iid": 10, "epic": "E2", "branch": "ctx/epic-i2", "candidate_sha": SHA,
               "structural_sha": None, "handoff_sha": None, "review": None,
               "repairs": [], "research_attempts": [], "active": None}
    return {"version": 1, "run_id": "e2-test", "attempt_id": state["active"]["id"],
            "request_sha256": state["request_sha256"], "previous_checkpoint_sha256": state["checkpoint_sha256"],
            "session_id": state["active"]["session_id"], "candidate_sha": SHA, "outcome": outcome,
            "summary": "Saved progress. Agent next: independent review. Your action: none.",
            "next_action": "validate", "closure": closure, "journal": None}


class ControllerTests(unittest.TestCase):
    def test_execute_objective_survives_design_closure_and_failed_worker(self):
        self.store.state = execution.new_run({**request(), "mode": "execute", "objective": "Fully implement E2"})
        self.controller.tick()
        self.assertIn('"next_action"', self.api.starts[-1], "dispatch must carry the derived next action")
        self.api.status = "failed"
        self.controller.tick()
        self.assertEqual(self.store.state["request"]["objective"], "Fully implement E2")
        self.controller.tick()
        self.assertIn('"reconcile_session_id":1', self.api.starts[-1])
        value = receipt(self.store.state)
        value["closure"].update(structural_sha=SHA, handoff_sha=SHA, review={"sha": SHA, "reviewer": "independent",
            "report_url": f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_44", "verdict": "ready", "findings": []})
        self.publish(value)
        self.api.status = "finished"
        state = self.controller.tick()
        self.assertEqual(state["status"], "ready", "closed design must not finish an execute objective")
        self.assertEqual(execution.next_step(state)["action"], "execution_preflight")
        self.assertEqual(state["recoveries"], 1)

    def test_resume_requires_persisted_answers_for_a_decision_checkpoint(self):
        self.controller.tick()
        value = receipt(self.store.state, "needs_decision")
        value["closure"].update(structural_sha=SHA, review={"sha": SHA, "reviewer": "independent",
            "report_url": f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_44", "verdict": "blocked",
            "findings": [{"id": "Q6", "kind": "decision", "summary": "Who may create an account?",
                          "owner": "user", "action": "Choose eligibility", "tickets": ["E2-1"]}]})
        self.publish(value)
        self.api.status = "finished"
        state = self.controller.tick()
        self.assertTrue(callable(getattr(execution, "resume_run", None)), "verified resume transition missing")
        with self.assertRaisesRegex(ValueError, "answer"):
            execution.resume_run(state, [])
        answers = [{"id": "Q6", "question": "Who may create an account?", "answer": "Anyone with an email",
                    "source_url": f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_200"}]
        resumed = execution.resume_run(state, answers)
        self.assertEqual(resumed["request"], state["request"])
        self.assertEqual(resumed["attempts"], state["attempts"])
        self.assertEqual(execution.next_step(resumed)["action"], "apply_decisions")
        self.assertEqual(state["status"], "needs_decision", "input state must not mutate")
        self.store.state = resumed
        self.controller.tick()
        forgotten = receipt(self.store.state)
        with self.assertRaisesRegex(ValueError, "unanswered decision"):
            execution.validate_checkpoint(forgotten, self.store.state, 2, SHA)

    def setUp(self):
        self.store, self.api = Store(), API()
        self.controller = execution.Controller(self.api, self.store, CONFIG, now=lambda: 100)

    def publish(self, value, author=99, note_id=7):
        self.api.saved_notes.append({"id": note_id, "body": execution.checkpoint_body(value), "author": {"id": author}})

    def test_lost_post_response_reconciles_without_duplicate_dispatch(self):
        self.api.lost_response = True
        with self.assertRaisesRegex(ValueError, "unknown outcome"):
            self.controller.tick()
        self.assertIsNone(self.store.state["active"]["session_id"])
        self.assertEqual(self.controller.tick()["active"]["session_id"], 1)
        self.assertEqual(len(self.api.starts), 1)
        self.api.sessions = lambda *args: []
        self.controller.tick()
        self.assertEqual(len(self.api.starts), 1)

    def test_concurrent_reservation_loser_cannot_launch(self):
        def lose(*args):
            raise ValueError("competing controller")
        self.store.save = lose
        with self.assertRaisesRegex(ValueError, "competing"):
            self.controller.tick()
        self.assertEqual(self.api.starts, [])

    def test_running_or_approval_required_does_not_spawn_again(self):
        self.controller.tick()
        for status in ("running", "created", "tool_call_approval_required"):
            self.api.status = status
            self.controller.tick()
        self.assertEqual(self.store.state["status"], "needs_decision")
        self.assertIsNotNone(self.store.state["active"])
        self.assertEqual(len(self.api.starts), 1)
        with self.assertRaisesRegex(ValueError, "native session"):
            execution.resume_run(self.store.state, [], self.api.sessions(1, "")[0])
        for status in ("running", "failed"):
            self.api.status = status
            resumed = execution.resume_run(self.store.state, [], self.api.sessions(1, "")[0])
            self.assertEqual(resumed["active"], self.store.state["active"])
            self.assertEqual(resumed["attempts"], self.store.state["attempts"])
        foreign = self.api.sessions(1, "")[0] | {"id": 2}
        with self.assertRaises(ValueError):
            execution.resume_run(self.store.state, [], foreign)

    def test_answer_application_readback_then_review_continues_same_execute_objective(self):
        self.store.state = execution.new_run({**request(), "mode": "execute", "objective": "Fully implement E2"})
        self.controller.tick()
        value = receipt(self.store.state, "needs_decision")
        question = "Who may create an account?"
        value["closure"].update(structural_sha=SHA, review={"sha": SHA, "reviewer": "independent",
            "report_url": f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_44", "verdict": "blocked",
            "findings": [{"id": "Q6", "kind": "decision", "summary": question,
                          "owner": "user", "action": "Choose eligibility", "tickets": ["E2-1"]}]})
        self.publish(value)
        self.api.status = "finished"
        state = self.controller.tick()
        answer = {"id": "Q6", "question": question, "answer": "Anyone with an email",
                  "source_url": f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_200"}
        for change in ({"id": "invented"}, {"question": "Changed question"}, {"source_url": "https://example.com"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                execution.resume_run(state, [answer | change])
        self.store.state = execution.resume_run(state, [answer])
        self.controller.tick()
        self.assertIn('"action":"apply_decisions"', self.api.starts[-1])
        self.assertIn('"answer":"Anyone with an email"', self.api.starts[-1])
        saved = receipt(self.store.state)
        next_sha = "b" * 40
        saved["candidate_sha"] = saved["closure"]["candidate_sha"] = next_sha
        saved["decision_applications"] = [{"answer_sha256": execution.digest(answer), "candidate_sha": next_sha,
            "changed_paths": ["docs/design/onboarding/spec.md"],
            "report_url": f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_201"}]
        for change in ({"answer_sha256": "0" * 64}, {"candidate_sha": SHA}, {"changed_paths": [".gitlab-ci.yml"]}):
            invalid = deepcopy(saved)
            invalid["decision_applications"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                execution.validate_checkpoint(invalid, self.store.state, 2, next_sha)
        self.api.head = lambda branch: next_sha
        def unavailable(*args):
            raise ValueError("artifact readback failed")
        self.api.verify_decision_applications = unavailable
        self.publish(saved, note_id=8)
        with self.assertRaisesRegex(ValueError, "readback"):
            self.controller.tick()
        self.assertEqual(self.store.state["answer_batches"][0]["status"], "pending")
        self.assertEqual(self.store.state["checkpoint"], value)
        verified = []
        self.api.verify_decision_applications = lambda v, s: verified.append(v)
        result = self.controller.tick()
        self.assertEqual(verified, [saved])
        self.assertEqual(result["answer_batches"][0]["status"], "applied")
        self.assertEqual(execution.next_step(result)["action"], "validate")
        self.controller.tick()
        reviewed = receipt(self.store.state)
        reviewed["candidate_sha"] = next_sha
        reviewed["closure"].update(candidate_sha=next_sha, structural_sha=next_sha, handoff_sha=next_sha,
            review={"sha": next_sha, "reviewer": "independent", "verdict": "ready", "findings": [],
                    "report_url": f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_202"})
        self.publish(reviewed, note_id=9)
        result = self.controller.tick()
        self.assertEqual(execution.next_step(result)["action"], "execution_preflight")
        self.assertEqual(result["request"]["objective"], "Fully implement E2")
        self.assertEqual(len(result["attempts"]), 3)

    def test_failed_and_finished_without_receipt_recover_but_never_complete(self):
        self.controller.tick()
        self.api.status = "failed"
        self.assertEqual(self.controller.tick()["status"], "ready")
        self.controller.tick()
        self.assertIn('"reconcile_session_id":1', self.api.starts[-1])
        self.api.status = "finished"  # Green completion alone does not establish work completion.
        self.assertEqual(self.controller.tick()["status"], "blocked")
        self.assertEqual(self.store.state["recoveries"], 1)
        self.controller.tick()
        self.assertEqual(len(self.api.starts), 2)

    def test_verified_checkpoint_survives_failed_session_and_drives_continuation(self):
        self.controller.tick()
        self.publish(receipt(self.store.state))
        self.api.status = "failed"  # Lost final router tail after a durable checkpoint.
        result = self.controller.tick()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["recoveries"], 0)
        self.assertEqual(result["checkpoint_note_id"], 7)
        self.controller.tick()
        self.assertIn('"checkpoint_note_id":7', self.api.starts[-1])
        self.assertEqual(len(self.api.starts), 2)

    def test_identity_stale_unknown_and_ambiguous_checkpoints_fail_closed(self):
        self.controller.tick()
        value = receipt(self.store.state)
        for field, bad in (("session_id", 20), ("outcome", "ready"), ("candidate_sha", "b" * 40),
                           ("previous_checkpoint_sha256", "bad"), ("request_sha256", "bad"), ("outcome", "complete")):
            changed = deepcopy(value)
            changed[field] = bad
            with self.subTest(field=field, value=bad), self.assertRaises(ValueError):
                execution.validate_checkpoint(changed, self.store.state, 1, SHA)
        self.publish(value)
        self.publish(value, note_id=8)
        self.api.status = "finished"
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.controller.tick()
        self.assertEqual(len(self.api.starts), 1)

    def test_same_sha_review_is_required_for_design_complete(self):
        self.controller.tick()
        value = receipt(self.store.state, "complete")
        value["closure"].update(structural_sha=SHA, handoff_sha=SHA, review={"sha": SHA, "reviewer": "independent subsession",
            "report_url": f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_44", "verdict": "ready", "findings": []})
        self.publish(value)
        self.api.status = "finished"
        self.assertEqual(self.controller.tick()["status"], "complete")
        self.controller.tick()
        self.assertEqual(len(self.api.starts), 1)

    def test_history_and_design_only_scope_cannot_reset_or_implement(self):
        self.controller.tick()
        prior = receipt(self.store.state)
        prior["closure"]["research_attempts"] = ["R1"]
        self.store.state.update(checkpoint=prior, checkpoint_sha256=execution.digest(prior))
        changed = receipt(self.store.state)
        with self.assertRaisesRegex(ValueError, "history"):
            execution.validate_checkpoint(changed, self.store.state, 1, SHA)
        changed["closure"]["research_attempts"] = ["R1"]
        prior["closure"]["reconciliations"] = [{"reservation": {"kind": "review", "base_sha": SHA, "session_id": 42},
            "observation": {"session_id": 42, "project_id": execution.PROJECT_ID, "status": "failed", "observed_head": SHA},
            "report_url": f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_200"}]
        self.store.state["checkpoint_sha256"] = execution.digest(prior)
        changed["previous_checkpoint_sha256"] = self.store.state["checkpoint_sha256"]
        with self.assertRaisesRegex(ValueError, "reconciliation history"):
            execution.validate_checkpoint(changed, self.store.state, 1, SHA)
        changed["closure"]["reconciliations"] = deepcopy(prior["closure"]["reconciliations"])
        changed["journal"] = {"fake": "implementation"}
        with self.assertRaisesRegex(ValueError, "execution before"):
            execution.validate_checkpoint(changed, self.store.state, 1, SHA)

    def test_budgets_never_reset_and_unauthorized_authors_are_ignored(self):
        self.store.state["request"]["max_sessions"] = 1
        self.store.state["request_sha256"] = execution.digest(self.store.state["request"])
        self.controller.tick()
        self.publish(receipt(self.store.state, "complete"), author=1234)
        self.api.status = "failed"
        self.controller.tick()
        self.assertEqual(self.controller.tick()["status"], "blocked")
        self.assertEqual(len(self.api.starts), 1)

    def test_completed_design_requires_explicit_execution_authorization_without_budget_reset(self):
        self.controller.tick()
        value = receipt(self.store.state, "complete")
        value["closure"].update(structural_sha=SHA, handoff_sha=SHA, review={"sha": SHA, "reviewer": "independent",
            "report_url": f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_44", "verdict": "ready", "findings": []})
        self.publish(value)
        self.api.status = "finished"
        old = self.controller.tick()
        authorized = {**request(), "mode": "execute", "run_id": "e2-execution"}
        upgraded = transport.authorize_execution(old, authorized, CONFIG)
        self.assertEqual(upgraded["attempts"], old["attempts"])
        self.assertEqual(upgraded["checkpoint"], old["checkpoint"])
        self.assertEqual(upgraded["request"]["mode"], "execute")
        for changed in ({**old, "status": "running"}, {**old, "request": authorized}):
            with self.assertRaises(ValueError):
                transport.authorize_execution(changed, authorized, CONFIG)

    def test_repeated_checkpoints_without_progress_stop_spending(self):
        for attempt in range(3):
            self.controller.tick()
            self.publish(receipt(self.store.state), note_id=7 + attempt)
            self.api.status = "finished"
            self.controller.tick()
        self.assertEqual(self.store.state["status"], "blocked")
        self.assertEqual(self.store.state["no_progress"], 2)
        self.controller.tick()
        self.assertEqual(len(self.api.starts), 3)

    def test_execution_journal_replay_and_active_claim_survive_slices(self):
        from test_ctx_development_repairs import repair_request
        import ctx_development as dev
        self.store.state["request"]["mode"] = "execute"
        self.store.state["request_sha256"] = execution.digest(self.store.state["request"])
        self.controller.tick()
        value = receipt(self.store.state)
        value["closure"].update(structural_sha=SHA, handoff_sha=SHA, review={"sha": SHA, "reviewer": "independent",
            "report_url": f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_44", "verdict": "ready", "findings": []})
        scoped = repair_request()
        scoped.update(project_path=execution.PROJECT_PATH, run_id="e2-test",
                      session_url=f"https://gitlab.com/{execution.PROJECT_PATH}/-/automate/agent-sessions/1")
        scoped["epics"][0]["design_sha"] = SHA
        value["journal"] = dev.claim(dev.new_run(scoped), "E2-1")
        self.publish(value)
        self.api.status = "finished"
        self.controller.tick()
        self.controller.tick()
        changed = receipt(self.store.state)
        changed.update(closure=value["closure"], journal=value["journal"])
        execution.validate_checkpoint(changed, self.store.state, 2, SHA)
        changed["journal"] = dev.claim(dev.new_run(scoped), "E2-2")
        with self.assertRaisesRegex(ValueError, "active claim"):
            execution.validate_checkpoint(changed, self.store.state, 2, SHA)
        changed["journal"] = dev.new_run(scoped)
        with self.assertRaisesRegex(ValueError, "claim budget"):
            execution.validate_checkpoint(changed, self.store.state, 2, SHA)

    def test_execution_answer_binds_ticket_candidate_not_unrelated_epic_head(self):
        from test_ctx_development_repairs import repair_request
        from test_ctx_development import receipt as worker_receipt
        import ctx_development as dev
        self.store.state = execution.new_run({**request(), "mode": "execute"})
        self.controller.tick()
        prior = receipt(self.store.state, "needs_decision")
        prior["closure"].update(structural_sha=SHA, handoff_sha=SHA, review={"sha": SHA, "reviewer": "independent",
            "report_url": f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_44", "verdict": "ready", "findings": []})
        scoped = repair_request()
        scoped.update(project_path=execution.PROJECT_PATH, run_id="e2-test",
                      session_url=f"https://gitlab.com/{execution.PROJECT_PATH}/-/automate/agent-sessions/1")
        scoped["epics"][0]["design_sha"] = SHA
        run = dev.new_run(scoped)
        for _ in range(3):
            run = dev.claim(run, "E2-1")
            run = dev.record(run, worker_receipt(run,
                report_url=f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_{run['actions']}"))
        run = dev.claim(run, "E2-1")
        answer = {"id": "Q6", "question": "Who?", "answer": "Anyone",
                  "source_url": f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_200"}
        blocked = worker_receipt(run, response="blocked", reason="Question", blocker_kind="decision",
            decisions=[{"id": answer["id"], "question": answer["question"]}], report_url=answer["source_url"])
        prior["journal"] = dev.record(run, blocked)
        self.store.state.update(active=None, status="needs_decision", checkpoint=prior,
                                checkpoint_sha256=execution.digest(prior), checkpoint_note_id=7)
        self.store.state = execution.resume_run(self.store.state, [answer])
        self.controller.tick()
        saved = receipt(self.store.state)
        saved["closure"] = prior["closure"]
        report = f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_201"
        application = {"answers": [answer], "candidate_sha": "d" * 40, "report_url": report,
            "report_readback": True, "changed_paths": ["docs/design/onboarding/spec.md"],
            "affected_targets": ["E2-1"], "acceptance_manifest_sha256": dev.scoped_manifest(prior["journal"], "E2-1")[1]}
        saved["journal"] = dev.resume_decision(prior["journal"], "E2-1", application)
        saved["decision_applications"] = [{"answer_sha256": execution.digest(answer), "candidate_sha": "d" * 40,
            "changed_paths": application["changed_paths"], "report_url": report}]
        execution.validate_checkpoint(saved, self.store.state, 2, SHA)
        self.assertEqual(execution.application_base(saved, self.store.state, saved["decision_applications"][0]),
                         prior["journal"]["nodes"]["E2-1"]["candidate_sha"])
        invalid = deepcopy(saved)
        invalid["decision_applications"][0]["candidate_sha"] = SHA
        with self.assertRaises(ValueError):
            execution.validate_checkpoint(invalid, self.store.state, 2, SHA)

    def test_admission_and_ci_job_boundaries(self):
        self.assertTrue(admission(100, 699)["delegate"])
        self.assertFalse(admission(100, 700)["delegate"])
        with self.assertRaises(ValueError):
            admission(100, 99)
        import yaml
        root = Path(__file__).resolve().parents[2]
        job = yaml.safe_load((root / ".gitlab/ci/controller.yml").read_text())["ctx:execution-controller"]
        self.assertEqual(job["resource_group"], "ctx-execution-controller")
        self.assertEqual(job["environment"]["name"], "ctx-controller")
        self.assertFalse(job["interruptible"])
        rule = job["rules"][0]["if"]
        for required in ('CI_DEFAULT_BRANCH', 'CI_COMMIT_REF_PROTECTED', '"schedule"', '"web"'):
            self.assertIn(required, rule)
        self.assertEqual(len(job["rules"]), 1)


class TransportTests(unittest.TestCase):
    def test_decision_artifacts_require_actual_diff_files_and_report_readback(self):
        api = transport.GitLab("test-only")
        path, new = "docs/design/onboarding/spec.md", "b" * 40
        raw = b"# Onboarding\nAnyone with an email may create an account.\n"
        comparison = {"compare_timeout": False, "diffs": [{"new_path": path}]}
        file = {"file_path": path, "commit_id": new, "encoding": "base64",
                "content": base64.b64encode(raw).decode(), "content_sha256": transport.hashlib_sha(raw)}
        note = {"id": 201, "body": new + " " + path}
        calls = []
        def rest(method, url, data=None):
            calls.append((method, url))
            return deepcopy(comparison if "/compare?" in url else file if "/files/" in url else note)
        api.rest = rest
        trees = {SHA: {path: ("a" * 40, "blob", "100644")},
                 new: {path: ("b" * 40, "blob", "100644")}}
        api.tree_files = lambda ref: deepcopy(trees[ref])
        checkpoint = {"candidate_sha": new, "decision_applications": [{"changed_paths": [path], "candidate_sha": new,
            "report_url": f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_201"}]}
        state = {"checkpoint": {"candidate_sha": SHA}, "request": request()}
        api.verify_decision_applications(checkpoint, state)
        self.assertTrue(all(method == "GET" for method, url in calls))
        self.assertIn("straight=true", calls[0][1])
        for target, key, bad in ((comparison, "compare_timeout", True),
                                 (comparison, "diffs", [{"new_path": ".gitlab-ci.yml"}]),
                                 (comparison, "diffs", [{"new_path": path, "too_large": True}]),
                                 (file, "commit_id", SHA), (file, "content_sha256", "0" * 64),
                                 (note, "body", "saved")):
            old = target[key]
            target[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                api.verify_decision_applications(checkpoint, state)
            target[key] = old
        trees[new][".gitlab-ci.yml"] = ("c" * 40, "blob", "100644")
        with self.assertRaisesRegex(ValueError, "tree"):
            api.verify_decision_applications(checkpoint, state)

    def test_repository_tree_read_is_complete_and_rejects_repeated_pages(self):
        api = transport.GitLab("test-only")
        pages = [([{"path": "docs", "type": "tree", "mode": "040000", "id": SHA},
                   {"path": "docs/spec.md", "type": "blob", "mode": "100644", "id": SHA}], {"X-Next-Page": "2"}),
                 ([{"path": "app.py", "type": "blob", "mode": "100644", "id": "b" * 40}], {})]
        calls = []
        api.request = lambda *args: (calls.append(args) or pages[len(calls) - 1])
        self.assertEqual(set(api.tree_files(SHA)), {"docs/spec.md", "app.py"})
        self.assertIn("page=2", calls[-1][1])
        api.request = lambda *args: pages[0]
        with self.assertRaises(ValueError):
            api.tree_files(SHA)

    def test_answer_provenance_is_read_not_inferred_from_a_worker_note(self):
        api = transport.GitLab("test-only")
        answer = {"id": "Q6", "question": "Who?", "answer": "Anyone",
                  "source_url": f"https://gitlab.com/{execution.PROJECT_PATH}/-/issues/10#note_200"}
        note = {"id": 200, "system": False, "author": {"id": 7}, "body": "Q6 Who? Anyone"}
        api.note = lambda source, note_id: note
        api.verify_answers([answer], 10, [99])
        for key, bad in (("system", True), ("author", {"id": 99}), ("body", "Q6 acknowledged")):
            old = note[key]
            note[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                api.verify_answers([answer], 10, [99])
            note[key] = old

    def test_state_compare_and_swap_and_full_readback(self):
        class Repo:
            stored = None
            revision = 0

            def rest(self, method, path, body=None):
                import base64
                if method == "GET":
                    raw = self.stored.encode()
                    return {"encoding": "base64", "content": base64.b64encode(raw).decode(),
                            "last_commit_id": f"{self.revision:040x}", "content_sha256": transport.hashlib_sha(raw)}
                if method == "POST" and self.stored is not None:
                    raise ValueError("exists")
                if method == "PUT" and body["last_commit_id"] != f"{self.revision:040x}":
                    raise ValueError("stale write")
                self.revision += 1
                self.stored = body["content"]

        store = transport.GitLabStore(Repo(), 2)
        state = execution.new_run(request())
        revision = store.save(state, None)
        self.assertEqual(store.load()[0], state)
        self.assertEqual(store.save(state, revision), revision)  # No empty GitLab commit on unchanged polls.
        self.assertEqual(store.api.revision, 1)
        changed = {**state, "summary": "changed"}
        store.save(changed, revision)
        with self.assertRaisesRegex(ValueError, "stale"):
            store.save(state, revision)
        with self.assertRaisesRegex(ValueError, "exists"):
            store.save(state, None)

    def test_pin_catalog_source_scope_and_privileges_without_default_all(self):
        api = transport.GitLab("test-only-not-a-secret")
        calls = []
        api.request = lambda *args: (calls.append(args) or {"id": 1}, {})
        api.start("scoped goal", request(), CONFIG)
        body = calls[0][2]
        self.assertEqual(body["ai_catalog_item_consumer_id"], 77)
        self.assertEqual(body["ai_catalog_item_version_id"], 88)
        self.assertEqual(body["source_branch"], "ctx/epic-i2")
        self.assertEqual(body["agent_privileges"], [1, 2, 3, 4, 5])
        self.assertEqual(body["pre_approved_agent_privileges"], [])
        self.assertNotIn("test-only", json.dumps(body))
        for key, bad in (("enabled", False), ("consumer_id", None), ("agent_privileges", [6]),
                         ("pre_approved_agent_privileges", [6])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                transport.validate_config({**CONFIG, key: bad})

    def test_native_status_query_uses_pagination_and_exact_attempt_marker(self):
        api = transport.GitLab("test-only")
        page = {"nodes": [{"id": "gid://gitlab/Ai::DuoWorkflows::Workflow/42", "projectId": "gid://gitlab/Project/87329027",
                            "goal": "marker\nscoped request", "statusName": "FAILED"}],
                "pageInfo": {"hasNextPage": False, "endCursor": None}}
        api.request = lambda *args, **kwargs: ({"data": {"duoWorkflowWorkflows": page}}, {})
        self.assertEqual(api.sessions(None, "marker")[0]["status"], "failed")
        self.assertEqual(api.sessions(None, "not-marker"), [])


if __name__ == "__main__":
    unittest.main()
