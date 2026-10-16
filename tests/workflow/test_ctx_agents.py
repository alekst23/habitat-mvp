"""Registration guardrails, not proof of live model behavior or tool authorization."""

import hashlib
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / ".gitlab/duo/agents"
sys.path.insert(0, str(ROOT / "scripts"))
import ctx_workflow as workflow


class ChatAgentRegistrationTests(unittest.TestCase):
    def test_project_consumer_binding_is_reviewed_not_a_name_guess(self):
        catalog = json.loads((ROOT / ".gitlab/ctx/catalog.json").read_text())
        record = json.loads((AGENTS / "ctx-project.json").read_text())
        prompt = (AGENTS / "ctx-project.md").read_bytes()
        self.assertEqual(record.get("development_consumer_binding"), {
            "project_id": 87329027,
            "catalog_item_id": 1016234,
            "consumer_id": 12316920,
            "name": "CTX Development",
            "catalog_version_at_verification": "1.10.0",
            "verified_on": "2026-10-15",
            "runtime_version_policy": "gitlab_configured_consumer",
        })
        for key, value in (("project_id", 1), ("catalog_item_id", 1),
                           ("consumer_id", 1016234), ("consumer_id", True),
                           ("name", "Developer"),
                           ("runtime_version_policy", "latest_catalog_release")):
            changed = deepcopy(record)
            changed["development_consumer_binding"][key] = value
            with self.subTest(field=key), self.assertRaises(workflow.Invalid):
                workflow.validate_chat_agent("ctx-project", changed, prompt, catalog)
        changed = deepcopy(record)
        del changed["development_consumer_binding"]
        with self.assertRaises(workflow.Invalid):
            workflow.validate_chat_agent("ctx-project", changed, prompt, catalog)

        changed_catalog = deepcopy(catalog)
        changed_catalog["flows"][".gitlab/duo/flows/ctx-development.yml"]["catalog_version"] = "1.11.0"
        with self.assertRaises(workflow.Invalid):
            workflow.validate_chat_agent("ctx-project", record, prompt, changed_catalog)

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
                    expected |= {"List Duo Sessions", "Get Duo Session", "List Duo Agents And Flows",
                                 "Start Duo Session", "Send Duo Session Input"}
                self.assertEqual(set(tools), expected)

    def test_project_session_handoff_is_bounded_and_restartable(self):
        # Registration/prompt regressions only; native tool execution needs a live smoke.
        record = json.loads((AGENTS / "ctx-project.json").read_text())
        self.assertEqual(record.get("session_handoff"), {
            "allowed_entrypoint": "development",
            "flow_catalog_item_id": 1016234,
            "max_session_mutations_per_turn": 1,
            "status_requests": "read_only",
            "check_progress": "continue_authorized_objective",
            "approval_policy": "explicit_current_request",
            "automatic_wakeup": False,
        })
        prompt = (AGENTS / "ctx-project.md").read_text()
        for term in ("docs/development/project-session-handoff.md", "Check progress",
                     "Start Duo Session", "Send Duo Session Input", "can_start_session",
                     "ai_catalog_item_consumer_id", "dispatch_unknown", "workflow_id",
                     "human_approval=true", "one session mutation per user turn",
                     "Do not ask the user to monitor", "Read-only overrides continuation"):
            self.assertIn(term, prompt)
        for obsolete in ("this chat starts nothing", "No flow-start or controller-start tool is installed",
                         "The human posts the trigger; you must not initiate it indirectly"):
            self.assertNotIn(obsolete, prompt)
        guide = (ROOT / "docs/development/project-session-handoff.md").read_text()
        for requirement in ("CTX Project session handoff v1", "dispatch_unknown",
                            "prepared request without an outcome", "not an atomic lease",
                            "human_approval=true", "live-proven"):
            self.assertIn(requirement, guide)

    def test_session_handoff_policy_cannot_silently_widen(self):
        catalog = json.loads((ROOT / ".gitlab/ctx/catalog.json").read_text())
        record = json.loads((AGENTS / "ctx-project.json").read_text())
        prompt = (AGENTS / "ctx-project.md").read_bytes()
        self.assertIn("session_handoff", record)
        for key, value in (("allowed_entrypoint", "delivery"), ("flow_catalog_item_id", 1),
                           ("max_session_mutations_per_turn", 2), ("max_session_mutations_per_turn", True),
                           ("status_requests", "execute"), ("approval_policy", "automatic"),
                           ("automatic_wakeup", True)):
            changed = deepcopy(record)
            changed["session_handoff"][key] = value
            with self.subTest(field=key), self.assertRaises(workflow.Invalid):
                workflow.validate_chat_agent("ctx-project", changed, prompt, catalog)
        changed_catalog = deepcopy(catalog)
        changed_catalog["flows"][".gitlab/duo/flows/ctx-development.yml"]["catalog_url"] = (
            "https://gitlab.com/another/project/-/automate/flows/1016234"
        )
        with self.assertRaises(workflow.Invalid):
            workflow.validate_chat_agent("ctx-project", record, prompt, changed_catalog)
        for tool in ("List Duo Agents And Flows", "Start Duo Session", "Send Duo Session Input"):
            changed = deepcopy(record)
            changed["tools_ui_labels"].remove(tool)
            with self.subTest(missing_tool=tool), self.assertRaises(workflow.Invalid):
                workflow.validate_chat_agent("ctx-project", changed, prompt, catalog)
        for name in ("ctx-design", "ctx-planning"):
            specialist = json.loads((AGENTS / f"{name}.json").read_text())
            specialist["session_handoff"] = record["session_handoff"]
            with self.subTest(specialist=name), self.assertRaises(workflow.Invalid):
                workflow.validate_chat_agent(name, specialist, (AGENTS / f"{name}.md").read_bytes(), catalog)
            specialist = json.loads((AGENTS / f"{name}.json").read_text())
            specialist["tools_ui_labels"].append("GitLab GraphQL")
            with self.subTest(graphql_specialist=name), self.assertRaises(workflow.Invalid):
                workflow.validate_chat_agent(name, specialist, (AGENTS / f"{name}.md").read_bytes(), catalog)

    def test_project_native_discovery_contract(self):
        # Prompt/registration regression checks, not runtime enforcement.
        prompt = (AGENTS / "ctx-project.md").read_text()
        guide = (ROOT / "docs/development/project-discovery.md").read_text()
        for term in ("docs/development/project-discovery.md", "status_group", "statuses",
                     "Rejecting a malformed request", "can_start_session=false",
                     "development_consumer_binding", "12316920", "runtime_version=not_exposed",
                     "No GraphQL", "Known-ID reads", "trusted default-branch SHA"):
            self.assertIn(term, prompt)
        normalized = " ".join(guide.split())
        for term in ("87329027", "1016234", "12316920", "release-time",
                     "runtime version attestation", "out-of-band pin changes",
                     "repeated cursor", "partial data", "not proof of exclusive ownership",
                     "No continuation", "Tool discovery repaired", "Do this now",
                     "stale binding", "explicit approval"):
            self.assertIn(term, normalized)
        for name in ("project-sessions", "project-flows"):
            self.assertFalse((ROOT / ".gitlab/ctx/queries" / f"{name}.graphql").exists())

    def test_project_discovery_request_and_bounded_recovery(self):
        # Guard the actual publication inputs, not an unused local API adapter.
        # Model compliance still requires the transcript acceptance in the guide.
        for path in (AGENTS / "ctx-project.md", ROOT / "docs/development/project-discovery.md"):
            with self.subTest(path=path.name):
                text = path.read_text()
                examples = [json.loads(body) for body in re.findall(r"```json\n(.*?)\n```", text, re.S)]
                self.assertEqual(examples, [{"project_id": "87329027", "first": 100}],
                                 "publish one exact filter-free session request, not empty/null placeholders")
                normalized = " ".join(text.split())
                for requirement in (
                    "At most one corrected read-only attempt per user turn",
                    "Never repeat the rejected payload",
                    "Rejecting a malformed request is not proof of a contradictory schema",
                    "Do not retry Start Duo Session or Send Duo Session Input under this rule",
                    "No new permission or maintainer lookup is needed to correct your own read-only arguments",
                    "do not reset the cursor",
                    "access denial",
                ):
                    self.assertIn(requirement, normalized)
                self.assertNotIn("Do not retry the contradictory schema if it reappears", text)

    def test_project_publication_record_preserves_specialists_and_pending_live_proof(self):
        catalog = json.loads((ROOT / ".gitlab/ctx/catalog.json").read_text())
        entry = catalog["entrypoints"]["project"]
        self.assertEqual(entry["kind"], "agent")
        self.assertEqual(entry["status"], "published")
        project = json.loads((ROOT / entry["registration"]).read_text())
        self.assertEqual(project["display_name"], "CTX Project")
        self.assertTrue(project["enabled_in_project"])
        self.assertTrue(project["catalog_url"].endswith("/agents/1016538"))
        self.assertEqual(project["catalog_version"], "1.8.0")
        prompt = (AGENTS / project["system_prompt_file"]).read_bytes()
        self.assertNotIn("pending_catalog_version", project)
        self.assertEqual(project["published_source_commit"], "e72534c164b2fbd17006148bb893d7b26e4f6291")
        self.assertEqual(project["published_system_prompt_sha256"],
                         "a2e33eb774a6ea74abb90175190a0c792b0213e5580ca3ff93d2fc09669a8b5a")
        self.assertIn("Not published", project["candidate_status"])
        self.assertEqual(project["candidate_catalog_version"], "1.9.0")
        self.assertTrue(project["verification"]["resumable_owner_live"].startswith("pending"))
        self.assertNotEqual(project["published_system_prompt_sha256"], hashlib.sha256(prompt.rstrip()).hexdigest())
        self.assertTrue(project["verification"]["discovery_fallback_live"].startswith("passed discovery-only"))
        self.assertTrue(project["verification"]["discovery_recovery_live"].startswith("pending"))
        self.assertTrue(project["verification"]["ordinary_continuation_preflight_live"].startswith("partial"))
        self.assertTrue(project["verification"]["session_handoff_live"].startswith("pending"))
        self.assertTrue(project["verification"]["next_action_live"].startswith("pending"))
        self.assertEqual(project["next_entrypoint"], "development-native-session-handoff")
        self.assertNotIn("published_next_entrypoint", project)
        previous = project["publication_history"][0]
        self.assertEqual(previous["catalog_version"], "1.0.0")
        self.assertEqual(previous["published_source_commit"], "033dc8da20002486a6d18269b64e443191eebc20")
        self.assertEqual(previous["published_system_prompt_sha256"], "bc94f5d6ef907121a1fd57b3581fd215b8aba98eb0bc24f749523924baf73ab9")
        previous = project["publication_history"][1]
        self.assertEqual(previous["catalog_version"], "1.1.0")
        self.assertEqual(previous["published_system_prompt_sha256"], "197e9f37dcc9483a7310d599290e0c1730cb2be2d6a790e4b773e2a6978ef8ff")
        self.assertEqual(project["publication_history"][-1]["catalog_version"], "1.7.0")
        self.assertEqual(project["publication_history"][-1]["published_system_prompt_sha256"],
                         "cb55d49826871686118dc4f5a5fc10507045f7a0b8d2062dcfcdf4395abb4fcb")
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
                            "no shell", "No controller-start tool",
                            "Never write ctx/controller-state", "do not reset",
                            "docs/development/project-owner.md", "current-SHA",
                            "Do not ask the user to copy review text", "in the same response",
                            "after an execution journal is pinned", "Fully implement E2", "persistent objective",
                            "failed session is not a running worker", "Do not say saved when only acknowledged",
                            "Continue E2", "ctx-owner-handoff:v1", "Before offering a background handoff"):
            self.assertIn(requirement.casefold(), prompt.casefold())
        guide = (ROOT / "docs/development/project-owner.md").read_text()
        for requirement in ("read-only restart", "product decision", "technical defect",
                            "one explicit", "not yet implemented", "single-epic",
                            "active writer", "exact SHA", "behavioral acceptance remains pending"):
            self.assertIn(requirement.casefold(), guide.casefold())

    def test_project_and_design_offer_the_next_action_without_another_prompt(self):
        # Prompt regression checks, not proof that a live model follows the contract.
        for name in ("ctx-project", "ctx-design"):
            prompt = (AGENTS / f"{name}.md").read_text()
            for requirement in (
                "## Make the next step usable now",
                "docs/development/next-action.md",
                "Status-only requests remain read-only",
                "in the SAME response",
                "Result -> Next -> Your action",
                "review-only",
                "exhausted",
                "not dispatched",
                "Do not promise a final review",
            ):
                with self.subTest(agent=name, requirement=requirement):
                    self.assertTrue(requirement in prompt, f"{name} missing: {requirement}")
        guide_path = ROOT / "docs/development/next-action.md"
        self.assertTrue(guide_path.is_file(), "missing next-action contract")
        guide = guide_path.read_text()
        project_prompt = (AGENTS / "ctx-project.md").read_text()
        for phrase in ("**Do this now:**", "one immediate instruction, not guidance",
                       "imperative verb, exact destination", "exact words/action",
                       "Do authorized technical work yourself first", "read-only",
                       "checkpoint-exclusions.json", "chat does not retype the full owner JSON"):
            self.assertIn(phrase, project_prompt)
        self.assertIn("Never offer deletion of invalid notes", guide)
        for scenario in (
            "Status only", "Repair saved", "Review returned findings",
            "Budget exhausted", "Active or uncertain writer", "Design complete",
            "Explicit review-only", "Missing trigger access",
        ):
            with self.subTest(scenario=scenario):
                self.assertIn(scenario, guide)
        design = json.loads((AGENTS / "ctx-design.json").read_text())
        self.assertEqual(design["catalog_version"], "1.9.0")
        self.assertNotIn("pending_catalog_version", design)
        self.assertNotIn("candidate_status", design)
        self.assertEqual(design["published_source_commit"], "0ab47996c52ec70a2f137f1dd9243a91036a706b")
        self.assertEqual(design["published_system_prompt_sha256"],
                         "ea335e9fb6f47cc2f697226d8bb4b96ec30de9d5436aa1bfa035bf175a7d172c")
        prompt = (AGENTS / design["system_prompt_file"]).read_bytes()
        self.assertEqual(design["published_system_prompt_sha256"], hashlib.sha256(prompt).hexdigest())
        self.assertEqual(design["catalog_saved_system_prompt_sha256"], hashlib.sha256(prompt.rstrip()).hexdigest())
        self.assertEqual(design["publication_history"][-1]["catalog_version"], "1.8.0")
        self.assertTrue(design["verification"]["v1_9_configuration_readback"].startswith("passed"))
        self.assertTrue(design["verification"]["next_action_live"].startswith("pending"))

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
