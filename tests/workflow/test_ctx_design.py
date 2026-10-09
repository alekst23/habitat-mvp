"""Small generated-artifact fixtures; no claim of model or application execution."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from ctx_design import validate_epic


class DesignHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "docs/plan/E2"
        self.directory.mkdir(parents=True)
        self.state = {"version": 2, "project_id": "87329027", "epic": "E2",
                      "epic_issue_iid": 2, "source_issue_iid": 10, "next_ticket_number": 3,
                      "tickets": [{"id": "E2-1", "issue_iid": 3, "status": "pending", "depends_on": [], "wave": 1},
                                  {"id": "E2-2", "issue_iid": 4, "status": "pending", "depends_on": ["E2-1"], "wave": 2}]}
        self.manifest = {"version": 1, "epic": "E2", "criteria": [
            {"id": "E2-1.AC1", "scenario": "F1-S1", "statement": "Reserve before dispatch", "ui": False, "methods": ["test"]},
            {"id": "E2-2.AC1", "scenario": "F1-S2", "statement": "Show denial", "ui": True, "methods": ["browser"]}]}
        self.design = {"version": 1, "epic": "E2", "status": "draft",
                       "features": [{"spec": "docs/design/trust/spec.md", "technical": "docs/design/trust/technical.md"}],
                       "contracts": [{"id": "Reserve", "owner": "E2-1", "consumers": ["E2-2"],
                                      "document": "docs/design/trust/technical.md", "status": "specified",
                                      "stub_phase": "development-design"}],
                       "wiring": {"ticket": "E2-2", "criteria": ["E2-2.AC1"]},
                       "decisions": [{"id": "Q1", "status": "open", "owner": "operator", "blocks": ["E2-1"], "question": "Which verified model?"}]}
        self.put("docs/design/README.md", "[Trust](trust/spec.md)\n")
        self.put("docs/design/trust/spec.md", "# Trust\n**F1-S1:** Given a budget, when dispatch starts, then reserve first.\n**F1-S2:** Given denial, when the owner views it, then show the reason.\n")
        self.put("docs/design/trust/technical.md", "# Trust\n## Contracts\nReserve(request) -> reservation or denial.\n## Process topology\nAPI calls ledger over authenticated HTTP.\n## Configuration\nNo credentials in agents.\n")
        for number in (1, 2):
            self.put(f"docs/plan/E2/E2-{number}.md", f"# E2-{number}: Work\nE2-{number}.AC1\n## Solution approach\nImplement the scoped behavior.\n## Contracts\nReserve: docs/design/trust/technical.md\n## Verification\nAssert the specified behavior.\n")
        self.save()

    def put(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def save(self):
        for name, value in (("state", self.state), ("acceptance", self.manifest), ("design", self.design)):
            self.put(f"docs/plan/E2/{name}.json", json.dumps(value))

    def test_draft_can_be_saved_but_not_handed_off_as_ready(self):
        result = validate_epic(self.root, self.directory)
        self.assertEqual(result["status"], "structurally_valid")
        self.assertFalse(result["implementation_ready"])
        with self.assertRaisesRegex(ValueError, "draft|decision"):
            validate_epic(self.root, self.directory, ready=True)

    def test_rejects_actual_mr8_schema_and_wave_failures(self):
        for field, value, message in (("status", "integrated", "status"), ("wave", 1, "wave")):
            with self.subTest(field=field):
                self.state["tickets"][1][field] = value
                self.save()
                with self.assertRaisesRegex(ValueError, message):
                    validate_epic(self.root, self.directory)
                self.state["tickets"][1].update(status="pending", wave=2)
        self.manifest["criteria"][0]["methods"] = ["justified_inspection"]
        self.save()
        with self.assertRaisesRegex(ValueError, "verification methods"):
            validate_epic(self.root, self.directory)

    def test_spec_coverage_is_bidirectional_and_ticket_scoped(self):
        original = copy.deepcopy(self.manifest)
        for scenario in ("F9-S9", "F1-S2", ""):
            with self.subTest(scenario=scenario):
                self.manifest = copy.deepcopy(original)
                self.manifest["criteria"][0]["scenario"] = scenario
                self.save()
                with self.assertRaises(ValueError):
                    validate_epic(self.root, self.directory)
        self.manifest = original
        self.manifest["criteria"][0]["id"] = "E2-9.AC1"
        self.save()
        with self.assertRaisesRegex(ValueError, "unknown ticket"):
            validate_epic(self.root, self.directory)

    def test_contract_dependency_and_wiring_are_explicit(self):
        self.design["contracts"][0]["owner"] = "E2-2"
        self.design["contracts"][0]["consumers"] = ["E2-1"]
        self.save()
        with self.assertRaisesRegex(ValueError, "contract dependency"):
            validate_epic(self.root, self.directory)
        self.design["contracts"][0].update(owner="E2-1", consumers=["E2-2"])
        self.design["wiring"] = {"ticket": "E2-1", "criteria": ["E2-1.AC1"]}
        self.save()
        with self.assertRaisesRegex(ValueError, "wiring"):
            validate_epic(self.root, self.directory)

    def test_untrusted_paths_duplicate_keys_and_missing_files_fail_closed(self):
        self.design["features"][0]["spec"] = "../outside.md"
        self.save()
        with self.assertRaisesRegex(ValueError, "path"):
            validate_epic(self.root, self.directory)
        self.design["features"][0]["spec"] = "docs/design/trust/spec.md"
        self.save()
        self.put("docs/plan/E2/design.json", '{"version":1,"version":1}')
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_epic(self.root, self.directory)
        self.save()
        (self.root / "docs/design/trust/technical.md").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            validate_epic(self.root, self.directory)

    def test_ready_structure_is_not_implementation_authority(self):
        self.design["status"] = "specified"
        self.design["decisions"][0]["status"] = "resolved"
        self.save()
        result = validate_epic(self.root, self.directory, ready=True)
        self.assertTrue(result["ready_gate_passed"])
        self.assertFalse(result["implementation_ready"])
        self.state["tickets"][0]["status"] = "blocked"
        self.save()
        with self.assertRaisesRegex(ValueError, "blocked"):
            validate_epic(self.root, self.directory, ready=True)

    def test_design_handoff_separates_later_gates_without_waiving_them(self):
        self.design["status"] = "specified"
        self.design["decisions"][0].update(
            stage="enablement", safeguard="Keep provider disabled; use local port fakes.")
        self.state["tickets"][0].update(status="blocked", blocker_kind="evidence",
                                         blocked_reason="Historical independent review missing")
        self.save()
        result = validate_epic(self.root, self.directory, handoff=True)
        self.assertTrue(result.get("handoff_gate_passed"))
        self.assertFalse(result["design_complete"])
        self.assertFalse(result["ready_gate_passed"])
        self.assertFalse(result["implementation_ready"])
        self.assertEqual(result["gates"]["enablement"], ["Q1"])
        self.assertEqual(result["gates"]["blocked_tickets"], ["E2-1"])
        # The legacy all-clear check is deliberately still conservative.
        with self.assertRaisesRegex(ValueError, "open decision"):
            validate_epic(self.root, self.directory, ready=True)
        self.design["decisions"][0]["stage"] = "development"
        self.save()
        self.assertEqual(validate_epic(self.root, self.directory, handoff=True)["gates"]["development"], ["Q1"])

    def test_handoff_rejects_unfinished_design_and_unsafe_gate_classification(self):
        self.design["status"] = "specified"
        self.save()
        with self.assertRaisesRegex(ValueError, "open design decision"):
            validate_epic(self.root, self.directory, handoff=True)
        for stage in ("development", "enablement"):
            with self.subTest(stage=stage):
                self.design["decisions"][0]["stage"] = stage
                self.save()
                with self.assertRaisesRegex(ValueError, "safeguard"):
                    validate_epic(self.root, self.directory)
        self.design["decisions"][0].update(stage="unknown", safeguard="Disabled")
        self.save()
        with self.assertRaisesRegex(ValueError, "decision stage"):
            validate_epic(self.root, self.directory)
        self.design["decisions"][0].update(stage="enablement", safeguard="Disabled")
        for field, value, message in (("status", "draft", "draft"),
                                       ("contract", "pending", "contract pending")):
            with self.subTest(field=field):
                self.design["status"] = value if field == "status" else "specified"
                self.design["contracts"][0]["status"] = value if field == "contract" else "specified"
                self.save()
                with self.assertRaisesRegex(ValueError, message):
                    validate_epic(self.root, self.directory, handoff=True)

    def test_docs_only_can_justify_no_contracts_or_runtime_wiring(self):
        self.design["features"][0].pop("technical")
        self.design["features"][0]["technical_not_applicable"] = "Documentation correction only."
        self.design["contracts"] = []
        self.design["contracts_not_applicable"] = "No interfaces change."
        self.design["wiring"] = {"not_applicable": "No runtime components change."}
        self.save()
        self.assertEqual(validate_epic(self.root, self.directory)["status"], "structurally_valid")

    def test_symlink_and_duplicate_scenarios_are_rejected(self):
        spec = self.root / "docs/design/trust/spec.md"
        spec.write_text(spec.read_text() + "**F1-S1:** Duplicate definition.\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_epic(self.root, self.directory)
        spec.unlink()
        spec.symlink_to(self.root / "docs/design/trust/technical.md")
        with self.assertRaisesRegex(ValueError, "symlink"):
            validate_epic(self.root, self.directory)

    def use_feature_map(self):
        self.design["version"] = 2
        self.design["features"][0].update(
            id="trust", purpose="Reserve budget and expose denials.", tickets=["E2-1", "E2-2"])

    def test_feature_map_supports_single_feature_and_many_to_many_tickets(self):
        self.use_feature_map()
        self.save()
        result = validate_epic(self.root, self.directory)
        self.assertEqual(result["feature_layout"], "explicit")
        self.assertEqual(result["features"], 1)
        self.design["features"].append({
            "id": "funding", "purpose": "Authorize funding independently of budget reservation.",
            "spec": "docs/design/funding/spec.md", "technical_not_applicable": "Behavioral clarification only.",
            "tickets": ["E2-2"]})
        self.put("docs/design/README.md", "[Trust](trust/spec.md)\n[Funding](funding/spec.md)\n")
        self.put("docs/design/funding/spec.md", "# Funding\n**F2-S1:** Given authorization, when verified, then credit once.\n")
        self.manifest["criteria"][1]["scenario"] = "F1-S2,F2-S1"
        self.save()
        result = validate_epic(self.root, self.directory)
        self.assertEqual(result["features"], 2)
        self.assertEqual(result["scenarios"], 3)

    def test_feature_map_rejects_missing_metadata_paths_and_wrong_ticket_coverage(self):
        self.use_feature_map()
        feature = copy.deepcopy(self.design["features"][0])
        cases = [
            ({"id": "../trust"}, "feature identity"),
            ({"purpose": " "}, "feature purpose"),
            ({"spec": "docs/plan/E2/spec.md"}, "feature spec path"),
            ({"technical": "docs/design/umbrella/technical.md"}, "feature technical path"),
            ({"tickets": []}, "feature tickets"),
            ({"tickets": ["E2-1", "E2-1"]}, "feature tickets"),
            ({"tickets": ["E2-9"]}, "feature tickets"),
            ({"tickets": ["E2-1"]}, "feature ticket coverage"),
        ]
        for delta, message in cases:
            with self.subTest(delta=delta):
                self.design["features"][0] = {**feature, **delta}
                self.save()
                with self.assertRaisesRegex(ValueError, message):
                    validate_epic(self.root, self.directory)
        self.design["features"][0] = copy.deepcopy(feature)
        del self.design["features"][0]["purpose"]
        self.save()
        with self.assertRaisesRegex(ValueError, "feature purpose"):
            validate_epic(self.root, self.directory)
        self.design["features"][0] = feature
        self.design["features"].append(copy.deepcopy(feature))
        self.save()
        with self.assertRaisesRegex(ValueError, "feature identity"):
            validate_epic(self.root, self.directory)

    def test_legacy_handoff_is_readable_without_claiming_explicit_feature_layout(self):
        result = validate_epic(self.root, self.directory)
        self.assertEqual(result["feature_layout"], "legacy_unclassified")
        self.assertEqual(result["scenarios"], 2)


if __name__ == "__main__":
    unittest.main()
