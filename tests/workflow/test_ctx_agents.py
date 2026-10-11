"""Registration guardrails, not proof of live model behavior or tool authorization."""

import hashlib
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / ".gitlab/duo/agents"
sys.path.insert(0, str(ROOT / "scripts"))
import ctx_workflow as workflow


class ChatAgentRegistrationTests(unittest.TestCase):
    def test_chat_records_match_their_prompts_and_scope(self):
        shared = {
            "Get Project", "Get Commit", "Get Repository Files", "List Repository Tree",
            "Get Issue", "Get Issue Note", "List Issue Notes", "List Issues",
            "Get Merge Request", "Create Issue Note",
        }
        publishing = {
            "List Branches", "List Merge Requests", "Get Pipeline", "Get Job Logs",
            "Update Issue", "Create Branch", "Create Commit",
            "Create Merge Request",
        }
        for name in ("ctx-design", "ctx-planning", "ctx-project"):
            with self.subTest(agent=name):
                registration = AGENTS / f"{name}.json"
                self.assertTrue(registration.is_file(), f"missing chat-agent record: {name}")
                record = json.loads(registration.read_text())
                prompt = AGENTS / record["system_prompt_file"]
                self.assertEqual(prompt.parent, AGENTS)
                self.assertEqual(record["system_prompt_sha256"],
                                 hashlib.sha256(prompt.read_bytes()).hexdigest())
                self.assertEqual(record["project_id"], 87329027)
                self.assertEqual(record["visibility"], "private")
                self.assertEqual(record["external_mcp_servers"], [])
                tools = record["tools_ui_labels"]
                self.assertEqual(len(tools), len(set(tools)))
                expected = shared | publishing | ({"Create Issue"} if name != "ctx-design" else set())
                if name == "ctx-project":
                    expected |= {"List Duo Sessions", "Get Duo Session"}
                self.assertEqual(set(tools), expected)

    def test_project_publication_record_preserves_specialists_and_pending_live_proof(self):
        catalog = json.loads((ROOT / ".gitlab/ctx/catalog.json").read_text())
        entry = catalog["entrypoints"]["project"]
        self.assertEqual(entry["kind"], "agent")
        self.assertEqual(entry["status"], "published")
        project = json.loads((ROOT / entry["registration"]).read_text())
        self.assertEqual(project["display_name"], "CTX Project")
        self.assertTrue(project["enabled_in_project"])
        self.assertTrue(project["catalog_url"].endswith("/agents/1016538"))
        self.assertEqual(project["catalog_version"], "1.0.0")
        prompt = (AGENTS / project["system_prompt_file"]).read_bytes()
        self.assertEqual(project["pending_catalog_version"], "1.1.0")
        self.assertEqual(project["published_source_commit"], "033dc8da20002486a6d18269b64e443191eebc20")
        self.assertEqual(project["published_system_prompt_sha256"], "bc94f5d6ef907121a1fd57b3581fd215b8aba98eb0bc24f749523924baf73ab9")
        self.assertNotEqual(project["published_system_prompt_sha256"], hashlib.sha256(prompt.rstrip()).hexdigest())
        self.assertTrue(project["verification"]["catalog_readback"].startswith("passed"))
        self.assertTrue(project["verification"]["chat_picker"].startswith("passed"))
        self.assertEqual(project["verification"]["chat_interview_save_smoke"], "pending")
        self.assertEqual(project["verification"]["fresh_chat_status_reconciliation"], "pending")
        for name in ("planning", "design"):
            record = json.loads((ROOT / catalog["entrypoints"][name]["registration"]).read_text())
            self.assertTrue(record["enabled_in_project"], "do not retire a working specialist before live proof")
            self.assertEqual(project["procedure_modes"][name], record["operations"])
        self.assertEqual(project["procedure_modes"]["assessment"], ["ctx-project-go", "ctx-project-sleep"])
        self.assertEqual(set(project["operations"]), {
            op for operations in project["procedure_modes"].values() for op in operations
        })

    def test_project_contract_keeps_interviews_and_technical_handoffs_in_their_owners(self):
        prompt = (AGENTS / "ctx-project.md").read_text()
        for requirement in ("same conversation", "not call the standalone chat agents",
                            "status-only requests are read-only", "docs/plan/project.md",
                            "mode=design-closure", "Technical findings are agent work",
                            "no shell", "No flow-start or controller-start tool",
                            "Never write ctx/controller-state", "do not reset",
                            "docs/development/project-owner.md", "current-SHA",
                            "Do not ask the user to copy review text", "in the same response",
                            "after an execution journal is pinned", "Fully implement E2", "persistent objective",
                            "failed session is not a running worker", "Do not say saved when only acknowledged"):
            self.assertIn(requirement.casefold(), prompt.casefold())
        guide = (ROOT / "docs/development/project-owner.md").read_text()
        for requirement in ("read-only restart", "product decision", "technical defect",
                            "one explicit", "not yet implemented", "single-epic",
                            "active writer", "exact SHA", "behavioral acceptance remains pending"):
            self.assertIn(requirement.casefold(), guide.casefold())

    def test_agent_validation_rejects_changed_identity_capabilities_and_unloaded_procedures(self):
        catalog = json.loads((ROOT / ".gitlab/ctx/catalog.json").read_text())
        for name in ("ctx-planning", "ctx-design", "ctx-project"):
            record = json.loads((AGENTS / f"{name}.json").read_text())
            prompt = (AGENTS / record["system_prompt_file"]).read_bytes()
            workflow.validate_chat_agent(name, record, prompt, catalog)
            for key, value in (
                ("project_id", 1), ("system_prompt_file", "../ctx-project.md"),
                ("system_prompt_sha256", "0" * 64),
                ("tools_ui_labels", record["tools_ui_labels"] + ["Run Command"]),
                ("tools_ui_labels", record["tools_ui_labels"] + ["Start Duo Session"]),
                ("tools_ui_labels", record["tools_ui_labels"] + ["Send Duo Session Input"]),
                ("external_mcp_servers", ["unreviewed-controller"]),
                ("operations", record["operations"] + ["ctx-release"]),
            ):
                with self.subTest(agent=name, field=key):
                    changed = deepcopy(record)
                    changed[key] = value
                    with self.assertRaises(workflow.Invalid):
                        workflow.validate_chat_agent(name, changed, prompt, catalog)
            changed = deepcopy(record)
            shortened = prompt.replace(catalog["skills"][record["operations"][0]].encode(), b"unloaded-procedure")
            changed["system_prompt_sha256"] = hashlib.sha256(shortened).hexdigest()
            with self.subTest(agent=name, field="missing procedure with fresh hash"):
                with self.assertRaises(workflow.Invalid):
                    workflow.validate_chat_agent(name, changed, shortened, catalog)

    def test_project_mode_routing_cannot_silently_lose_design_or_gain_execution(self):
        catalog = json.loads((ROOT / ".gitlab/ctx/catalog.json").read_text())
        record = json.loads((AGENTS / "ctx-project.json").read_text())
        prompt = (AGENTS / record["system_prompt_file"]).read_bytes()
        for mode, operations in (("design", []), ("planning", ["ctx-ticket-start"]),
                                 ("execution", ["ctx-epic-run"])):
            changed = deepcopy(record)
            changed["procedure_modes"][mode] = operations
            with self.subTest(mode=mode), self.assertRaises(workflow.Invalid):
                workflow.validate_chat_agent("ctx-project", changed, prompt, catalog)

    def test_planning_entrypoint_replaces_flow_without_losing_operations(self):
        catalog = json.loads((ROOT / ".gitlab/ctx/catalog.json").read_text())
        legacy = catalog["flows"][".gitlab/duo/flows/ctx-planning.yml"]
        self.assertIn("entrypoints", catalog, "catalog still routes all planning through CI")
        entry = catalog["entrypoints"]["planning"]
        self.assertEqual(entry["kind"], "agent")
        self.assertEqual(legacy["status"], "retired")
        self.assertEqual(legacy["replaced_by"], entry["registration"])
        planning = json.loads((ROOT / entry["registration"]).read_text())
        design = json.loads((ROOT / catalog["entrypoints"]["design"]["registration"]).read_text())
        self.assertEqual(set(planning["operations"]), {
            "ctx-project-design", "ctx-issue-new", "ctx-issue-triage",
            "ctx-epic-new", "ctx-ticket-new",
        })
        self.assertEqual(set(design["operations"]), {
            "ctx-spec-interview", "ctx-epic-design", "ctx-ticket-design",
        })
        self.assertTrue(set(legacy["operations"]) <= set(planning["operations"] + design["operations"]))
        for record in (planning, design):
            prompt = (AGENTS / record["system_prompt_file"]).read_text()
            for operation in record["operations"]:
                self.assertIn(catalog["skills"][operation], prompt)

    def test_stage_ownership_and_durable_design_handoff(self):
        planning = json.loads((AGENTS / "ctx-planning.json").read_text())
        design = json.loads((AGENTS / "ctx-design.json").read_text())
        self.assertEqual(planning["next_entrypoint"], "design")
        self.assertEqual(design["next_entrypoint"], "development")
        self.assertEqual(planning["artifact_ownership"], ["scope", "epic", "tickets", "dependencies", "plan_state"])
        self.assertEqual(design["artifact_ownership"], ["spec", "technical_design", "ticket_design", "acceptance_manifest"])
        prompt = (AGENTS / "ctx-design.md").read_text()
        for requirement in ("Create Commit", "Get Repository Files", "returned commit SHA",
                            "docs/design/<feature>/spec.md", "acceptance.json",
                            "Do not send the user to Planning or Development merely to save",
                            "draft", "last_commit_id"):
            self.assertIn(requirement, prompt)
        self.assertNotIn("Do not commit specifications or design files", prompt)

    def test_development_consumes_saved_design_and_ticket_template_allows_planning_first(self):
        flow = (ROOT / ".gitlab/duo/flows/ctx-development.yml").read_text()
        self.assertIn("Consume the committed specifications", flow)
        self.assertIn("only real scope/decomposition changes belong to Planning", flow)
        self.assertIn("Do not require a new design commit", flow)
        ticket = (ROOT / ".gitlab/ctx/templates/ticket.md").read_text()
        self.assertIn("Design pending", ticket)
        self.assertIn("block ticket creation, but it does block implementation", ticket)

    def test_design_session_contract_and_feature_map_are_not_checkpoint_handoffs(self):
        prompt = (AGENTS / "ctx-design.md").read_text()
        for requirement in ("Own the session", "Design progress", "in the same response",
                            "Treat save receipts as progress", "version-2 design.json",
                            "A feature can span tickets", "not automatically one feature",
                            "GitLab tool approval cards remain mandatory",
                            "do not reload every feature", "epic-wide consistency pass"):
            self.assertIn(requirement.lower(), prompt.lower())
        self.assertNotIn("Finish a save with normal prose", prompt)
        template = json.loads((ROOT / ".gitlab/ctx/templates/design.json").read_text())
        self.assertEqual(template["version"], 2)
        self.assertTrue({"id", "purpose", "tickets", "spec", "technical"} <= template["features"][0].keys())

    def test_design_completion_does_not_wait_for_execution_or_unreadable_mr_notes(self):
        prompt = (AGENTS / "ctx-design.md").read_text()
        for requirement in ("design specified, development preflight passed",
                            "status to specified", "--handoff", "safeguard",
                            "unreadable MR comment", "not a failed review",
                            "Get Merge Request's advertised include option", "notes/discussions",
                            "source issue", "does not require a documentation MR to remain Draft",
                            "Thin summaries", "one next human invocation"):
            self.assertIn(requirement, prompt)
        flow = (ROOT / ".gitlab/duo/flows/ctx-development.yml").read_text()
        for requirement in ("ctx_design.py --handoff", "BEFORE assessing",
                            "mode=historical-evidence", "do not send review collection to Design",
                            "then return. No epic completion claim"):
            self.assertIn(requirement, flow)
        review = (ROOT / "skills/ctx-epic-review/SKILL.md").read_text()
        for requirement in ("exact design SHA", "source-issue", "original ACs",
                            "Changed ACs", "Do not edit state", "safeguards"):
            self.assertIn(requirement, review)

    def test_design_owns_closure_and_has_a_concrete_research_handoff(self):
        prompt = (AGENTS / "ctx-design.md").read_text()
        flow = (ROOT / ".gitlab/duo/flows/ctx-development.yml").read_text()
        guide = (ROOT / "docs/development/design-closure.md").read_text()
        for term in ("mode=design-closure", "mode=feasibility-research", "120 words",
                     "not Design completion", "fresh independent review", "source-issue receipt"):
            self.assertIn(term, prompt)
        for term in ("mode=design-repair", "scripts/ctx_design_closure.py", "THREE repair",
                     "TWO research", "STOPs", "ctx_research.py", "no code/stubs/tests/CI/policy"):
            self.assertIn(term, flow)
        for term in ("Reddit", "PayPal", "Render", "Browserbase", "source_urls", "fallback",
                     "BEFORE delegate_task", "no ticket claims"):
            self.assertIn(term, guide)


if __name__ == "__main__":
    unittest.main()
