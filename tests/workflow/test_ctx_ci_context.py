"""Candidate-owned scope, never pipeline-variable-selected acceptance."""
import json
import contextlib
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ctx_ci_context as context
import ctx_acceptance as acceptance


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ctx-ci-context-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q", "-b", "ctx/ticket-i13")
        self.state = {"version": 2, "project_id": "87329027", "epic": "E11",
                      "epic_issue_iid": 11, "source_issue_iid": 11, "next_ticket_number": 3,
                      "tickets": [{"id": "E11-1", "issue_iid": 12},
                                  {"id": "E11-2", "issue_iid": 13}]}
        self.save("docs/plan/E11/state.json", self.state)
        self.save("docs/plan/EPIC-I2/state.json", {"version": 1, "epic": "EPIC-I2"})
        self.save("docs/plan/E11/acceptance.json", {"version": 1, "epic": "E11", "criteria": [
            {"id": "E11-1.AC1", "statement": "foundation", "methods": ["test"], "ui": False},
            {"id": "E11-2.AC1", "statement": "observable creation", "methods": ["browser"], "ui": True}]})
        self.commit()
        self.env = {"CI_PROJECT_ID": "87329027", "CI_COMMIT_BRANCH": "ctx/ticket-i13",
                    "CI_COMMIT_SHA": self.git("rev-parse", "HEAD"), "CI_PIPELINE_ID": "100",
                    "CTX_AC_SCOPE": "E11-1", "CTX_AC_MANIFEST": "wrong.json",
                    "CTX_BROWSER_CHECKS": "0", "CTX_APPLICATION_CHECKS": "0"}

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True,
                                       stderr=subprocess.DEVNULL).strip()

    def save(self, path, data):
        dest = self.root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data))

    def commit(self):
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.com", "-c",
                 "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "fixture")

    def test_ticket_scope_ignores_manual_variables_and_mr_uses_source_not_target(self):
        for env in (self.env, {**self.env, "CI_COMMIT_BRANCH": "",
                              "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "ctx/ticket-i13",
                              "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "ctx/epic-i11"}):
            with self.subTest(env=env):
                result = context.resolve_context(self.root, env)
                self.assertEqual(result["scope"], "E11-2")
                self.assertEqual(result["manifest"], "docs/plan/E11/acceptance.json")
                self.assertTrue(result["browser_required"])

    def test_machine_prepared_context_survives_ticket_merge_and_whole_epic_preparation(self):
        prepared = context.prepare_context(self.root, self.env)
        self.assertEqual(prepared["scope"], "E11-2")
        self.commit()
        self.git("switch", "-qc", "ctx/epic-i11")
        env = {**self.env, "CI_COMMIT_BRANCH": "ctx/epic-i11", "CI_COMMIT_SHA": self.git("rev-parse", "HEAD")}
        self.assertEqual(context.resolve_context(self.root, env)["scope"], "E11-2")
        context.prepare_context(self.root, env, whole_epic=True)
        self.commit()
        env["CI_COMMIT_SHA"] = self.git("rev-parse", "HEAD")
        self.assertEqual(context.resolve_context(self.root, env)["scope"], "E11")

    def test_stale_ambiguous_untracked_and_wrong_project_contexts_fail_closed(self):
        bads = [{**self.env, "CI_PROJECT_ID": "9"},
                {**self.env, "CI_COMMIT_SHA": "a" * 40},
                {**self.env, "CI_COMMIT_BRANCH": "ctx/ticket-i99"}]
        for env in bads:
            with self.subTest(env=env), self.assertRaises(ValueError):
                context.resolve_context(self.root, env)
        # A stale context from another ticket cannot silently narrow the current candidate.
        self.save(context.CONTEXT_PATH, {"version": 1, "project_id": "87329027", "epic": "E11", "scope": "E11-1"})
        with self.assertRaises(ValueError):
            context.resolve_context(self.root, self.env)
        self.commit()
        self.env["CI_COMMIT_SHA"] = self.git("rev-parse", "HEAD")
        with self.assertRaises(ValueError):
            context.resolve_context(self.root, self.env)

    def test_duplicate_ticket_branch_and_partial_default_branch_are_rejected(self):
        self.state["tickets"][0]["branch"] = "ctx/ticket-i13"
        self.save("docs/plan/E11/state.json", self.state)
        self.commit()
        self.env["CI_COMMIT_SHA"] = self.git("rev-parse", "HEAD")
        with self.assertRaises(ValueError):
            context.resolve_context(self.root, self.env)
        self.state["tickets"][0].pop("branch")
        self.save("docs/plan/E11/state.json", self.state)
        self.commit()
        self.env["CI_COMMIT_SHA"] = self.git("rev-parse", "HEAD")
        context.prepare_context(self.root, self.env)
        self.commit()
        env = {**self.env, "CI_COMMIT_BRANCH": "main", "CI_DEFAULT_BRANCH": "main",
               "CI_COMMIT_SHA": self.git("rev-parse", "HEAD")}
        with self.assertRaises(ValueError):
            context.resolve_context(self.root, env)

    def test_browser_applicability_is_not_a_switch_and_never_fabricates_a_pass(self):
        env = {**self.env, "CI_COMMIT_BRANCH": "ctx/ticket-i12"}
        resolved = context.resolve_context(self.root, env)
        with patch.object(context, "resolve_context", return_value=resolved), \
                patch.object(context.subprocess, "run") as run:
            self.assertEqual(context.run_browser(self.root, env), 0)
            run.assert_not_called()
        record = json.loads((self.root / ".ctx/browser/not-applicable.json").read_text())
        self.assertEqual((record["status"], record["scope"]), ("not_applicable", "E11-1"))
        self.assertFalse((self.root / ".ctx/browser/acceptance.json").exists())
        # Disabling the old switch cannot skip a genuinely required UI harness.
        with self.assertRaisesRegex(ValueError, "browser foundation missing"):
            context.run_browser(self.root, self.env)

    def test_browser_requires_hashed_backend_lock_before_running_tools(self):
        resolved = context.resolve_context(self.root, self.env)
        self.save("package-lock.json", {})
        (self.root / "backend").mkdir()
        (self.root / "backend/requirements.txt").write_text("example==1.0\n")
        with patch.object(context, "resolve_context", return_value=resolved), \
                patch.object(context.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "backend/requirements.lock"):
                context.run_browser(self.root, self.env)
            run.assert_not_called()
        (self.root / "backend/requirements.lock").write_text("example==1.0 --hash=sha256:" + "a" * 64 + "\n")
        with patch.object(context, "resolve_context", return_value=resolved), \
                patch.object(context.subprocess, "run", return_value=subprocess.CompletedProcess([], 7)) as run, \
                patch.object(context.subprocess, "check_output", return_value="1.63.0\n"):
            self.assertEqual(context.run_browser(self.root, self.env), 7)
        self.assertEqual(run.call_args_list[0].args[0], [sys.executable, "-m", "pip", "install",
                         "--disable-pip-version-check", "--require-hashes", "-r", "backend/requirements.lock"])
        self.assertTrue(run.call_args_list[0].kwargs["check"])

    def test_default_requires_full_epic_and_manifest_cannot_escape_repository(self):
        self.git("switch", "-qc", "ctx/epic-i11")
        env = {**self.env, "CI_COMMIT_BRANCH": "ctx/epic-i11"}
        context.prepare_context(self.root, env, whole_epic=True)
        self.commit()
        env.update(CI_COMMIT_BRANCH="main", CI_DEFAULT_BRANCH="main", CI_COMMIT_SHA=self.git("rev-parse", "HEAD"))
        self.assertEqual(context.resolve_context(self.root, env)["scope"], "E11")
        manifest = self.root / "docs/plan/E11/acceptance.json"
        manifest.unlink()
        manifest.symlink_to(self.root / "docs/plan/E11/state.json")
        with self.assertRaises(ValueError):
            context.resolve_context(self.root, env)

    def test_mr_hierarchy_and_premerge_whole_epic_gate(self):
        for target in ("main", "ctx/epic-i99", "ctx/ticket-i12"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                context.resolve_context(self.root, {**self.env,
                    "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "ctx/ticket-i13",
                    "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": target})
        context.prepare_context(self.root, self.env)
        self.commit()
        env = {**self.env, "CI_COMMIT_SHA": self.git("rev-parse", "HEAD"),
               "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "ctx/epic-i11",
               "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "main"}
        # Ticket integration evidence is available while the epic remains a draft.
        self.assertEqual(context.resolve_context(self.root, env)["scope"], "E11-2")
        with self.assertRaisesRegex(ValueError, "whole-epic"):
            context.require_whole_epic(self.root, env)
        self.git("switch", "-qc", "ctx/epic-i11")
        context.prepare_context(self.root, env, whole_epic=True)
        self.commit()
        env["CI_COMMIT_SHA"] = self.git("rev-parse", "HEAD")
        self.assertEqual(context.require_whole_epic(self.root, env)["scope"], "E11")

    def test_maintenance_is_proven_by_complete_diff_not_branch_name_or_inherited_scope(self):
        base = self.env["CI_COMMIT_SHA"]
        self.save("scripts/ctx_ci_context.py", {"fixture": "workflow-only change"})
        self.commit()
        env = {**self.env, "CI_COMMIT_SHA": self.git("rev-parse", "HEAD"),
               "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "codex/helper-sync",
               "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "ctx/ticket-i13",
               "CI_MERGE_REQUEST_DIFF_BASE_SHA": base}
        resolved = context.resolve_context(self.root, env)
        self.assertEqual(resolved["mode"], "maintenance")
        self.assertNotIn("scope", resolved)
        self.assertEqual(resolved["changed_paths"], ["scripts/ctx_ci_context.py"])
        # No exemption for a planned application branch or for an unknown base/target.
        planned = {**env, "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "ctx/ticket-i13",
                   "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "ctx/epic-i11"}
        self.assertEqual(context.resolve_context(self.root, planned)["mode"], "application")
        for changes in ({"CI_MERGE_REQUEST_DIFF_BASE_SHA": "0" * 40},
                        {"CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "foreign"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                context.resolve_context(self.root, env | changes)
        self.save("backend/application.py", {"fixture": "application change"})
        self.commit()
        env["CI_COMMIT_SHA"] = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(ValueError, "non-maintenance"):
            context.resolve_context(self.root, env)

    def test_prepare_uses_saved_identity_while_final_resolve_requires_committed_inputs(self):
        self.state["tickets"][1]["status"] = "pending"
        self.save("docs/plan/E11/state.json", self.state)
        self.assertEqual(context.prepare_context(self.root, self.env)["scope"], "E11-2")
        with self.assertRaises(ValueError):
            context.resolve_context(self.root, self.env)
        self.commit()
        self.env["CI_COMMIT_SHA"] = self.git("rev-parse", "HEAD")
        self.assertEqual(context.resolve_context(self.root, self.env)["scope"], "E11-2")

    def test_acceptance_entrypoint_rejects_green_report_for_old_global_ticket(self):
        name = "docs/plan/E11/acceptance.json"
        report = {"version": 1, "project_id": "87329027", "pipeline_id": "100",
                  "source_sha": self.env["CI_COMMIT_SHA"], "scope": "E11-1",
                  "manifest_sha256": hashlib.sha256((self.root / name).read_bytes()).hexdigest(),
                  "criteria": [{"id": "E11-1.AC1", "status": "passed", "code": "fixture.py",
                                "evidence": {"test": {"status": "passed", "test_ids": ["fixture-test"],
                                                      "url": "https://gitlab.com/example/project/-/jobs/1"}}}]}
        self.save(".ctx/acceptance.json", report)
        env = self.env | {"CTX_AC_MANIFEST": name, "CTX_SOURCE_SHA": self.env["CI_COMMIT_SHA"],
                          "CTX_OUTPUT": str(self.root / ".ctx/output.json"),
                          "CI_JOB_URL": "https://gitlab.com/example/project/-/jobs/2"}
        with contextlib.chdir(self.root), patch.dict(os.environ, env, clear=True), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(acceptance.main(), 2)  # Old adapter incorrectly returned 0 here.
        self.assertFalse((self.root / ".ctx/output.json").exists())

    def test_worker_preparation_uses_actual_worktree_not_parent_runner_ci_ref(self):
        runner_env = self.env | {"CI_COMMIT_BRANCH": "main", "CI_COMMIT_SHA": "a" * 40,
                                "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "main"}
        self.assertEqual(context.prepare_context(self.root, runner_env)["scope"], "E11-2")
        with self.assertRaisesRegex(ValueError, "pipeline SHA"):
            context.resolve_context(self.root, runner_env)


if __name__ == "__main__":
    unittest.main()
