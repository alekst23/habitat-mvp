from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "ctx_acceptance", Path(__file__).resolve().parents[2] / "scripts/ctx_acceptance.py")
ac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ac)


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.identity = {"project_id": "12", "source_sha": "a" * 40,
                         "pipeline_id": "34", "scope": "E2-1"}
        self.digest = "b" * 64
        self.manifest = {"version": 1, "epic": "E2", "criteria": [
            {"id": "E2-1.AC1", "statement": "Deny dispatch", "ui": False, "methods": ["test"]},
            {"id": "E2-1.AC2", "statement": "Explain denial", "ui": True, "methods": ["browser"]},
        ]}
        check = {"status": "passed", "test_ids": ["budget-denial"], "url": "https://gitlab.com/job/7"}
        self.report = {"version": 1, **self.identity, "manifest_sha256": self.digest, "criteria": [
            {"id": "E2-1.AC1", "status": "passed", "code": "budget.py:7", "evidence": {"test": check}},
            {"id": "E2-1.AC2", "status": "pending-browser", "code": "page.ts:8", "evidence": {}},
        ]}
        self.browser = {"version": 1, **self.identity, "manifest_sha256": self.digest,
                        "criteria": [{"id": "E2-1.AC2", "evidence": {"browser": check}}]}

    def validate(self):
        return ac.validate_acceptance(self.manifest, self.digest, self.report, self.identity, self.browser)

    def test_complete_evidence_reuses_tests_and_allows_justified_inspection(self):
        self.assertEqual(self.validate(), 2)
        criterion = deepcopy(self.manifest["criteria"][0])
        criterion["id"] = "E2-1.AC3"
        self.manifest["criteria"].append(criterion)
        row = deepcopy(self.report["criteria"][0])
        row["id"] = "E2-1.AC3"
        self.report["criteria"].append(row)
        self.assertEqual(self.validate(), 3)  # No additional test required for the related AC.
        criterion["methods"] = ["inspection"]
        criterion["inspection_reason"] = "Documentation-only change"
        row["evidence"] = {"inspection": {"status": "passed", "reason": "Setup matches implemented flags",
                                         "url": "https://gitlab.com/mr/1"}}
        self.assertEqual(self.validate(), 3)

    def test_missing_stale_or_failed_evidence_cannot_pass(self):
        baseline = deepcopy((self.manifest, self.report, self.browser))
        mutations = [
            lambda: self.report["criteria"].pop(),
            lambda: self.report.update(source_sha="c" * 40),
            lambda: self.report.update(scope="E2"),
            lambda: self.report.update(manifest_sha256="d" * 64),
            lambda: self.browser.update(pipeline_id="old"),
            lambda: self.browser["criteria"][0]["evidence"]["browser"].update(status="skipped"),
            lambda: self.report["criteria"][0]["evidence"]["test"].update(test_ids=[]),
            lambda: self.report["criteria"].append(deepcopy(self.report["criteria"][0])),
            lambda: self.manifest["criteria"][1].update(methods=["test"]),
            lambda: self.manifest["criteria"][0].update(methods=["inspection"]),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                self.manifest, self.report, self.browser = deepcopy(baseline)
                mutate()
                with self.assertRaises(ac.Invalid):
                    self.validate()
        self.manifest, self.report, self.browser = deepcopy(baseline)
        self.browser = None
        with self.assertRaisesRegex(ac.Invalid, "browser report"):
            self.validate()
