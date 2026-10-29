"""Trusted composition of disclosure authority, exact egress and durable holds."""
from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import timedelta, timezone
from pathlib import Path
import sqlite3
from time import monotonic

from aicl.agent_runtime.adapters import AdapterResult
from aicl.agent_runtime.storage import Repository
from aicl.control.budget import Estimate, MeasuredUsage
from aicl.control.errors import AiclError
from aicl.control.price_table import import_price_table
from aicl.db import to_iso
from aicl.network.research_policy import (PublicResearchRelease, ResearchAuthorization,
    ResearchPolicySnapshot, SearchProviderPolicy, research_binding, web_url_allowed)
from aicl.network.research_broker import BrokerCredential, ResearchBroker
from aicl.network.research_planner import (OpenAIPublicResearchPlanner, MAX_ROUNDS, MAX_SEARCHES,
    MAX_PAGES, MAX_INPUT_TOKENS, MAX_OUTPUT_TOKENS, public_evidence)
from aicl.network.research_worker import DockerResearchWorker
from aicl.workflow.openai_inference import InferenceNoChargeError, InferenceUnknownOutcomeError

PRICE_VERSION = "brave-search-2026-10-27"
WEB_TOOLS = {"web.read", "web.search"}
MAX_EVIDENCE_RECEIPT_BYTES = 90_000


class PublicResearchService:
    version = "aicl-public-research-v2"
    price_version = PRICE_VERSION
    timeout_seconds = 110

    def __init__(self, db, clock, broker, *, planner=None):
        self.db, self.clock, self.broker, self.planner = db, clock, broker, planner
        self.repo = Repository(db, clock)
        self.gate = ResearchAuthorization(self._load_policy, clock)
        # Operator startup verification, outside owner/assistant DB transactions.
        # Dispatch still verifies every actual worker launch and current policy.
        self._status_observation = self.broker.status(verify_worker=True)

    def capabilities(self):
        return [{"name": "web.search", "capability": "network.search",
                 "description": "Search Brave for the approved goal within the owner's search policy."},
                {"name": "web.read", "capability": "network.fetch",
                 "description": "Read public HTTPS pages within the owner's web access policy."}]

    def status(self, *, tools=(), mode="exact"):
        # This is advisory. Every dispatch launches and verifies its own worker.
        state = self._status_observation
        available = (["web.read"] if state["page_available"] else []) + (["web.search"] if state["search_available"] else [])
        selected = set(tools) & WEB_TOOLS
        policy = self.broker.provider_policy if "web.search" in selected else None
        reason = state.get("reason") or (state.get("search_reason") if "web.search" in selected else None)
        if mode == "agent" and self.planner is None:
            reason = reason or "research_planner_unconfigured"
        recipients = (["OpenAI for research planning"] if mode == "agent" else [])
        if "web.search" in selected:
            recipients.append("Brave Search")
        if "web.read" in selected:
            recipients.append("public websites within your page access level")
        return {"available": selected <= set(available) and (mode != "agent" or self.planner is not None),
                "available_tools": available, "planner_available": self.planner is not None,
                "reason": reason, "provider_binding": research_binding(policy, mode=mode),
                "recipient_label": ", ".join(recipients),
                "message": ("Configure the isolated public research worker." if state.get("reason") else
                            "Configure the public research planner." if reason == "research_planner_unconfigured" else
                            "Configure a Brave Search API connection before approving search." if reason else
                            "The agent chooses searches and public pages for your approved goal." if mode == "agent" else
                            "Only the exact public queries and URLs below may leave Habitat.")}

    def _load_policy(self, auth, run_id):
        with self.db.reader() as conn:
            run = self.repo.owned_run(conn, auth, run_id)
            definition = self.repo.get_content(conn, auth, run_id, run["definition_ref"])
            release = conn.execute("SELECT * FROM workspace_public_research_release WHERE id=? AND tenant_id=? AND owner_id=? AND instance_id=?",
                (definition.get("public_research_release_id"), auth.tenant_id, auth.owner_id, run["instance_id"])).fetchone()
            if not release:
                raise AiclError("denied", "Review and approve the public research disclosure.", reason="disclosure_approval_required")
            inst = conn.execute("SELECT * FROM agent_instance WHERE id=?", (run["instance_id"],)).fetchone()
            grants = frozenset(r[0] for r in conn.execute("SELECT capability FROM capability_grant WHERE instance_id=? AND enabled=1", (run["instance_id"],)))
            payload = json.loads(release["payload_json"])
            selected = tuple(json.loads(release["tools_json"]))
            if set(selected) != set(definition["allowed_tools"]) & WEB_TOOLS:
                raise AiclError("denied", "The research permissions changed.", reason="disclosure_approval_required")
            approved = PublicResearchRelease(id=release["id"], tenant_id=release["tenant_id"], owner_id=release["owner_id"],
                instance_id=release["instance_id"], version=release["version"], disclosure_digest=release["disclosure_digest"],
                purpose=payload["purpose"], queries=tuple(payload["queries"]), source_urls=tuple(payload["source_urls"]),
                binding_json=release["binding_json"], tools=selected, revoked=release["revoked_at"] is not None,
                mode=payload.get("mode", "exact"), access_json=json.dumps(payload.get("access", {})),
                search_access_json=json.dumps(payload["search_access"]) if "search_access" in payload else None)
            return ResearchPolicySnapshot(run_id=run_id, release=approved, instance_version=inst["version"],
                enabled_capabilities=grants, network_domains=tuple(json.loads(inst["network_domains"])),
                run_status=run["status"], lifecycle=inst["lifecycle"], gated_reason=inst["gated_reason"],
                context_profile="public_research", provider_policy=self.broker.provider_policy if "web.search" in selected else None)

    def authorize(self, auth, run_id):
        return self.gate.authorize_batch(auth, run_id)

    @staticmethod
    def _agent_estimate(tools=WEB_TOOLS):
        return Estimate(MAX_ROUNDS * MAX_INPUT_TOKENS, MAX_ROUNDS * MAX_OUTPUT_TOKENS, 0,
                        web_search_calls=MAX_SEARCHES if "web.search" in tools else 0)

    def estimate(self, auth, run_id):
        state = self.gate.validate(auth, run_id)
        if state.release.mode == "agent":
            if self.planner is None:
                raise AiclError("denied", "Configure the public research planner.", reason="research_planner_unconfigured")
            return self._agent_estimate(state.release.tools)
        return Estimate(0, 0, 0, web_search_calls=len(state.release.queries))

    def action_bound(self, auth, run_id):
        state = self.gate.validate(auth, run_id)
        return ((MAX_SEARCHES if "web.search" in state.release.tools else 0)
                + (MAX_PAGES if "web.read" in state.release.tools else 0) if state.release.mode == "agent" else
                len(state.release.queries) + len(state.release.source_urls))

    def estimate_for_release(self, release_id):
        with self.db.reader() as conn:
            release = conn.execute("SELECT payload_json, tools_json FROM workspace_public_research_release WHERE id=? AND revoked_at IS NULL", (release_id,)).fetchone()
            if not release:
                raise AiclError("denied", "Review and approve the public research disclosure.", reason="disclosure_approval_required")
            payload = json.loads(release[0])
            return (self._agent_estimate(json.loads(release["tools_json"])) if payload.get("mode") == "agent" else
                    Estimate(0, 0, 0, web_search_calls=len(payload["queries"])))

    def execute(self, auth, run_id, hold_id):
        try:
            state = self.gate.validate(auth, run_id)
        except AiclError as error:
            raise InferenceNoChargeError(str(error.extra.get("reason", "research_denied"))) from None
        if state.release.mode == "agent":
            return self._execute_agent(auth, run_id, hold_id, state)
        dispatched = []
        try:
            requests = self.authorize(auth, run_id)
            with self.db.transaction() as conn:
                run = self.repo.owned_run(conn, auth, run_id)
                if run["decision_count"] != 0:
                    raise AiclError("denied", "Research must precede private analysis.", reason="private_context_disclosure")
                self._held(conn, auth, run, hold_id, requests)
                try:
                    conn.execute("INSERT INTO public_research_dispatch(hold_id,run_id,claimed_at) VALUES (?,?,?)",
                                 (hold_id, run_id, to_iso(self.clock.now())))
                except sqlite3.IntegrityError:
                    raise InferenceUnknownOutcomeError("research_dispatch_already_claimed") from None

            def before(request):
                self.gate.reauthorize(auth, request)
                with self.db.reader() as conn:
                    current = self.repo.owned_run(conn, auth, run_id)
                    self._held(conn, auth, current, hold_id, requests)
                self._record_request(auth, run_id, hold_id, request)
                return hold_id

            def record(request, result):
                dispatched.append(result)
                self._record_result(auth, run_id, hold_id, request, result)

            results = self.broker.execute_batch(requests, recheck=lambda request: self.gate.reauthorize(auth, request),
                before_dispatch=before, record=record)
            if any(r.status == "unknown" for r in results):
                raise InferenceUnknownOutcomeError("research_outcome_unknown")
            if len(results) != len(requests) or any(r.status != "succeeded" for r in results):
                if any(r.dispatched for r in results):
                    raise InferenceUnknownOutcomeError("research_batch_incomplete")
                raise InferenceNoChargeError(results[-1].reason or "research_not_dispatched")
            return AdapterResult(self._evidence_receipt(auth, run_id, hold_id, results),
                                 MeasuredUsage(0, 0, 0, web_search_calls=sum(r.web_search_calls for r in results)))
        except AiclError as error:
            if any(r.dispatched for r in dispatched):
                raise InferenceUnknownOutcomeError("research_batch_incomplete") from None
            raise InferenceNoChargeError(str(error.extra.get("reason", "research_denied"))) from None

    def _execute_agent(self, auth, run_id, hold_id, initial):
        """Research from an explicit public projection, before private analysis.

        One durable claim and one maximum hold cover the entire bounded phase.
        No partial/unknown phase is retried, and model outputs never supply
        credentials, policy, accounting, private context or release identities.
        """
        results, dispatched = [], []
        attempted = set()
        inp = out = searches = pages = 0
        deadline = monotonic() + 105
        search_limit = MAX_SEARCHES if "web.search" in initial.release.tools else 0
        page_limit = MAX_PAGES if "web.read" in initial.release.tools else 0
        limitation = (f"Public research is bounded to {MAX_ROUNDS} planning rounds, {search_limit} searches "
                      f"and {page_limit} page reads. Coverage may be incomplete.")
        expected = self._agent_estimate(initial.release.tools)

        def current():
            state = self.gate.validate(auth, run_id)
            if state.release != initial.release:
                raise AiclError("denied", "The approved web policy changed.", reason="disclosure_approval_required")
            with self.db.reader() as conn:
                run = self.repo.owned_run(conn, auth, run_id)
                if run["decision_count"] != 0:
                    raise AiclError("denied", "Research must precede private analysis.", reason="private_context_disclosure")
                self._held(conn, auth, run, hold_id, (), estimate=expected)
            return state

        def receipt(*, error=None, exceeded=False):
            payload = self._evidence_receipt(auth, run_id, hold_id, results)
            payload.update(error=error, research_limitations=limitation)
            return AdapterResult(payload, MeasuredUsage(inp, out, 0, web_search_calls=searches),
                                 bounds_exceeded=exceeded)

        try:
            if self.planner is None:
                raise InferenceNoChargeError("research_planner_unconfigured")
            current()
            with self.db.transaction() as conn:
                run = self.repo.owned_run(conn, auth, run_id)
                self._held(conn, auth, run, hold_id, (), estimate=expected)
                try:
                    conn.execute("INSERT INTO public_research_dispatch(hold_id,run_id,claimed_at) VALUES (?,?,?)",
                                 (hold_id, run_id, to_iso(self.clock.now())))
                except sqlite3.IntegrityError:
                    raise InferenceUnknownOutcomeError("research_dispatch_already_claimed") from None
            access = json.loads(initial.release.access_json)
            search_access = (json.loads(initial.release.search_access_json)
                             if initial.release.search_access_json is not None else access)
            for round_number in range(1, MAX_ROUNDS + 1):
                current()
                if searches == search_limit and pages == page_limit:
                    break
                if monotonic() + self.planner.timeout_seconds + 2 > deadline:
                    break
                # Deliberately construct every field; never pass run.definition,
                # owner messages, inputs, files, DB rows or artifact references.
                now = self.clock.now().astimezone(timezone.utc)
                context = {"goal": initial.release.purpose, "access": access, "search_access": search_access,
                           "evidence": public_evidence(results), "round": round_number,
                           "current_date": now.date().isoformat(),
                           "current_time": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
                           "remaining": {"search": search_limit - searches, "page": page_limit - pages}}
                # This is the exact adapter input, not the provider's shaped
                # HTTP envelope. Audit records never become planner evidence.
                with self.db.transaction() as conn:
                    self.repo.put_content(conn, auth, run_id, "public_research_planner_request", {
                        "schema_version": 1, "hold_id": hold_id, "round": round_number,
                        "context": context, "adapter_version": getattr(self.planner, "version", None)},
                        identity=f"research-plan-input:{hold_id}:{round_number}")
                planned = self.planner.plan(context)
                if not isinstance(planned, AdapterResult) or not isinstance(planned.usage, MeasuredUsage):
                    raise InferenceUnknownOutcomeError("research_planner_usage_unavailable")
                measured = planned.usage
                if (any(type(n) is not int or n < 0 for n in
                        (measured.inference_input_tokens, measured.inference_output_tokens))
                        or measured.compute_minutes != 0 or measured.web_search_calls != 0):
                    raise InferenceUnknownOutcomeError("research_planner_usage_invalid")
                inp += measured.inference_input_tokens
                out += measured.inference_output_tokens
                # A later lost response must not erase earlier trusted usage.
                # This journal is scoped private storage, never planner input,
                # a public artifact, provider metadata or spending authority.
                receipt_auth = replace(auth, expires_at=self.clock.now() + timedelta(minutes=1))
                try:
                    with self.db.transaction() as conn:
                        self.repo.put_content(conn, receipt_auth, run_id, "public_research_planner_receipt", {
                            "schema_version": 1, "hold_id": hold_id, "round": round_number, "model": planned.model,
                            "response_id": planned.response_id, "usage": asdict(measured),
                            "status": "received", "bounds_exceeded": bool(planned.bounds_exceeded),
                            "result": planned.payload},
                            identity=f"research-plan:{hold_id}:{round_number}")
                except Exception:
                    raise InferenceUnknownOutcomeError("research_receipt_unavailable") from None
                if (planned.bounds_exceeded or measured.inference_input_tokens > MAX_INPUT_TOKENS
                        or measured.inference_output_tokens > MAX_OUTPUT_TOKENS):
                    return receipt(error="research_planner_bound_exceeded", exceeded=True)
                if type(planned.payload) is not dict or set(planned.payload) != {"operations"}:
                    return receipt(error="research_plan_invalid")
                operations = planned.payload["operations"]
                if (type(operations) is not list or len(operations) > MAX_SEARCHES + MAX_PAGES
                        or any(type(op) is not dict or op.get("kind") not in {"search", "page"}
                               for op in operations)):
                    return receipt(error="research_plan_invalid")
                # Successful or unavailable resources are never retried within
                # this phase, including when untrusted evidence asks for it.
                distinct = []
                for operation in operations:
                    identity = json.dumps(operation, sort_keys=True, separators=(",", ":"))
                    if identity not in attempted:
                        attempted.add(identity)
                        distinct.append(operation)
                operations = distinct
                requested_searches = sum(op["kind"] == "search" for op in operations)
                requested_pages = sum(op["kind"] == "page" for op in operations)
                if searches + requested_searches > search_limit or pages + requested_pages > page_limit:
                    return receipt(error="research_action_limit")
                current()
                if not operations:
                    break
                requests = self.gate.authorize_operations(auth, run_id, operations)
                def before(request):
                    self.gate.reauthorize(auth, request)
                    current()
                    self._record_request(auth, run_id, hold_id, request)
                    return hold_id
                def record(request, result):
                    dispatched.append(result)
                    self._record_result(auth, run_id, hold_id, request, result)
                batch = self.broker.execute_batch(requests,
                    recheck=lambda request: (self.gate.reauthorize(auth, request), current()),
                    before_dispatch=before, record=record,
                    max_seconds=max(1, min(25, int(deadline - monotonic()))), continue_on_page_failure=True)
                if (len(batch) > len(requests) or any(result.status == "unknown" for result in batch)
                        or any(request.kind == "search" and result.dispatched and result.status != "succeeded"
                               for request, result in zip(requests, batch))):
                    raise InferenceUnknownOutcomeError("research_batch_incomplete")
                for request, result in zip(requests, batch):
                    if request.kind == "page" and result.status == "failed":
                        pages += 1
                        # The HTTP response is a known no-fee page failure.
                        # Preserve useful earlier evidence and report the gap;
                        # do not retry, follow redirects or treat it as success.
                        results.append(replace(result, evidence={"source_kind": "public_page", "url": request.url,
                            "unavailable": True, "reason": result.reason,
                            "instruction_authority": "untrusted_evidence"}))
                        continue
                    if result.status != "succeeded":
                        continue
                    if type(result.web_search_calls) is not int or result.web_search_calls != (request.kind == "search"):
                        raise InferenceUnknownOutcomeError("research_usage_invalid")
                    searches += result.web_search_calls
                    pages += request.kind == "page"
                    evidence = deepcopy(result.evidence)
                    if type(evidence) is dict and evidence.get("source_kind") == "public_search":
                        evidence["sources"] = [source for source in evidence.get("sources", [])
                            if type(source) is dict and web_url_allowed(source.get("url"), search_access)]
                    if type(evidence) is dict and evidence.get("source_kind") == "public_page" and "links" in evidence:
                        evidence["links"] = [link for link in evidence["links"]
                            if type(link) is dict and web_url_allowed(link.get("url"), access)]
                    results.append(replace(result, evidence=evidence))
                if len(batch) != len(requests) or any(result.status != "succeeded" and not
                        (request.kind == "page" and result.status == "failed") for request, result in zip(requests, batch)):
                    # A rejected page or a proven no-dispatch denial has no
                    # unobserved charge. Settle preceding measured operations;
                    # the error receipt still prevents private continuation.
                    return receipt(error="research_request_failed")
            current()
            return receipt()
        except InferenceNoChargeError:
            if inp or out or any(result.dispatched for result in dispatched):
                return receipt(error="research_plan_unavailable")
            raise
        except AiclError as error:
            if inp or out or any(result.dispatched for result in dispatched):
                return receipt(error="research_request_limit" if error.extra.get("policy_reason") == "provider_request_limit"
                               else "research_controls_changed")
            raise InferenceNoChargeError(str(error.extra.get("reason", "research_denied"))) from None

    def _record_request(self, auth, run_id, hold_id, request):
        """Persist the authorized request before broker credential injection.

        Never serialize the authorization object or outgoing authenticated
        request: both contain control-plane material outside this projection.
        A saved intent alone is not proof that the request reached its server.
        """
        with self.db.transaction() as conn:
            self.repo.put_content(conn, auth, run_id, "public_research_request", {
                "schema_version": 1, "hold_id": hold_id, "request_id": request.request_id,
                "kind": request.kind, "request": {"method": request.method, "url": request.url,
                    "headers": dict(request.headers), "body": ""}},
                identity=f"research-request:{hold_id}:{request.request_id}")

    def _record_result(self, auth, run_id, hold_id, request, result):
        # As with the usage journal, a session expiring during a request must
        # not erase its receipt. This identity is not used to authorize work.
        receipt_auth = replace(auth, expires_at=self.clock.now() + timedelta(minutes=1))
        try:
            with self.db.transaction() as conn:
                self.repo.put_content(conn, receipt_auth, run_id, "public_research_response", {
                    "schema_version": 1, "hold_id": hold_id, "request_id": request.request_id,
                    "kind": request.kind, "response": {"status": result.status,
                        "dispatched": result.dispatched, "http_status": result.http_status,
                        "reason": result.reason, "web_search_calls": result.web_search_calls,
                        "evidence": result.evidence}},
                    identity=f"research-response:{hold_id}:{request.request_id}")
        except Exception:
            # The batch has not yet returned measured search usage to the
            # caller. A failed journal must not settle only earlier model fees.
            raise InferenceUnknownOutcomeError("research_receipt_unavailable") from None

    def _evidence_receipt(self, auth, run_id, hold_id, results):
        """Bound inline evidence without corrupting URLs or discarding the source.

        Public observations remain untrusted. A full successful batch that does
        not fit inline is saved behind the existing scoped artifact reader;
        private analysis can retrieve it without performing any new public I/O.
        """
        payload = {"error": None, "evidence": [deepcopy(result.evidence) for result in results],
                   "public_evidence_truncated": False}

        def size(value):
            return len(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":"), allow_nan=False).encode("utf-8"))

        if size(payload) <= MAX_EVIDENCE_RECEIPT_BYTES:
            return payload
        with self.db.transaction() as conn:
            # Each broker result has its own response bound. A manifest avoids
            # exceeding the repository's per-record bound for a large batch.
            source_refs = [self.repo.put_content(conn, auth, run_id, "public_research_source", evidence,
                                                 identity=f"research-source:{hold_id}:{index}")
                           for index, evidence in enumerate(payload["evidence"])]
            ref = self.repo.put_content(conn, auth, run_id, "public_research_evidence", {
                "instruction_authority": "untrusted_evidence", "evidence_refs": source_refs},
                identity=f"research-evidence:{hold_id}")
        payload.update(public_evidence_truncated=True, full_evidence_ref=ref)
        text_fields = []
        for index, evidence in enumerate(payload["evidence"]):
            if not isinstance(evidence, dict):
                continue
            evidence["evidence_ref"] = source_refs[index]
            for entry in [evidence, *evidence.get("sources", [])]:
                if isinstance(entry, dict) and isinstance(entry.get("text"), str):
                    encoded = entry["text"].encode("utf-8")
                    text_fields.append((entry, encoded))
                    entry["text"] = ""
                    entry["truncated"] = True
        # URL/title/provenance metadata takes precedence over snippets. Some
        # legal batches contain more URL bytes than the entire inline budget;
        # retain complete entries where possible and refer to the intact batch
        # for the rest, never cut a URL into a different resource identity.
        if size(payload) > MAX_EVIDENCE_RECEIPT_BYTES:
            originals = payload["evidence"]
            payload["evidence"] = [{"evidence_index": index, "omitted": True,
                                    "evidence_ref": source_refs[index],
                                    "instruction_authority": "untrusted_evidence"}
                                   for index in range(len(originals))]
            for index, evidence in enumerate(originals):
                omitted = payload["evidence"][index]
                payload["evidence"][index] = evidence
                if size(payload) > MAX_EVIDENCE_RECEIPT_BYTES:
                    payload["evidence"][index] = omitted
            return payload

        def set_text_limit(limit):
            for entry, encoded in text_fields:
                entry["text"] = encoded[:limit].decode("utf-8", errors="ignore")

        low, high = 0, max((len(encoded) for _, encoded in text_fields), default=0)
        while low < high:
            trial = (low + high + 1) // 2
            set_text_limit(trial)
            if size(payload) <= MAX_EVIDENCE_RECEIPT_BYTES:
                low = trial
            else:
                high = trial - 1
        set_text_limit(low)
        return payload

    def _held(self, conn, auth, run, hold_id, requests, *, estimate=None):
        row = conn.execute("SELECT h.* FROM budget_hold h JOIN agent_step s ON s.hold_id=h.id JOIN agent_runtime_hold r ON r.hold_id=h.id "
            "WHERE h.id=? AND h.instance_id=? AND s.run_id=? AND s.tool_name='public.research' AND s.state='dispatching' "
            "AND r.tenant_id=? AND r.owner_id=? AND r.instance_id=? AND r.operation_id=s.id",
            (hold_id, run["instance_id"], run["id"], auth.tenant_id, auth.owner_id, run["instance_id"])).fetchone()
        count = estimate.web_search_calls if estimate else sum(r.kind == "search" for r in requests)
        # The pinned table charges the fixed gpt-6-sol text contract at 2/10
        # micro-USD per token and the fixed Brave contract at 5,000 per query.
        maximum = ((estimate.inference_input_tokens * 2 + estimate.inference_output_tokens * 10
                    + count * 5000) if estimate else sum(r.max_cost_micro_usd for r in requests))
        if (not row or row["state"] != "held" or row["price_table_version"] != self.price_version
                or row["est_web_search_calls"] != count or row["inference_micro_usd"] < maximum
                or (estimate is not None and (row["est_input_tokens"] != estimate.inference_input_tokens
                    or row["est_output_tokens"] != estimate.inference_output_tokens or row["est_compute_minutes"] != 0))):
            raise AiclError("denied", "A current research cost reservation is required.", reason="budget_unavailable")


def build_public_research(ctx):
    settings = ctx.settings
    worker = DockerResearchWorker(settings.research_worker_image) if settings.research_worker_image else None
    policy = credential = None
    if settings.brave_search_api_key.get_secret_value():
        # Key rotation invalidates old releases even if an operator reuses the
        # friendly slot label. This keyed fingerprint is never sent to providers.
        fingerprint = hmac.new(settings.identity_hmac_key.encode(),
            settings.brave_search_api_key.get_secret_value().encode(), hashlib.sha256).hexdigest()
        policy = SearchProviderPolicy("brave", settings.research_provider_account,
            settings.research_credential_binding + ":" + fingerprint, 5000, PRICE_VERSION)
        credential = BrokerCredential("brave", policy.account_id, policy.credential_binding,
                                      settings.brave_search_api_key.get_secret_value())
    with ctx.db.transaction() as conn:
        import_price_table(conn, Path(__file__).with_name("research_prices.json"), explicit_only=True)
    planner = (OpenAIPublicResearchPlanner(settings.openai_api_key.get_secret_value())
               if settings.openai_api_key.get_secret_value() else None)
    return PublicResearchService(ctx.db, ctx.clock, ResearchBroker(worker=worker, provider_policy=policy, credential=credential),
                                 planner=planner)
