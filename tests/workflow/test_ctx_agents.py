"""Registration guardrails, not proof of live model behavior or tool authorization."""

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / ".gitlab/duo/agents"


class ChatAgentRegistrationTests(unittest.TestCase):
    def test_planning_and_design_records_match_their_prompts_and_scope(self):
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
        for name in ("ctx-design", "ctx-planning"):
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
                expected = shared | publishing | ({"Create Issue"} if name == "ctx-planning" else set())
                self.assertEqual(set(tools), expected)

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


if __name__ == "__main__":
    unittest.main()
