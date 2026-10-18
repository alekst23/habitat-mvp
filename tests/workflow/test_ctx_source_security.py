"""Failure-oriented source scanner tests; scanner processes use synthetic fixtures."""
import hashlib
import io
import json
import tarfile
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import ctx_source_security as build
import ctx_security_tools as installer

SHA = "a" * 40
SECRET = "private-token-value-must-never-be-retained"
ENV = {"CTX_SOURCE_SHA": SHA, "CI_COMMIT_SHA": SHA, "CI_PROJECT_ID": "42", "CI_PIPELINE_ID": "81",
       "CI_JOB_ID": "123", "CI_PROJECT_URL": "https://gitlab.com/example/showcase",
       "CI_JOB_URL": "https://gitlab.com/example/showcase/-/jobs/123"}


class FakeTools:
    def __init__(self):
        self.calls = []
        self.codes = {}
        self.bandit = {"errors": [], "metrics": {"_totals": {"loc": 42}}, "results": []}
        self.dependencies = {"dependencies": [{"name": "example", "version": "1.0", "vulns": []}]}
        self.secrets = {"SchemaVersion": 2, "ArtifactType": "filesystem", "ArtifactName": "."}

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        tool = argv[0]
        stdout = ""
        if argv[-1] == "--version":
            stdout = tool + " " + build.VERSIONS[tool]
        elif tool == "bandit":
            Path(argv[argv.index("-o") + 1]).write_text(json.dumps(self.bandit))
        elif tool == "pip-audit":
            Path(argv[argv.index("--output") + 1]).write_text(json.dumps(self.dependencies))
        elif tool == "trivy":
            Path(argv[argv.index("--output") + 1]).write_text(json.dumps(self.secrets))
        return subprocess.CompletedProcess(argv, self.codes.get(tool, 0), stdout=stdout, stderr=SECRET)


class SourceSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / "backend/aicl").mkdir(parents=True)
        (self.root / "backend/aicl/app.py").write_text("answer = 42\n")
        (self.root / "backend/requirements.lock").write_text("example==1.0 --hash=sha256:" + "c" * 64 + "\n")
        self.tools = FakeTools()
        self.patcher = patch.object(build.subprocess, "run", side_effect=self.tools)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_real_ci_identity_and_backend_required_before_any_tool(self):
        with self.assertRaisesRegex(build.Blocked, "CI commit"):
            build.source_security(self.root, {**ENV, "CI_COMMIT_SHA": "b" * 40})
        (self.root / "backend/requirements.lock").unlink()
        with self.assertRaisesRegex(build.Blocked, "requirements.lock"):
            build.source_security(self.root, ENV)
        self.assertEqual(self.tools.calls, [])

    def test_clean_source_scans_produce_native_reports_and_passed_checks(self):
        result = build.source_security(self.root, {**ENV, "TRIVY_IGNORE_UNFIXED": "true", "TRIVY_SKIP_FILES": "*"})
        self.assertEqual(result["checks"], {key: "passed" for key in ("source", "dependency", "secrets")})
        self.assertEqual(result["blocking_findings"], 0)
        reports = list((self.root / ".ctx/security").glob("gl-*-report.json"))
        self.assertEqual(len(reports), 3)
        for path in reports:
            report = json.loads(path.read_text())
            self.assertEqual(report["scan"]["status"], "success")
            self.assertTrue(report["scan"]["scanner"]["version"])
        bandit = next(argv for argv, _ in self.tools.calls if "--ignore-nosec" in argv)
        self.assertEqual(bandit[bandit.index("-r") + 1], "backend/aicl")
        self.assertIn("--ini", bandit)
        self.assertIn("-c", bandit)
        for argv, kwargs in self.tools.calls:
            self.assertFalse(kwargs["shell"])
            self.assertTrue(kwargs["capture_output"])
            self.assertNotIn("TRIVY_IGNORE_UNFIXED", kwargs["env"])
            self.assertNotIn("TRIVY_SKIP_FILES", kwargs["env"])

    def test_medium_sast_finding_blocks_and_publishes_location_without_code(self):
        self.tools.bandit["results"] = [{"filename": "backend/app.py", "line_number": 1,
                                         "test_id": "B608", "issue_severity": "MEDIUM", "code": SECRET}]
        self.tools.codes["bandit"] = 1
        # Tool version checks have exit=0; findings exit=1 only on the scan itself.
        original = self.tools.__call__
        def execute(argv, **kwargs):
            result = original(argv, **kwargs)
            if argv[-1] == "--version":
                result.returncode = 0
            return result
        self.patcher.stop()
        with patch.object(build.subprocess, "run", side_effect=execute):
            with self.assertRaisesRegex(build.Blocked, "blocking security findings"):
                build.source_security(self.root, ENV)
        text = (self.root / ".ctx/security/gl-sast-report.json").read_text()
        self.assertNotIn(SECRET, text)
        self.assertEqual(json.loads(text)["vulnerabilities"][0]["location"]["file"], "backend/app.py")

    def test_scanner_error_cannot_masquerade_as_no_findings(self):
        self.tools.bandit["errors"] = [{"reason": SECRET}]
        with self.assertRaisesRegex(build.Blocked, "source scanner errors") as caught:
            build.source_security(self.root, ENV)
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertFalse((self.root / ".ctx/security/gl-sast-report.json").exists())

    def test_dependency_skipped_or_zero_packages_blocks(self):
        for dependencies in ([], [{"name": "unknown", "skip_reason": SECRET}]):
            with self.subTest(dependencies=dependencies):
                self.tools.dependencies = {"dependencies": dependencies}
                with self.assertRaises(build.Blocked):
                    build.source_security(self.root, ENV)

    def test_secret_match_never_survives_normalization(self):
        self.tools.secrets["Results"] = [{"Target": "backend/app.py", "Secrets": [{
            "RuleID": "generic-api-key", "Severity": "HIGH", "StartLine": 1, "Match": SECRET, "Code": SECRET}]}]
        with self.assertRaisesRegex(build.Blocked, "blocking security findings"):
            build.source_security(self.root, ENV)
        text = (self.root / ".ctx/security/gl-secret-detection-report.json").read_text()
        self.assertNotIn(SECRET, text)
        self.assertEqual(json.loads(text)["vulnerabilities"][0]["location"]["commit"]["sha"], SHA)


    def test_tool_failure_and_version_mismatch_clear_stale_reports_and_never_pass(self):
        previous = build.write_json(self.root, ".ctx/security/gl-sast-report.json", {"stale": True})
        original = self.tools.__call__

        def failing(argv, **kwargs):
            result = original(argv, **kwargs)
            if argv[-1] != "--version":
                result.returncode = 1  # no findings: failure, not a clean scan
            return result

        self.patcher.stop()
        with patch.object(build.subprocess, "run", side_effect=failing):
            with self.assertRaisesRegex(build.Blocked, "failed without usable findings"):
                build.source_security(self.root, ENV)
        self.assertFalse(previous.exists())
        with patch.object(build.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, stdout="unknown version", stderr=SECRET)):
            with self.assertRaisesRegex(build.Blocked, "version differs"):
                build.source_security(self.root, ENV)

    def test_trivy_installer_verifies_checksum_and_rejects_archive_symlinks(self):
        def archive(kind):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w:gz") as output:
                info = tarfile.TarInfo("trivy")
                info.type = kind
                if kind == tarfile.SYMTYPE:
                    info.linkname = "outside"
                    output.addfile(info)
                else:
                    info.size = 4
                    output.addfile(info, io.BytesIO(b"tool"))
            return stream.getvalue()

        data = archive(tarfile.REGTYPE)
        digest = hashlib.sha256(data).hexdigest()
        self.assertEqual(installer.binary(data, "trivy", "trivy.tar.gz", digest), b"tool")
        with self.assertRaisesRegex(ValueError, "checksum"):
            installer.binary(data + b"tampered", "trivy", "trivy.tar.gz", digest)
        data = archive(tarfile.SYMTYPE)
        with self.assertRaisesRegex(ValueError, "archive member"):
            installer.binary(data, "trivy", "trivy.tar.gz", hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    unittest.main()
