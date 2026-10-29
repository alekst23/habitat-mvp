"""Explicit non-network adapters for the first durable-session proof.

Real provider dispatch is intentionally unavailable in this composition. A tool
adapter owns its argument validation, bounded result and effect classification.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Callable

from aicl.control.budget import Estimate, MeasuredUsage
from aicl.control.errors import AiclError
from aicl.agent_runtime.contracts import canonical_json
from aicl.agent_runtime.research_context import public_evidence_preview, public_page_text


@dataclass(frozen=True)
class AdapterResult:
    payload: object
    usage: MeasuredUsage = field(default_factory=lambda: MeasuredUsage(0, 0, 0))
    response_id: str | None = None
    model: str | None = None
    # Trusted adapter evidence of a provider limit violation, separate from
    # untrusted result text and the actual quantities used for billing.
    bounds_exceeded: bool = False


class ScriptedModel:
    scripted = True
    version = "scripted-v1"
    estimate = Estimate(0, 0, 0)

    def __init__(self, responses: list[dict | Callable]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def decide(self, context: dict, invocation_id: str) -> AdapterResult:
        self.calls.append(deepcopy(context))
        if not self.responses:
            return AdapterResult({"adapter_error": "scripted_responses_exhausted"})
        response = self.responses.pop(0)
        return AdapterResult(response(context) if callable(response) else deepcopy(response))


class ScriptedTool:
    scripted = True
    version = "scripted-v1"
    independent_read = True
    capability = "inference"
    estimate = Estimate(0, 0, 0)
    cache_ttl_seconds = 300

    def __init__(self, name: str, records: dict):
        self.name, self.records = name, deepcopy(records)
        self.calls: list[dict] = []

    def validate(self, arguments: dict) -> None:
        if (not {"key"} <= set(arguments) <= {"key", "refresh"} or type(arguments["key"]) is not str
                or ("refresh" in arguments and type(arguments["refresh"]) is not bool)):
            raise AiclError("validation_failed", "fixture read requires one string key")

    def execute(self, arguments: dict, invocation_id: str) -> AdapterResult:
        self.validate(arguments)
        self.calls.append(deepcopy(arguments))
        if arguments["key"] not in self.records:
            return AdapterResult({"error": "not_found", "value": None})
        return AdapterResult({"error": None, "value": deepcopy(self.records[arguments["key"]])})


class ToolRegistry:
    def __init__(self, tools=()):
        self._tools = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError("duplicate tool name")
            self._tools[tool.name] = tool

    def get(self, name):
        if name not in self._tools:
            raise AiclError("validation_failed", "tool is unavailable")
        return self._tools[name]

    def specs(self):
        return [deepcopy(tool.descriptor) for tool in self._tools.values() if hasattr(tool, "descriptor")]

    def with_artifact_reader(self, repository):
        return ToolRegistry([*[tool for name, tool in self._tools.items() if name != "artifact.read"],
                             ScopedArtifactReader(repository)])

    def validate_batch(self, actions, allowed_tools, *, allow_live=False):
        for action in actions:
            if action.name not in allowed_tools and action.name != "artifact.read":
                raise AiclError("denied", "tool is outside this run's grants")
            tool = self.get(action.name)
            if tool.scripted is not True and not allow_live:
                raise AiclError("denied", "live adapters are not enabled")
            if len(actions) > 1 and not tool.independent_read:
                raise AiclError("validation_failed", "batch requires independent reads")
            tool.validate(action.arguments)


class ScopedArtifactReader:
    """Internal retrieval of bounded source/draft excerpts in the current run."""
    name = "artifact.read"
    scripted = True
    version = "artifact-v5"
    independent_read = True
    capability = "inference"
    estimate = Estimate(0, 0, 0)
    cache_ttl_seconds = 0
    descriptor = {"name": "artifact.read", "description": "Read saved evidence/output in this run. source_index selects a research source. Public evidence always uses a disclosure projection; public_preview cannot disable it. field:text reads only the whitespace-normalized public_page body with metadata. For public_search omit field. Other offsets address selected JSON. Projections omit credential-shaped discovery candidates; saved evidence is unchanged. Use source refs, not read receipt wrappers.",
                  "parameters": {"type": "object", "properties": {
                      "ref": {"type": "string"}, "offset": {"type": "integer", "minimum": 0},
                      "max_chars": {"type": "integer", "minimum": 1, "maximum": 4000},
                      "source_index": {"type": "integer", "minimum": 0, "maximum": 29},
                      "field": {"type": "string", "enum": ["text"]},
                      "public_preview": {"type": "boolean"}},
                      "required": ["ref"], "additionalProperties": False}}

    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _selection_error(arguments, code):
        # These deterministic local read failures have no external effect or
        # usage. Fixed diagnostics let the next decision repair its selection
        # without treating a known empty result as an unknown provider outcome.
        messages = {
            "research_source_not_found": "Select an existing source_index from the saved research overview.",
            "public_preview_unavailable": "This saved source has no supported public preview. Use another saved source from the research overview.",
            "public_page_text_required": "field:text requires a saved public_page body. For public_search, omit field and keep public_preview:true to read the search candidates as JSON.",
            "artifact_read_receipt_unavailable": "Read the original source reference from the saved evidence overview, not an artifact.read receipt.",
        }
        return AdapterResult({"error": code, "message": messages[code], "ref": arguments["ref"],
                              **({"source_index": arguments["source_index"]} if "source_index" in arguments else {}),
                              "text": "", "next_offset": None, "total_chars": 0})

    def validate(self, arguments):
        if (not {"ref"} <= set(arguments) <= {"ref", "offset", "max_chars", "source_index", "public_preview", "field"}
                or type(arguments["ref"]) is not str
                or type(arguments.get("offset", 0)) is not int or arguments.get("offset", 0) < 0
                or type(arguments.get("max_chars", 4000)) is not int
                or not 1 <= arguments.get("max_chars", 4000) <= 4000
                or ("source_index" in arguments and (type(arguments["source_index"]) is not int
                    or not 0 <= arguments["source_index"] <= 29))
                or ("public_preview" in arguments and type(arguments["public_preview"]) is not bool)
                or ("field" in arguments and arguments["field"] != "text")):
            raise AiclError("validation_failed", "Supply a content ref and bounded character range.")

    def _public_selection(self, conn, arguments, auth, run_id, payload):
        # The scoped, integrity-checked read happens before provenance checks.
        # Public-looking JSON in a private artifact never acquires disclosure
        # projection authority from its shape or from a model-supplied hint.
        record = conn.execute("SELECT kind FROM agent_content WHERE id=? AND run_id=? AND tenant_id=? AND owner_id=?",
                              (arguments["ref"], run_id, auth.tenant_id, auth.owner_id)).fetchone()
        read_receipt = conn.execute("SELECT 1 FROM agent_step WHERE run_id=? AND tool_name='artifact.read' "
                                    "AND state='applied' AND output_ref=?", (run_id, arguments["ref"])).fetchone()
        if read_receipt:
            return self._selection_error(arguments, "artifact_read_receipt_unavailable").payload
        public_receipt = conn.execute("SELECT 1 FROM agent_step WHERE run_id=? AND tool_name='public.research' "
                                      "AND state='applied' AND output_ref=?", (run_id, arguments["ref"])).fetchone()
        if record["kind"] != "public_research_source" and not public_receipt:
            return None
        payload = self._select_source(arguments, payload)
        if isinstance(payload, AdapterResult):
            return payload.payload
        try:
            return public_evidence_preview(payload)[0]
        except ValueError:
            return self._selection_error(arguments, "public_preview_unavailable").payload

    def public_projection_selection(self, conn, arguments, auth, run_id):
        """Project complete selected public evidence for protected context use.

        Returns None for private content and a fixed selection error for an
        unsupported public selection. This does not grant a new read or export:
        callers must already be operating inside the run's AICL context path.
        """
        self.validate(arguments)
        payload = self.repository.get_content(conn, auth, run_id, arguments["ref"])
        return self._public_selection(conn, arguments, auth, run_id, payload)

    def public_read_projection(self, conn, arguments, auth, run_id):
        """The same bounded public view, without tool dispatch or audit writes."""
        payload = self.public_projection_selection(conn, arguments, auth, run_id)
        return None if payload is None else self._read_selection(arguments, payload, is_public=True).payload

    def _select_source(self, arguments, payload):
        if "source_index" in arguments:
            index = arguments["source_index"]
            if (type(payload) is not dict or payload.get("error") is not None
                    or "error" not in payload or type(payload.get("evidence")) is not list
                    or index >= len(payload["evidence"])):
                return self._selection_error(arguments, "research_source_not_found")
            return payload["evidence"][index]
        return payload

    def execute_scoped(self, arguments, invocation_id, auth, run_id):
        self.validate(arguments)
        with self.repository.db.reader() as conn:
            payload = self.repository.get_content(conn, auth, run_id, arguments["ref"])
            projected = self._public_selection(conn, arguments, auth, run_id, payload)
        is_public = projected is not None
        if is_public:
            payload = projected
        else:
            if arguments.get("public_preview") or "field" in arguments:
                raise AiclError("validation_failed", "Public previews require saved public research evidence.")
            payload = self._select_source(arguments, payload)
            if isinstance(payload, AdapterResult):
                return payload
        return self._read_selection(arguments, payload, is_public=is_public)

    def _read_selection(self, arguments, payload, *, is_public):
        if is_public and payload.get("error") is not None:
            return AdapterResult(payload)
        source_metadata = None
        if arguments.get("field") == "text":
            if (type(payload) is not dict or payload.get("source_kind") != "public_page"
                    or payload.get("unavailable") or type(payload.get("text")) is not str):
                return self._selection_error(arguments, "public_page_text_required")
            source_metadata = {key: deepcopy(payload[key]) for key in
                               ("source_kind", "url", "title", "date_candidates", "instruction_authority") if key in payload}
            text = public_page_text(payload)
        else:
            text = canonical_json(payload)
        start, maximum = arguments.get("offset", 0), arguments.get("max_chars", 4000)
        end = min(len(text), start + maximum)
        return AdapterResult({"error": None, "ref": arguments["ref"],
                              **({"projection": "public_page_text", "source": source_metadata, "offset": start,
                                  "truncated": bool(payload.get("truncated")) or end < len(text),
                                  "source_truncated": bool(payload.get("truncated"))} if source_metadata is not None else
                                 {"projection": "public_evidence_preview"} if is_public else {}),
                              **({"reader_version": self.version} if is_public else {}),
                              **({"source_index": arguments["source_index"]} if "source_index" in arguments else {}), "text": text[start:end],
                              "next_offset": end if end < len(text) else None, "total_chars": len(text)})
