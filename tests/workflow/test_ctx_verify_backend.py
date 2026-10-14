"""The verify adapter must earn evidence from real pytest output or fail closed.

Fixture projects are tiny throwaway git repositories; no application code exists
in this repository, and none is added to make these checks pass.
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "scripts/ctx_verify_backend.py"
spec = importlib.util.spec_from_file_location("ctx_workflow", ROOT / "scripts/ctx_workflow.py")
ctx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctx)
JOB_URL = "https://gitlab.example.com/group/project/-/jobs/123"
PASSING = "import pytest\n@pytest.mark.ac('E1-1.AC1', code='README.md')\ndef test_ok(): assert True\n"
MANIFEST_PATH = "docs/plan/E1/acceptance.json"
BASE_CRITERIA = [
    {"id": "E1-1.AC1", "statement": "Backend rule holds.", "ui": False, "methods": ["test"]},
    {"id": "E1-1.AC2", "statement": "Owner sees the result.", "ui": True, "methods": ["test", "browser"]},
    {"id": "E1-1.AC3", "statement": "Owner can navigate.", "ui": True, "methods": ["browser"]},
    {"id": "E1-2.AC1", "statement": "Other ticket rule holds.", "ui": False, "methods": ["test"]},
]
spec = importlib.util.spec_from_file_location("ctx_acceptance", ROOT / "scripts/ctx_acceptance.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


def git(cwd, *args):
    return subprocess.check_output(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=cwd, text=True).strip()


class VerifyAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ctx-verify-")
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "out/verify.json"
        self.output.parent.mkdir()
        self.project = None

    def commit(self, name, files=None, criteria=BASE_CRITERIA):
        """Commit a fixture; files maps backend/ paths to source, None means no backend."""
        self.project = Path(self.temp.name) / name
        self.project.mkdir()
        git(self.project, "init", "-q")
        manifest = self.project / MANIFEST_PATH
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"version": 1, "epic": "E1", "criteria": criteria}, indent=1) + "\n")
        (self.project / ".gitignore").write_text(".ctx/\n")
        for filename, source in (files or {}).items():
            path = self.project / "backend" / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(source))
        (self.project / "README.md").write_text("fixture\n")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", "fixture")
        return git(self.project, "rev-parse", "HEAD")

    def run_adapter(self, sha, **extra):
        env = {"PATH": os.environ["PATH"], "HOME": self.temp.name, "CTX_OUTPUT": str(self.output),
               "CTX_SOURCE_SHA": sha, "CI_JOB_URL": JOB_URL, "CI_PROJECT_ID": "42",
               "CI_PIPELINE_ID": "7", "CTX_AC_MANIFEST": MANIFEST_PATH, "CTX_AC_SCOPE": "E1-1", **extra}
        env = {k: v for k, v in env.items() if v is not None}
        return subprocess.run([sys.executable, str(ADAPTER)], cwd=self.project, env=env,
                              capture_output=True, text=True, timeout=120)

    def test_real_pytest_run_writes_exact_evidence(self):
        sha = self.commit("real", {"probe.py": "VALUE = 2\n", "tests/test_ok.py": """
            import pytest
            from probe import VALUE  # resolved through PYTHONPATH=backend
            @pytest.mark.ac("E1-1.AC1", "E1-1.AC2", "E1-1.AC3", code="backend/probe.py:VALUE")
            def test_one(): assert VALUE == 2
            @pytest.mark.parametrize("n", [1, 2])
            def test_many(n): assert n > 0
            """})
        done = self.run_adapter(sha)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        evidence = json.loads(self.output.read_text())
        self.assertEqual(evidence["tests_total"], 3)  # counted from pytest's JUnit output
        self.assertEqual(evidence["report_url"], JOB_URL)
        ctx.validate_evidence("verify", evidence, {"source_sha": sha}, {})
        self.assertEqual(git(self.project, "status", "--porcelain", "--untracked-files=normal"), "")

    def test_acceptance_writer_maps_real_junit_results_to_validated_evidence(self):
        sha = self.commit("writer", {"tests/test_rules.py": """
            import pytest
            @pytest.mark.ac("E1-1.AC1", "E1-1.AC2", code="backend/rules.py:apply")
            def test_rule(): assert True
            @pytest.mark.ac("E1-1.AC2", code="backend/ui.py:navigate")
            @pytest.mark.parametrize("n", [1, 2])
            def test_screen_data(n): assert n
            def test_unmapped(): assert True
            @pytest.mark.ac("E1-1.AC3", code="backend/ui.py:navigate")
            def test_navigation_data(): assert True
            @pytest.mark.ac("E1-2.AC1", code="backend/rules.py:apply")
            def test_other_ticket(): assert True
            """, "rules.py": "def apply(): pass\n", "ui.py": "def navigate(): pass\n"})
        done = self.run_adapter(sha)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        report = json.loads((self.project / ".ctx/acceptance.json").read_text())
        manifest_bytes = (self.project / MANIFEST_PATH).read_bytes()
        self.assertEqual({k: report[k] for k in ("version", "project_id", "source_sha", "pipeline_id", "scope")},
                         {"version": 1, "project_id": "42", "source_sha": sha, "pipeline_id": "7", "scope": "E1-1"})
        self.assertEqual(report["manifest_sha256"], hashlib.sha256(manifest_bytes).hexdigest())
        rows = {row["id"]: row for row in report["criteria"]}
        self.assertEqual(set(rows), {"E1-1.AC1", "E1-1.AC2", "E1-1.AC3"})  # exact scope, no E1-2
        ac1, ac2, ac3 = rows["E1-1.AC1"], rows["E1-1.AC2"], rows["E1-1.AC3"]
        self.assertEqual(ac1["status"], "passed")
        self.assertEqual(ac1["code"], "backend/rules.py:apply")
        self.assertEqual(ac1["evidence"]["test"]["test_ids"], ["backend/tests/test_rules.py::test_rule"])
        self.assertEqual(ac1["evidence"]["test"]["url"], JOB_URL)
        self.assertEqual(ac2["evidence"]["test"]["test_ids"], [  # collected, not declared: 1 + 2 parametrized
            "backend/tests/test_rules.py::test_rule", "backend/tests/test_rules.py::test_screen_data[1]",
            "backend/tests/test_rules.py::test_screen_data[2]"])
        # Browser-required rows stay pending (browser-only rows carry no test evidence) until browser CI proves them.
        self.assertEqual((ac2["status"], ac3["status"], ac3["evidence"]), ("pending-browser",) * 2 + ({},))
        self.assertEqual(ac3["code"], "backend/ui.py:navigate")
        self.assertEqual(ac2["code"], "backend/rules.py:apply, backend/ui.py:navigate")
        # The unchanged validator accepts it once the independent browser producer supplies UI evidence.
        manifest = json.loads(manifest_bytes)
        identity = {k: report[k] for k in ("project_id", "source_sha", "pipeline_id", "scope")}
        browser = {"version": 1, **identity, "manifest_sha256": report["manifest_sha256"], "criteria": [
            {"id": cid, "evidence": {"browser": {"status": "passed", "test_ids": ["journey"], "url": JOB_URL}}}
            for cid in ("E1-1.AC2", "E1-1.AC3")]}
        self.assertEqual(acceptance.validate_acceptance(
            manifest, report["manifest_sha256"], report, identity, browser), 3)
        with self.assertRaises(acceptance.Invalid):  # without browser evidence it cannot pass
            acceptance.validate_acceptance(manifest, report["manifest_sha256"], report, identity, None)

    def test_acceptance_writer_fails_closed_without_evidence(self):
        marked = lambda *ids, body="pass", code="'README.md'": (  # noqa: E731
            "import pytest\n@pytest.mark.ac(%s, code=%s)\ndef test_x():\n    %s\n"
            % (", ".join(map(repr, ids)), code, body))
        inspection = [{"id": "E1-1.AC1", "statement": "Doc is accurate.", "ui": False,
                       "methods": ["inspection"], "inspection_reason": "documentation only"}]
        cases = {
            "unmapped-ac": ({"tests/test_x.py": marked("E1-1.AC2")}, {}, BASE_CRITERIA, "no passing test mapped"),
            "failing-mapped-test": ({"tests/test_x.py": marked("E1-1.AC1", body="assert False")}, {},
                                    BASE_CRITERIA, "did not pass"),
            "unknown-ac-id": ({"tests/test_x.py": marked("E1-1.AC1", "E1-9.AC9")}, {},
                              BASE_CRITERIA, "unknown AC"),
            "epic-scope-lacks-evidence": ({"tests/test_x.py": marked("E1-1.AC1", "E1-1.AC2")},
                                          {"CTX_AC_SCOPE": "E1"}, BASE_CRITERIA, "no passing test mapped"),
            "missing-scope": ({"tests/test_x.py": PASSING}, {"CTX_AC_SCOPE": None}, BASE_CRITERIA, "CTX_AC_SCOPE"),
            "missing-manifest-var": ({"tests/test_x.py": PASSING}, {"CTX_AC_MANIFEST": None},
                                     BASE_CRITERIA, "CTX_AC_MANIFEST"),
            "manifest-not-found": ({"tests/test_x.py": PASSING}, {"CTX_AC_MANIFEST": "nope.json"},
                                   BASE_CRITERIA, "manifest"),
            "scope-outside-manifest": ({"tests/test_x.py": PASSING}, {"CTX_AC_SCOPE": "E2-1"},
                                       BASE_CRITERIA, "scope"),
            "ac-marker-without-code": ({"tests/test_x.py": "import pytest\n@pytest.mark.ac('E1-1.AC1')\ndef test_x(): pass\n"},
                                       {}, BASE_CRITERIA, "invalid ac marker"),
            "untracked-code-reference": ({"tests/test_x.py": marked("E1-1.AC1", code="'backend/missing.py:f'")},
                                         {}, BASE_CRITERIA, "not a tracked repository file"),
            "no-pipeline-id": ({"tests/test_x.py": PASSING}, {"CI_PIPELINE_ID": None}, BASE_CRITERIA, "CI_PIPELINE_ID"),
            "inspection-ac": ({"tests/test_x.py": PASSING}, {}, inspection, "inspection"),
        }
        for label, (files, extra, criteria, reason) in cases.items():
            with self.subTest(label):
                self.output.unlink(missing_ok=True)
                sha = self.commit(label, files, criteria)
                stale = self.project / ".ctx/acceptance.json"
                stale.parent.mkdir()
                stale.write_text("{}")  # ignored by git, must not survive a failed run
                done = self.run_adapter(sha, **extra)
                self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
                self.assertIn(reason, done.stdout + done.stderr)
                self.assertFalse(self.output.exists())
                self.assertFalse(stale.exists(), "failed run must not leave acceptance evidence")

    def test_fail_closed_without_real_passing_tests(self):
        cases = {
            "no-backend": (None, {}, "no collected tests"),
            "backend-without-tests-dir": ({"helper.py": "x = 1\n"}, {}, "no collected tests"),
            "empty-tests-dir": ({"tests/helper.py": "x = 1\n"}, {}, "no collected tests"),
            "failed-test": ({"tests/test_bad.py": "def test_bad(): assert False\n"}, {}, "did not pass"),
            "skipped-test": ({"tests/test_skip.py": "import pytest\n@pytest.mark.skip\ndef test_s(): pass\n"},
                             {}, "did not pass"),
            "no-job-url": ({"tests/test_ok.py": PASSING}, {"CI_JOB_URL": None}, "CI_JOB_URL"),
            "http-job-url": ({"tests/test_ok.py": PASSING}, {"CI_JOB_URL": "http://ci.example.com/jobs/1"}, "CI_JOB_URL"),
        }
        for label, (files, extra, reason) in cases.items():
            with self.subTest(label):
                self.output.unlink(missing_ok=True)
                done = self.run_adapter(self.commit(label, files), **extra)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn(reason, done.stdout + done.stderr)
                self.assertFalse(self.output.exists(), "failed run must not leave evidence")

    def test_wrong_head_and_dirty_checkout_fail_closed(self):
        sha = self.commit("dirty", {"tests/test_ok.py": PASSING})
        self.assertNotEqual(self.run_adapter("0" * 40).returncode, 0)
        self.assertFalse((self.project / ".ctx/acceptance.json").exists())
        (self.project / "untracked.py").write_text("x = 1\n")
        done = self.run_adapter(sha)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("dirty", done.stdout + done.stderr)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.project / ".ctx/acceptance.json").exists())

    def test_command_and_ci_contract(self):
        config = ctx.read_yaml(ROOT / ".gitlab/ctx/commands.yml")
        ctx.validate_commands(config)
        verify = config["commands"]["verify"]
        self.assertEqual(verify["argv"], ["python", "scripts/ctx_verify_backend.py"])
        self.assertLessEqual(verify["timeout_seconds"], 900)
        jobs = ctx.read_yaml(ROOT / ".gitlab/ci/delivery.yml")
        self.assertEqual(jobs["ctx:verify"]["script"], ["python scripts/ctx_workflow.py run verify"])
        self.assertNotIn("services", jobs["ctx:verify"])  # E11 uses SQLite: no database service
        self.assertIs(jobs[".ctx-check"]["allow_failure"], False)
        self.assertNotIn("CTX_APPLICATION_CHECKS", json.dumps(jobs))
        self.assertIn(".ctx/acceptance.json", jobs[".ctx-check"]["artifacts"]["paths"])
        browser = ctx.read_yaml(ROOT / ".gitlab/ci/browser.yml")["ctx:browser"]
        script = browser["script"]
        self.assertEqual(browser["image"], "mcr.microsoft.com/playwright:v1.63.0-noble")
        self.assertIs(browser["allow_failure"], False)
        self.assertEqual(browser["rules"], [{"if": '$CTX_BROWSER_CHECKS == "1"'}])
        self.assertEqual(browser["timeout"], "10 minutes")
        self.assertIn("npm ci", script)
        self.assertIn('test "$(node -p \'require("@playwright/test/package.json").version\')" = "1.63.0"', script)
        # Python + pinned backend dependencies are installed (failing the job on error) before Playwright runs.
        steps = [i for i, line in enumerate(script) if "python3-venv" in line]
        self.assertEqual(len(steps), 1)
        install = [i for i, line in enumerate(script) if "pip install" in line and "backend/requirements.txt" in line]
        playwright = [i for i, line in enumerate(script) if line.startswith("npx --no-install playwright test")]
        path = [i for i, line in enumerate(script) if line.startswith("export PATH=") and ".ctx/venv/bin" in line]
        self.assertTrue(steps[0] < path[0] < install[0] < playwright[0], script)
        self.assertFalse(any("||" in line or "set +e" in line for line in script), "install failure must fail the job")


if __name__ == "__main__":
    unittest.main()
