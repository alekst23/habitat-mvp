"""The verify adapter must earn evidence from real pytest output or fail closed.

Fixture projects are tiny throwaway git repositories; no application code exists
in this repository, and none is added to make these checks pass.
"""

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
PASSING = "def test_ok(): assert True\n"


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

    def commit(self, name, files=None):
        """Commit a fixture; files maps backend/ paths to source, None means no backend."""
        self.project = Path(self.temp.name) / name
        self.project.mkdir()
        git(self.project, "init", "-q")
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
               "CTX_SOURCE_SHA": sha, "CI_JOB_URL": JOB_URL, **extra}
        env = {k: v for k, v in env.items() if v is not None}
        return subprocess.run([sys.executable, str(ADAPTER)], cwd=self.project, env=env,
                              capture_output=True, text=True, timeout=120)

    def test_real_pytest_run_writes_exact_evidence(self):
        sha = self.commit("real", {"probe.py": "VALUE = 2\n", "tests/test_ok.py": """
            import pytest
            from probe import VALUE  # resolved through PYTHONPATH=backend
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
        (self.project / "untracked.py").write_text("x = 1\n")
        done = self.run_adapter(sha)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("dirty", done.stdout + done.stderr)
        self.assertFalse(self.output.exists())

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


if __name__ == "__main__":
    unittest.main()
