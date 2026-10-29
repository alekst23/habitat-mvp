"""Canonical, versioned workspace state shared by the UI and its assistant.

Draft edits grant no authority. Only the owner application entry point writes
instance controls, and its creation/control/configuration changes are atomic.
Reads never repair controls, release reservations, or activate execution.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
import unicodedata
import uuid
from urllib.parse import urlsplit

from pydantic import ValidationError

from aicl.agent_workspace.models import WorkspaceDraft, empty_draft, run_definition
from aicl.control.audit import AuditEvent, SqliteAuditLog
from aicl.control.errors import AiclError
from aicl.control.instances import Limits
from aicl.creation.models import CreateInstanceRequest
from aicl.creation.operations import LIMIT_FIELDS, SqliteInstanceOperations
from aicl.creation.service import create_instance
from aicl.db import to_iso
from aicl.network.policy import normalize_owner_domain
from aicl.network.research_policy import normalize_public_research, normalize_web_access, release_digest
from aicl.workflow.service import MockWorkflowService


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _release_payload(draft):
    access = draft.get("web_access")
    search = draft.get("web_search")
    if access is not None or search is not None:
        payload = {"mode": "agent", "purpose": draft["goal"].strip(), "access": access,
                   "queries": [], "source_urls": []}
        if search is not None:
            payload["search_access"] = search
        return payload
    public = draft["public_research"]
    return {"purpose": public["purpose"],
            "queries": public["queries"] if "web.search" in draft["tools"] else [],
            "source_urls": public["source_urls"] if "web.read" in draft["tools"] else []}


class WorkspaceService:
    def __init__(self, ctx):
        self.ctx, self.db, self.clock = ctx, ctx.db, ctx.clock
        self.workflow = MockWorkflowService(self.db, self.clock)
        self.operations = SqliteInstanceOperations(self.db, self.clock)

    def _auth(self, auth):
        if auth.expires_at <= self.clock.now():
            raise AiclError("unauthenticated", "Sign in to continue.")

    def _instance(self, conn, auth, instance_id):
        row = conn.execute("SELECT * FROM agent_instance WHERE id=? AND tenant_id=? AND owner_id=?",
                           (instance_id, auth.tenant_id, auth.owner_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "Agent not found.")
        return row

    def _session(self, conn, auth, session_id):
        row = conn.execute("SELECT * FROM assistant_session WHERE id=? AND tenant_id=? AND owner_id=?",
                           (session_id, auth.tenant_id, auth.owner_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "Assistant conversation not found.")
        return row

    def _owned(self, conn, auth, workspace_id):
        self._auth(auth)
        row = conn.execute("SELECT * FROM agent_workspace WHERE id=? AND tenant_id=? AND owner_id=?",
                           (workspace_id, auth.tenant_id, auth.owner_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "Agent workspace not found.")
        return row

    def capabilities(self):
        runtime = getattr(self.ctx, "agent_runtime", None)
        if runtime is None:
            return []
        result = []
        for descriptor in runtime.tools.specs():
            if descriptor["name"] in {"artifact.read", "web.search", "web.read"}:
                continue
            tool = runtime.tools.get(descriptor["name"])
            if not getattr(tool, "scripted", False) and not getattr(runtime, "allow_live", True):
                continue
            result.append({**descriptor, "capability": tool.capability})
        research = getattr(self.ctx, "public_research", None)
        if research is not None:
            result.extend(research.capabilities())
        return result

    def _sources(self, conn, auth, row):
        if not row["instance_id"]:
            return None, None
        instance = self._instance(conn, auth, row["instance_id"])
        workflow = conn.execute("SELECT * FROM mock_workflow_config WHERE instance_id=?", (row["instance_id"],)).fetchone()
        return instance, workflow

    @staticmethod
    def _inference_enabled(conn, instance_id):
        grant = conn.execute("SELECT enabled FROM capability_grant WHERE instance_id=? AND capability='inference'",
                             (instance_id,)).fetchone()
        return bool(grant and grant["enabled"])

    def _saved_draft(self, conn, row, field="draft_json"):
        """Ignore the retired option in stored drafts without read-side writes.

        Inference is intrinsic to agent work. Current editable input still goes
        through the strict draft schema and cannot restore this obsolete field.
        """
        data = json.loads(row[field])
        data.pop("inference_enabled", None)
        return self._draft(data)

    def _state(self, conn, auth, row):
        draft = self._saved_draft(conn, row)
        published = self._saved_draft(conn, row, "published_json") if row["published_json"] else None
        instance, workflow = self._sources(conn, auth, row)
        external = bool(instance and (instance["version"] != row["source_instance_version"] or
                        (workflow["version"] if workflow else None) != row["source_workflow_version"]))
        errors = []
        try:
            self._validate_publication(draft)
        except AiclError as error:
            errors.append({"message": error.message, **error.extra})
        schedule = conn.execute("SELECT enabled,next_due,last_outcome FROM agent_workspace_schedule WHERE workspace_id=?",
                                (row["id"],)).fetchone()
        return {"id": row["id"], "version": row["version"], "session_id": row["session_id"],
                "instance_id": row["instance_id"], "draft": draft, "published": published,
                "dirty": published != draft, "capabilities": self.capabilities(),
                "inference_grant_missing": bool(instance and instance["lifecycle"] != "archived"
                                                and not self._inference_enabled(conn, instance["id"])),
                "public_research_release": self._research_state(conn, row, draft),
                "external_conflict": external, "validation_errors": errors,
                "lifecycle": instance["lifecycle"] if instance else "draft",
                "gated_reason": instance["gated_reason"] if instance else None,
                "source_instance_version": row["source_instance_version"],
                "source_workflow_version": row["source_workflow_version"],
                "schedule": {**dict(schedule), "enabled": bool(schedule["enabled"])} if schedule else
                            {"enabled": False, "next_due": None, "last_outcome": None},
                "legacy_schedule_enabled": bool(workflow and workflow["enabled"]),
                "runtime_available": getattr(self.ctx, "agent_runtime", None) is not None,
                "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def _research_state(self, conn, row, draft):
        """Metadata only: viewing or proposing a disclosure never approves it."""
        tools = sorted(set(draft["tools"]) & {"web.search", "web.read"})
        active = conn.execute("SELECT * FROM workspace_public_research_release WHERE workspace_id=? AND revoked_at IS NULL",
                              (row["id"],)).fetchone()
        status = {"available": False, "available_tools": [], "provider_binding": None,
                  "message": "Public research is unavailable until an AICL broker and verified worker containment are configured.",
                  "recipient_label": "No approved research recipient is configured."}
        research = getattr(self.ctx, "public_research", None)
        if research is not None:
            kwargs = {"mode": "agent"} if (draft.get("web_access") or draft.get("web_search")) and tools else {}
            status = {**status, **research.status(tools=tools, **kwargs)}
        if (draft.get("web_access") or draft.get("web_search")) and tools and status.get("planner_available") is False:
            status.update(available=False, message="Configure the research agent before enabling web access.")
        available = bool(status.get("available") and isinstance(status.get("provider_binding"), dict)
                         and set(tools) <= set(status.get("available_tools", [])))
        digest = None
        if tools and available:
            try:
                digest = release_digest(_release_payload(draft), binding=status["provider_binding"], tools=tools)
            except AiclError as error:
                if error.error != "validation_failed":
                    raise
                # Incomplete goals/site lists remain editable drafts. They
                # cannot be approved until publication validation succeeds.
        recipient = status["recipient_label"]
        binding = status.get("provider_binding") or {}
        search = binding.get("search")
        if "web.search" in tools:
            if isinstance(search, dict) and type(search.get("account_id")) is str:
                recipient += ". Search account: " + search["account_id"] + "."
                if type(search.get("max_cost_micro_usd")) is int:
                    recipient += f" Maximum ${search['max_cost_micro_usd'] / 1_000_000:.6f} per search request."
            else:
                recipient = "No approved search provider account is configured."
        return {"available": available, "availability_message": status["message"],
                "recipient_label": recipient, "provider_binding": status["provider_binding"],
                "draft_digest": digest, "approved_digest": active["disclosure_digest"] if active else None,
                "approved_release_id": active["id"] if active else None,
                "version": active["version"] if active else 0,
                "legacy": bool(active and json.loads(active["payload_json"]).get("mode") != "agent"),
                "approval_required": bool(tools and (not active or active["disclosure_digest"] != digest)),
                "enabled": bool(active and tools and digest == active["disclosure_digest"])}

    def view(self, auth, workspace_id):
        with self.db.reader() as conn:
            return self._state(conn, auth, self._owned(conn, auth, workspace_id))

    def open(self, auth, *, instance_id=None, session_id=None):
        """Open the one canonical workspace, importing legacy state only once.

        A supplied conversation can identify a legacy agent or pending proposal.
        An existing workspace always retains its persistent management session.
        """
        self._auth(auth)
        with self.db.transaction() as conn:
            instance = self._instance(conn, auth, instance_id) if instance_id else None
            if session_id:
                self._session(conn, auth, session_id)
                existing = conn.execute("SELECT * FROM agent_workspace WHERE session_id=?", (session_id,)).fetchone()
                if existing:
                    if instance_id and existing["instance_id"] != instance_id:
                        raise AiclError("conflict", "This conversation belongs to another workspace.")
                    return self._state(conn, auth, self._owned(conn, auth, existing["id"]))
                linked = conn.execute("SELECT r.instance_id FROM agent_chat_run c JOIN agent_run r ON r.id=c.run_id "
                                      "WHERE c.session_id=?", (session_id,)).fetchone()
                committed = conn.execute("SELECT instance_id FROM assistant_proposal WHERE session_id=? AND state='committed' "
                                         "AND instance_id IS NOT NULL ORDER BY rowid DESC LIMIT 1", (session_id,)).fetchone()
                inferred_id = linked["instance_id"] if linked else committed["instance_id"] if committed else None
                if instance_id and inferred_id and instance_id != inferred_id:
                    raise AiclError("conflict", "This conversation belongs to another agent.")
                if not instance_id and inferred_id:
                    instance_id = inferred_id
                    instance = self._instance(conn, auth, instance_id)
            if instance_id:
                existing = conn.execute("SELECT * FROM agent_workspace WHERE instance_id=?", (instance_id,)).fetchone()
                if existing:
                    return self._state(conn, auth, self._owned(conn, auth, existing["id"]))
            if not session_id and instance_id:
                candidate = conn.execute("SELECT s.id FROM assistant_session s WHERE s.tenant_id=? AND s.owner_id=? "
                    "AND NOT EXISTS (SELECT 1 FROM agent_workspace w WHERE w.session_id=s.id) AND ("
                    "EXISTS (SELECT 1 FROM agent_chat_run c JOIN agent_run r ON c.run_id=r.id WHERE c.session_id=s.id AND r.instance_id=?) "
                    "OR EXISTS (SELECT 1 FROM assistant_proposal p WHERE p.session_id=s.id AND p.instance_id=? AND p.state='committed')) "
                    "ORDER BY s.updated_at DESC LIMIT 1", (auth.tenant_id, auth.owner_id, instance_id, instance_id)).fetchone()
                session_id = candidate["id"] if candidate else None
            now = to_iso(self.clock.now())
            if not session_id:
                session_id = str(uuid.uuid4())
                conn.execute("INSERT INTO assistant_session(id,tenant_id,owner_id,created_at,updated_at) VALUES (?,?,?,?,?)",
                             (session_id, auth.tenant_id, auth.owner_id, now, now))
            draft, workflow_version = self._import(conn, auth, instance, session_id)
            workspace_id = str(uuid.uuid4())
            conn.execute("INSERT INTO agent_workspace(id,tenant_id,owner_id,session_id,instance_id,version,draft_json,"
                         "source_instance_version,source_workflow_version,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?,?,?,?)",
                         (workspace_id, auth.tenant_id, auth.owner_id, session_id, instance_id, _json(draft),
                          instance["version"] if instance else None, workflow_version, now, now))
            conn.execute("INSERT INTO agent_workspace_schedule(workspace_id,updated_at) VALUES (?,?)", (workspace_id, now))
            if instance_id:
                conn.execute("INSERT OR IGNORE INTO agent_workspace_run(workspace_id,run_id,created_at) "
                             "SELECT ?,id,created_at FROM agent_run WHERE instance_id=? AND tenant_id=? AND owner_id=?",
                             (workspace_id, instance_id, auth.tenant_id, auth.owner_id))
            return self._state(conn, auth, self._owned(conn, auth, workspace_id))

    def _import(self, conn, auth, instance, session_id, *, prefer_run_tools=True):
        draft, workflow_version = empty_draft(), None
        if instance:
            config = self.workflow._config(conn, auth, instance["id"])
            saved = conn.execute("SELECT version FROM mock_workflow_config WHERE instance_id=?", (instance["id"],)).fetchone()
            workflow_version = saved["version"] if saved else None
            draft.update({key: deepcopy(config[key]) for key in ("name", "goal", "inputs", "deliverables", "cadence", "timezone")})
            draft["tools"] = list(config.get("tools", []))
            draft["network_domains"] = json.loads(instance["network_domains"])
            draft["limits"] = {key: instance[key] for key in LIMIT_FIELDS}
            # Legacy chat tool selection was a separate state. Preserve it when
            # available instead of inventing permission from the legacy catalog.
            run = conn.execute("SELECT r.* FROM agent_chat_run c JOIN agent_run r ON r.id=c.run_id WHERE c.session_id=?",
                               (session_id,)).fetchone()
            if run and prefer_run_tools:
                from aicl.agent_runtime.storage import Repository
                definition = Repository(self.db, self.clock).get_content(conn, auth, run["id"], run["definition_ref"])
                draft["tools"] = [name for name in definition.get("allowed_tools", []) if name != "artifact.read"]
        else:
            proposal = conn.execute("SELECT data_json FROM assistant_proposal WHERE session_id=? AND kind='create' "
                                    "AND state='pending' ORDER BY rowid DESC LIMIT 1", (session_id,)).fetchone()
            if proposal:
                payload = json.loads(proposal["data_json"])
                draft.update({key: deepcopy(payload[key]) for key in draft if key in payload})
        draft["deliverables"] = [{key: spec.get(key, [] if key == "criteria" else "")
                                  for key in ("key", "name", "description", "criteria")} for spec in draft["deliverables"]]
        # Import the older workflow's search selection as a draft choice only.
        # The owner must still Apply before any current capability is granted.
        if any(item["name"] == "web.search" for item in self.capabilities()):
            draft["tools"] = list(dict.fromkeys("web.search" if name == "web_search" else name
                                              for name in draft["tools"]))
        return draft, workflow_version

    @staticmethod
    def _version(row, expected_version):
        if type(expected_version) is not int or expected_version < 1:
            raise AiclError("validation_failed", "A workspace version is required.")
        if row["version"] != expected_version:
            raise AiclError("conflict", "The workspace changed. Review the latest settings before saving.",
                            current_version=row["version"])

    @staticmethod
    def _draft(data):
        try:
            result = WorkspaceDraft.model_validate(data).model_dump()
            result["public_research"] = normalize_public_research(result["public_research"])
            for key in ("web_access", "web_search"):
                access = result.get(key)
                if access is None:
                    continue
                access["domains"] = list(dict.fromkeys(normalize_owner_domain(host.strip().lower()) for host in access["domains"]))
                if access["mode"] in {"off", "all"}:
                    access["domains"] = []
                if access["mode"] != "off":
                    # Drafts may leave the selected-sites list empty while it
                    # is being edited; publication enforces completeness.
                    if access["mode"] != "allowlist" or access["domains"]:
                        access.update(normalize_web_access(access))
            access = result.get("web_access")
            search = result.get("web_search")
            if access is not None:
                result["tools"] = [name for name in result["tools"] if name != "web.read"]
                if access["mode"] != "off":
                    result["tools"].append("web.read")
                # The legacy instance field never grants broad access. The new
                # release is the sole source of blocklist/all-sites authority.
                result["network_domains"] = access["domains"] if access["mode"] == "allowlist" else []
            effective_search = search if search is not None else access
            if effective_search is not None:
                result["tools"] = [name for name in result["tools"] if name != "web.search"]
                if effective_search["mode"] != "off":
                    result["tools"].append("web.search")
            if any(len(item) > 500 for spec in result["deliverables"] for item in spec["criteria"]):
                raise ValueError()
            if any(len(item) > 253 for item in result["network_domains"]) or any(len(item) > 80 for item in result["tools"]):
                raise ValueError()
            return result
        except (ValidationError, ValueError):
            raise AiclError("validation_failed", "Use the documented workspace fields and bounded text, lists and spending limits.") from None

    def update_draft(self, auth, workspace_id, expected_version, patch, actor="owner"):
        if actor not in {"owner", "assistant"}:
            raise AiclError("denied", "This actor cannot edit the workspace.")
        if not isinstance(patch, dict) or not patch.keys() <= WorkspaceDraft.model_fields.keys():
            raise AiclError("validation_failed", "Supply only editable workspace fields.")
        with self.db.transaction() as conn:
            row = self._owned(conn, auth, workspace_id)
            self._version(row, expected_version)
            draft = self._saved_draft(conn, row)
            merged = {**draft, **patch}
            if "limits" in patch and isinstance(patch["limits"], dict):
                merged["limits"] = {**draft["limits"], **patch["limits"]}
            normalized = self._draft(merged)
            if normalized == draft:
                return self._state(conn, auth, row)
            conn.execute("UPDATE agent_workspace SET draft_json=?,version=version+1,updated_at=? WHERE id=?",
                         (_json(normalized), to_iso(self.clock.now()), workspace_id))
            self._event(conn, auth, row["instance_id"], "workspace_draft_updated", expected_version + 1, actor)
            return self._state(conn, auth, self._owned(conn, auth, workspace_id))

    def reload(self, auth, workspace_id, expected_version):
        """Explicit owner action to replace a stale draft with saved settings.

        Keep the published review baseline and persistent conversation. Import
        actual external changes into the draft; they need a fresh Apply whenever
        they differ from the last review. Ordinary reads never perform this.
        """
        with self.db.transaction() as conn:
            row = self._owned(conn, auth, workspace_id)
            self._version(row, expected_version)
            instance, config = self._sources(conn, auth, row)
            imported, workflow_version = self._import(conn, auth, instance, row["session_id"], prefer_run_tools=False)
            published = self._saved_draft(conn, row, "published_json") if row["published_json"] else None
            if published and instance:
                # The legacy mirror does not represent manual cadence, custom
                # times, or runtime tool names. Preserve the canonical values
                # unless that legacy configuration was explicitly edited.
                draft = deepcopy(published)
                draft.update(name=instance["name"], limits=imported["limits"], network_domains=imported["network_domains"])
                if workflow_version != row["source_workflow_version"]:
                    draft.update({key: imported[key] for key in ("goal", "inputs", "deliverables", "cadence", "timezone", "tools")})
                elif instance["instructions"] != published["goal"]:
                    draft["goal"] = instance["instructions"]
                grant_by_tool = {item["name"]: item["capability"] for item in self.capabilities()}
                grants = {item["capability"] for item in conn.execute(
                    "SELECT capability FROM capability_grant WHERE instance_id=? AND enabled=1", (instance["id"],))}
                draft["tools"] = [name for name in draft["tools"] if name not in grant_by_tool or grant_by_tool[name] in grants]
                if draft.get("web_access"):
                    prior_access = deepcopy(draft["web_access"])
                    if "network.fetch" not in grants:
                        draft["web_access"] = {"mode": "off", "domains": []}
                    elif draft["web_access"]["mode"] == "allowlist":
                        draft["web_access"]["domains"] = imported["network_domains"]
                    if draft.get("web_search") is None and draft["web_access"] != prior_access:
                        # An external page change cannot silently alter the
                        # previously approved search scope through inheritance.
                        draft["web_search"] = prior_access
                    if "network.search" not in grants:
                        draft["web_search"] = {"mode": "off", "domains": []}
            else:
                draft = imported
            conn.execute("UPDATE agent_workspace SET draft_json=?,source_instance_version=?,source_workflow_version=?,"
                         "version=version+1,updated_at=? WHERE id=?",
                         (_json(draft), instance["version"] if instance else None, workflow_version,
                          to_iso(self.clock.now()), workspace_id))
            self._event(conn, auth, row["instance_id"], "workspace_draft_reloaded", expected_version + 1)
            return self._state(conn, auth, self._owned(conn, auth, workspace_id))

    def _validate_publication(self, data):
        normalized = self._draft(data)
        name = unicodedata.normalize("NFC", normalized["name"]).strip()
        if not name or any(unicodedata.category(char) == "Cc" for char in name):
            raise AiclError("validation_failed", "Give the agent a name without control characters.")
        if any(unicodedata.category(char) == "Cc" and char not in "\n\t" for char in normalized["goal"]):
            raise AiclError("validation_failed", "The outcome contains unsupported control characters.")
        if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", normalized["time_of_day"]):
            raise AiclError("validation_failed", "Choose a daily time in HH:MM format.")
        available = {item["name"] for item in self.capabilities()}
        unavailable = sorted(set(normalized["tools"]) - available)
        if unavailable:
            raise AiclError("validation_failed", "Review unavailable tools before applying these settings: " + ", ".join(unavailable),
                            unavailable_tools=unavailable)
        normalized["tools"] = list(dict.fromkeys(normalized["tools"]))
        normalized["network_domains"] = list(dict.fromkeys(normalize_owner_domain(host) for host in normalized["network_domains"]))
        access = normalized.get("web_access")
        search = normalized.get("web_search")
        if search is not None and access is None:
            raise AiclError("validation_failed", "Choose a page access level, including Off, before applying separate search permissions.")
        for policy, label in ((access, "page access"), (search, "web search")):
            if policy and policy["mode"] == "allowlist" and not policy["domains"]:
                raise AiclError("validation_failed", f"Add at least one site, or choose a different {label} level.")
        if (access is not None or search is not None) and set(normalized["tools"]) & {"web.search", "web.read"}:
            normalize_public_research(_release_payload(normalized))
        if access is None and "web.read" in normalized["tools"] and not normalized["public_research"]["source_urls"]:
            raise AiclError("validation_failed", "List the exact public page URLs to review and release before enabling page reads.")
        if access is None and "web.search" in normalized["tools"] and not normalized["public_research"]["queries"]:
            raise AiclError("validation_failed", "List the exact public queries to review and release before enabling search.")
        if access is None and "web.search" in normalized["tools"] and any(len(query) > 600 or len(query.split()) > 75
                                                       for query in normalized["public_research"]["queries"]):
            raise AiclError("validation_failed", "Keep each public search query within 600 characters and 75 words.")
        if access is None and set(normalized["tools"]) & {"web.search", "web.read"} and not normalized["public_research"]["purpose"].strip():
            raise AiclError("validation_failed", "Describe the purpose of the public research release.")
        if access is None and "web.read" in normalized["tools"] and any(urlsplit(url).hostname not in normalized["network_domains"]
                                                     for url in normalized["public_research"]["source_urls"]):
            raise AiclError("validation_failed", "Include each exact public page hostname in the website domain limits.")
        config = self.workflow._normalize({**normalized, "scenario": "general", "tools": [],
                                           "cadence": "daily" if normalized["cadence"] == "manual" else normalized["cadence"]})
        normalized.update(name=name, goal=config["goal"], inputs=config["inputs"],
                          deliverables=[{key: spec[key] for key in ("key", "name", "description", "criteria")}
                                        for spec in config["deliverables"]])
        run_definition(normalized)
        return normalized

    def _event(self, conn, auth, instance_id, action, version, actor="owner"):
        SqliteAuditLog(self.clock).append(conn, AuditEvent(
            "commerce.policy_changed", "chat" if actor == "assistant" else "owner", "committed",
            auth.tenant_id, auth.owner_id, instance_id, details={"action": action, "version": version}))

    def apply(self, auth, workspace_id, expected_version, *, approved_public_research_digest=None):
        """Owner-only commit; absent from embedded assistant and WebMCP tool sets."""
        with self.db.transaction() as conn:
            row = self._owned(conn, auth, workspace_id)
            self._version(row, expected_version)
            current = self._state(conn, auth, row)
            if current["external_conflict"]:
                raise AiclError("conflict", "Agent controls changed outside this workspace. Reload their current values before applying.",
                                current_version=row["version"], external_conflict=True)
            instance, config = self._sources(conn, auth, row)
            if instance and instance["lifecycle"] == "archived":
                raise AiclError("invalid_state", "Archived agents cannot be changed.")
            normalized = self._validate_publication(current["draft"])
            research = self._research_state(conn, row, normalized)
            research_tools = sorted(set(normalized["tools"]) & {"web.search", "web.read"})
            if research_tools and not research["available"]:
                raise AiclError("unavailable", research["availability_message"])
            if research["approval_required"] and approved_public_research_digest != research["draft_digest"]:
                raise AiclError("denied", "Review and approve the goal and web access level before applying.",
                                reason="confirmation_required")
            if (current["published"] == normalized and not current["legacy_schedule_enabled"]
                    and not research["approval_required"] and instance
                    and self._inference_enabled(conn, instance["id"])):
                return current
            if instance is None:
                created = create_instance(auth, CreateInstanceRequest(
                    idempotency_key="workspace_" + uuid.UUID(workspace_id).hex, template_id="default",
                    name=normalized["name"], instructions=normalized["goal"],
                    enabled_capabilities=frozenset({"inference"})),
                    actor_kind="owner", surface="ui", clock=self.clock)
                instance_id = created.instance.id
            else:
                instance_id = instance["id"]
            # Use the canonical controls, always at the version produced by the
            # preceding mutation in this transaction. No unknown hold is touched.
            def version():
                return self._instance(conn, auth, instance_id)["version"]
            self.operations.set_limits(auth, instance_id, version(), Limits(**normalized["limits"]))
            old_domains = json.loads(self._instance(conn, auth, instance_id)["network_domains"])
            for domain in old_domains:
                if domain not in normalized["network_domains"]:
                    self.operations.remove_network_domain(auth, instance_id, version(), domain)
            for domain in normalized["network_domains"]:
                self.operations.add_network_domain(auth, instance_id, version(), domain)
            capabilities = self.capabilities()
            managed = {"inference", "network.fetch", "network.search", *(item["capability"] for item in capabilities)}
            # Applying an agent always establishes its intrinsic inference
            # grant. AICL still checks lifecycle, funding and spending limits
            # before every model request; no provider bypass is introduced.
            enabled = {"inference", *(item["capability"] for item in capabilities
                                      if item["name"] in normalized["tools"])}
            for capability in sorted(managed):
                self.operations.set_capability(auth, instance_id, version(), capability, capability in enabled)
            saved = self._instance(conn, auth, instance_id)
            if (saved["name"], saved["instructions"]) != (normalized["name"], normalized["goal"]):
                conn.execute("UPDATE agent_instance SET name=?,instructions=?,version=version+1,updated_at=? WHERE id=?",
                             (normalized["name"], normalized["goal"], to_iso(self.clock.now()), instance_id))
            # Legacy configuration remains readable; execution uses published_json.
            # Stop its scheduler only on this explicit owner handoff.
            if config and config["enabled"]:
                config = self.workflow.schedule(auth, instance_id, False, expected_version=config["version"])
            workflow_version = config["version"] if config else 1
            saved_config = self.workflow.save_config(auth, instance_id,
                {**normalized, "scenario": "general", "tools": [],
                 "cadence": "daily" if normalized["cadence"] == "manual" else normalized["cadence"]}, workflow_version)
            now = to_iso(self.clock.now())
            if research["approval_required"] or not research_tools:
                conn.execute("UPDATE workspace_public_research_release SET revoked_at=? WHERE workspace_id=? AND revoked_at IS NULL",
                             (now, workspace_id))
                if research_tools:
                    release_version = conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM workspace_public_research_release WHERE workspace_id=?",
                                                   (workspace_id,)).fetchone()[0]
                    conn.execute("INSERT INTO workspace_public_research_release(id,workspace_id,tenant_id,owner_id,instance_id,version,"
                                 "disclosure_digest,payload_json,binding_json,tools_json,approved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                 (str(uuid.uuid4()), workspace_id, auth.tenant_id, auth.owner_id, instance_id, release_version,
                                  research["draft_digest"], _json(_release_payload(normalized)), _json(research["provider_binding"]),
                                  _json(research_tools), now))
                    self._event(conn, auth, instance_id, "public_research_released", release_version)
            conn.execute("UPDATE agent_workspace SET instance_id=?,draft_json=?,published_json=?,source_instance_version=?,"
                         "source_workflow_version=?,version=version+1,updated_at=? WHERE id=?",
                         (instance_id, _json(normalized), _json(normalized), version(), saved_config["version"], now, workspace_id))
            # A changed schedule requires an explicit owner re-enable, avoiding
            # an old due timestamp running the new configuration unexpectedly.
            previous = current["published"]
            if previous and any(previous[key] != normalized[key] for key in ("cadence", "timezone", "time_of_day")):
                conn.execute("UPDATE agent_workspace_schedule SET enabled=0,next_due=NULL,last_outcome='Schedule settings changed; enable when ready',updated_at=? WHERE workspace_id=?",
                             (now, workspace_id))
            self._event(conn, auth, instance_id, "workspace_applied", expected_version + 1)
            return self._state(conn, auth, self._owned(conn, auth, workspace_id))
