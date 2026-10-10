"""Controller transition/transport tests, not evidence of native Duo execution."""
from copy import deepcopy
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
