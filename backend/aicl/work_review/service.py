"""A metadata inbox over owner-scoped immutable runs, outputs and ledger evidence.

No tool invocation, inference, fetch, review approval or runtime mutation occurs
here. List search covers agent names, run goals and saved output names, not report
bodies. Detail uses the existing integrity-checking audit projection. Each read
observes one committed snapshot; marks live in a separate owner UI table.
"""
from __future__ import annotations

import base64
from datetime import date
import hashlib
import json
from urllib.parse import quote, urlsplit

from aicl.agent_runtime.storage import Repository
from aicl.control.errors import AiclError
from aicl.db import from_iso, to_iso
from aicl.network.policy import normalize_owner_domain
from aicl.workflow.cost_projection import cost_summary
from aicl.workflow.runtime_projection import RuntimeAuditProjection, audit_reader


_ATTENTION = "('waiting_owner','blocked','failed')"
_VIEWS = {"all", "unseen", "needs_attention", "saved"}
_SEARCH_SCOPE = "Agent names, goals and saved output names"
_SCOPED_FROM = """
 FROM agent_run r
 JOIN agent_instance i ON i.id=r.instance_id AND i.tenant_id=r.tenant_id AND i.owner_id=r.owner_id
 JOIN agent_workspace w ON w.instance_id=r.instance_id AND w.tenant_id=r.tenant_id AND w.owner_id=r.owner_id
"""
_SCOPED_WHERE = """
 WHERE r.tenant_id=? AND r.owner_id=?
 AND (EXISTS (SELECT 1 FROM agent_workspace_run x WHERE x.workspace_id=w.id AND x.run_id=r.id)
 OR EXISTS (SELECT 1 FROM agent_chat_run x WHERE x.session_id=w.session_id AND x.run_id=r.id))
"""
_BASE = _SCOPED_FROM + """
 JOIN agent_content d ON d.id=r.definition_ref AND d.run_id=r.id AND d.tenant_id=r.tenant_id AND d.owner_id=r.owner_id
 LEFT JOIN work_review_mark m ON m.run_id=r.id AND m.tenant_id=r.tenant_id AND m.owner_id=r.owner_id
""" + _SCOPED_WHERE
_SELECT = """SELECT r.id AS run_id,r.instance_id,r.status,r.reason,r.version,r.created_at,r.updated_at,
 r.checkpoint_ref,w.id AS workspace_id,i.name AS agent_name,
 json_extract(d.payload_json,'$.objective') AS goal,
 CASE WHEN m.seen_version>=r.version THEN 1 ELSE 0 END AS seen,COALESCE(m.saved,0) AS saved
"""


def _text(value, limit=180):
    text = next((line.strip() for line in str(value or "").splitlines() if line.strip()), "")
    return text[:limit - 1].rstrip() + "…" if len(text) > limit else text


def _safe_source_url(value):
    """Links only, never auto-fetched; exclude active schemes and URL credentials."""
    if type(value) is not str or len(value) > 6000 or any(ord(c) <= 32 for c in value):
        return None
    try:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password or "\\" in value:
            return None
        if url.port not in (None, 443):
            return None
        normalize_owner_domain(url.hostname)
    except (ValueError, AiclError):
        return None
    return value


class WorkReviewService:
    def __init__(self, ctx):
        self.db, self.clock = ctx.db, ctx.clock
        self.repo = Repository(self.db, self.clock)
        self.audit = RuntimeAuditProjection(self.db, self.clock)

    def _check_metadata(self, conn, auth, *, workspace_id="", run_id=""):
        """Check scoped immutable bytes before a filter can hide corruption.

        A materialized scope prevents the digest function from inspecting other
        owners' content. Hashing uses the repository's UTF-8 representation;
        report bodies are neither decoded into Python objects nor returned by
        list queries. No persistent cache or alternate content authority exists.
        """
        scope = "SELECT r.id,r.tenant_id,r.owner_id,r.definition_ref,r.checkpoint_ref" + _SCOPED_FROM + _SCOPED_WHERE
        args = [auth.tenant_id, auth.owner_id]
        for name, value in (("w.id", workspace_id), ("r.id", run_id)):
            if value:
                scope += " AND " + name + "=?"
                args.append(value)
        prefix = "WITH scoped AS MATERIALIZED (" + scope + ") "
        missing = conn.execute(prefix + """
            SELECT 1 FROM scoped r
            LEFT JOIN agent_content d ON d.id=r.definition_ref AND d.run_id=r.id
             AND d.tenant_id=r.tenant_id AND d.owner_id=r.owner_id AND d.kind='definition'
            LEFT JOIN agent_content p ON p.id=r.checkpoint_ref AND p.run_id=r.id
             AND p.tenant_id=r.tenant_id AND p.owner_id=r.owner_id AND p.kind='checkpoint'
            WHERE d.id IS NULL OR p.id IS NULL LIMIT 1
        """, args).fetchone()
        if missing:
            raise AiclError("unavailable", "Saved work metadata is unavailable.")
        conn.create_function("work_review_sha256", 1,
                             lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest(), deterministic=True)
        records = prefix.rstrip() + """, records AS MATERIALIZED (
            SELECT c.payload_json,c.digest,c.kind FROM scoped r
            JOIN agent_content c ON c.run_id=r.id AND c.tenant_id=r.tenant_id AND c.owner_id=r.owner_id
            WHERE c.id=r.definition_ref OR c.id=r.checkpoint_ref OR c.kind='artifact'
        ) """
        invalid = conn.execute(records + """SELECT 1 FROM records
            WHERE work_review_sha256(payload_json) IS NOT digest LIMIT 1""", args).fetchone()
        if invalid:
            raise AiclError("unavailable", "Stored content failed its integrity check.")
        # All hashes passed in this same read snapshot before metadata is parsed.
        malformed = conn.execute(records + """SELECT 1 FROM records WHERE json_type(payload_json) IS NOT 'object'
            OR (kind='definition' AND json_type(payload_json,'$.objective') IS NOT 'text')
            OR (kind='artifact' AND json_type(payload_json,'$.local_ref') IS NOT 'text')
            OR (kind='checkpoint' AND (
              COALESCE(json_type(payload_json,'$.artifacts'),'object')<>'object'
              OR COALESCE(json_type(payload_json,'$.completed_artifacts'),'array')<>'array')) LIMIT 1
        """, args).fetchone()
        if malformed:
            raise AiclError("unavailable", "Saved work metadata has an invalid format.")

    def _filters(self, auth, q, workspace_id, from_date, to_date):
        self.repo._auth(auth)
        if type(q) is not str or len(q) > 200 or any(ord(c) < 32 for c in q):
            raise AiclError("validation_failed", "Search with up to 200 characters.")
        if type(workspace_id) is not str or len(workspace_id) > 240:
            raise AiclError("validation_failed", "Select an agent workspace.")
        sql, args = _BASE, [auth.tenant_id, auth.owner_id]
        if workspace_id:
            sql += " AND w.id=?"
            args.append(workspace_id)
        dates = []
        for value in (from_date, to_date):
            if not value:
                dates.append(None)
                continue
            try:
                parsed = date.fromisoformat(value)
                if parsed.isoformat() != value:
                    raise ValueError
            except (ValueError, TypeError):
                raise AiclError("validation_failed", "Use YYYY-MM-DD for dates.") from None
            dates.append(parsed)
        if all(dates) and dates[0] > dates[1]:
            raise AiclError("validation_failed", "The end date must follow the start date.")
        if dates[0]:
            sql += " AND r.created_at>=?"
            args.append(dates[0].isoformat() + "T00:00:00.000000Z")
        if dates[1]:
            sql += " AND substr(r.created_at,1,10)<=?"
            args.append(dates[1].isoformat())
        if q.strip():
            pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            sql += """ AND (i.name LIKE ? ESCAPE '\\' OR json_extract(d.payload_json,'$.objective') LIKE ? ESCAPE '\\'
             OR EXISTS (SELECT 1 FROM agent_content o WHERE o.run_id=r.id AND o.tenant_id=r.tenant_id
              AND o.owner_id=r.owner_id AND o.kind='artifact'
              AND json_extract(o.payload_json,'$.local_ref') LIKE ? ESCAPE '\\'))"""
            args.extend([pattern] * 3)
        return sql, args

    def _owned_row(self, conn, auth, run_id):
        self.repo.owned_run(conn, auth, run_id)
        self._check_metadata(conn, auth, run_id=run_id)
        row = conn.execute(_SELECT + _BASE + " AND r.id=?", (auth.tenant_id, auth.owner_id, run_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "Work not found in an agent workspace.")
        return row

    def _item(self, conn, auth, row):
        item = dict(row)
        checkpoint = self.repo.get_content(conn, auth, row["run_id"], row["checkpoint_ref"])
        latest = checkpoint.get("artifacts", {})
        completed = checkpoint.get("completed_artifacts", [])
        versions, outputs = {}, []
        # Extract only display metadata in SQL. List responses do not materialize
        # Markdown bodies or call the full job/step projection for every run.
        for output in conn.execute(
                "SELECT id,created_at,json_extract(payload_json,'$.local_ref') AS name FROM agent_content "
                "WHERE tenant_id=? AND owner_id=? AND run_id=? AND kind='artifact' ORDER BY rowid",
                (auth.tenant_id, auth.owner_id, row["run_id"])):
            name = output["name"]
            versions[name] = versions.get(name, 0) + 1
            is_latest = latest.get(name, {}).get("ref") == output["id"]
            outputs.append({"id": "runtime:" + row["run_id"] + ":" + output["id"], "ref": output["id"],
                            "name": name, "version": versions[name], "latest": is_latest,
                            "state": "completed" if is_latest and name in completed else "draft",
                            "created_at": output["created_at"]})
        outputs.reverse()
        costs = self.audit.costs(conn, auth, row["instance_id"], row["agent_name"], run_id=row["run_id"])
        summary = cost_summary(costs)
        recorded = conn.execute(
            "SELECT 1 FROM budget_usage u JOIN agent_runtime_hold h ON h.hold_id=u.hold_id "
            "JOIN agent_step s ON s.id=h.operation_id AND s.hold_id=h.hold_id "
            "WHERE s.run_id=? AND h.instance_id=? AND h.tenant_id=? AND h.owner_id=? LIMIT 1",
            (row["run_id"], row["instance_id"], auth.tenant_id, auth.owner_id)).fetchone() is not None
        preferred = next((output for output in outputs if output["latest"]), outputs[0] if outputs else None)
        workspace_url = "/agent-workspaces/" + quote(row["workspace_id"], safe="")
        item.update(title=_text(preferred["name"].replace("_", " ") if preferred else row["goal"]) or row["agent_name"],
                    seen=bool(row["seen"]), saved=bool(row["saved"]), needs_attention=row["status"] in {"waiting_owner", "blocked", "failed"},
                    outputs=outputs, output_count=len(outputs), cost_summary=summary,
                    cost_recorded=recorded, recorded_micro_usd=summary["settled_micro_usd"] if recorded else None,
                    recorded_cost_micro_usd=summary["settled_micro_usd"] if recorded else None,
                    workspace_url=workspace_url, assistant_url=workspace_url + "#workspace-assistant",
                    audit_url="/audit/jobs/" + quote("runtime:" + row["run_id"], safe=""))
        item.pop("checkpoint_ref", None)
        return item

    def list(self, auth, *, q="", view="all", workspace_id="", from_date="", to_date="", cursor="", limit=25):
        if type(view) is not str or view not in _VIEWS or type(limit) is not int or not 1 <= limit <= 50:
            raise AiclError("validation_failed", "Choose an inbox view and a page size between 1 and 50.")
        sql, args = self._filters(auth, q, workspace_id, from_date, to_date)
        fingerprint = hashlib.sha256(json.dumps([q, view, workspace_id, from_date, to_date]).encode()).hexdigest()[:20]
        tail, tail_args = "", []
        if cursor:
            try:
                if type(cursor) is not str or len(cursor) > 1000:
                    raise ValueError
                position = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
                if (type(position) is not list or len(position) != 3 or position[2] != fingerprint
                        or type(position[0]) is not str or type(position[1]) is not str or len(position[1]) > 240):
                    raise ValueError
                from_iso(position[0])
            except (ValueError, TypeError, UnicodeError):
                raise AiclError("validation_failed", "This page cursor does not match the inbox filters.") from None
            tail = " AND (r.created_at<? OR (r.created_at=? AND r.id<?))"
            tail_args = [position[0], position[0], position[1]]
        views = {"all": "", "unseen": " AND (m.seen_version IS NULL OR m.seen_version<r.version)",
                 "saved": " AND m.saved=1", "needs_attention": " AND r.status IN " + _ATTENTION}
        with audit_reader(self.db) as conn:
            self._check_metadata(conn, auth, workspace_id=workspace_id)
            counts = conn.execute("SELECT COUNT(*) AS all_count,"
                "SUM(CASE WHEN m.seen_version IS NULL OR m.seen_version<r.version THEN 1 ELSE 0 END) AS unseen,"
                "SUM(CASE WHEN r.status IN " + _ATTENTION + " THEN 1 ELSE 0 END) AS needs_attention,"
                "SUM(CASE WHEN m.saved=1 THEN 1 ELSE 0 END) AS saved" + sql, args).fetchone()
            rows = conn.execute(_SELECT + sql + views[view] + tail + " ORDER BY r.created_at DESC,r.id DESC LIMIT ?",
                                [*args, *tail_args, limit + 1]).fetchall()
            page = rows[:limit]
            next_cursor = base64.urlsafe_b64encode(json.dumps(
                [page[-1]["created_at"], page[-1]["run_id"], fingerprint]).encode()).decode() if len(rows) > limit else None
            agents = [dict(row) for row in conn.execute(
                "SELECT w.id AS workspace_id,i.name FROM agent_workspace w JOIN agent_instance i ON i.id=w.instance_id "
                "AND i.tenant_id=w.tenant_id AND i.owner_id=w.owner_id WHERE w.tenant_id=? AND w.owner_id=? ORDER BY i.name,w.id",
                (auth.tenant_id, auth.owner_id))]
            return {"items": [self._item(conn, auth, row) for row in page], "next_cursor": next_cursor,
                    "counts": {"all": counts["all_count"], **{key: counts[key] or 0 for key in ("unseen", "needs_attention", "saved")}},
                    "agents": agents, "search_scope": _SEARCH_SCOPE, "date_basis": "Run start date (UTC)"}

    def _sources(self, conn, auth, run_id):
        sources, seen = [], set()
        for record in conn.execute(
                "SELECT c.id,c.kind,c.created_at FROM agent_content c WHERE c.run_id=? AND c.tenant_id=? AND c.owner_id=? "
                "AND (c.kind='public_research_source' OR EXISTS (SELECT 1 FROM agent_step s WHERE s.run_id=c.run_id "
                "AND s.output_ref=c.id AND s.state='applied' AND s.tool_name IN ('public.research','web.read','web.search'))) ORDER BY c.rowid",
                (run_id, auth.tenant_id, auth.owner_id)):
            content = self.repo.get_content(conn, auth, run_id, record["id"])
            entries = content.get("evidence", [content]) if isinstance(content, dict) else []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                candidates = entry.get("sources", []) if entry.get("source_kind") in {"public_search", "public_web_search"} else [entry]
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    url = _safe_source_url(candidate.get("url"))
                    kind = "search_result" if entry is not candidate else "page"
                    if not url or (url, kind) in seen:
                        continue
                    seen.add((url, kind))
                    sources.append({"url": url, "title": _text(candidate.get("title")) or urlsplit(url).hostname,
                                    "kind": kind, "unavailable": bool(candidate.get("unavailable")),
                                    "evidence_ref": record["id"], "recorded_at": record["created_at"],
                                    "instruction_authority": "untrusted_evidence"})
        return sources

    def detail(self, auth, run_id):
        with audit_reader(self.db) as conn:
            row = self._owned_row(conn, auth, run_id)
            job = self.audit.job(conn, auth, run_id)
            definition = self.repo.get_content(conn, auth, run_id,
                self.repo.owned_run(conn, auth, run_id)["definition_ref"])
            outputs = [{**output, "ref": output["id"].rsplit(":", 1)[-1]} for output in job["deliverables"]]
            return {"item": self._item(conn, auth, row), "outputs": outputs,
                    "activity": self.audit.activity_log(conn, auth, run_id), "costs": job["cost_rows"],
                    "plan": job["plan"], "question": job["question"], "sources": self._sources(conn, auth, run_id),
                    "snapshot": definition, "audit_url": job["evidence_url"]}

    def mark(self, auth, run_id, data):
        if (type(data) is not dict or not set(data) <= {"seen", "saved", "expected_version"}
                or not ({"seen", "saved"} & set(data))
                or any(type(data[key]) is not bool for key in ("seen", "saved") if key in data)
                or ("expected_version" in data and (type(data["expected_version"]) is not int or data["expected_version"] <= 0))):
            raise AiclError("validation_failed", "Supply seen or saved as true or false.")
        with self.db.transaction() as conn:
            row = self._owned_row(conn, auth, run_id)
            if "expected_version" in data and data["expected_version"] != row["version"]:
                raise AiclError("conflict", "Work changed. Refresh it before marking it seen.", current_version=row["version"])
            old = conn.execute("SELECT seen_version,saved FROM work_review_mark WHERE tenant_id=? AND owner_id=? AND run_id=?",
                               (auth.tenant_id, auth.owner_id, run_id)).fetchone()
            seen_version = old["seen_version"] if old else None
            if "seen" in data:
                seen_version = row["version"] if data["seen"] else None
            saved = int(data["saved"]) if "saved" in data else old["saved"] if old else 0
            conn.execute("INSERT INTO work_review_mark(tenant_id,owner_id,run_id,seen_version,saved,updated_at) VALUES (?,?,?,?,?,?) "
                         "ON CONFLICT(tenant_id,owner_id,run_id) DO UPDATE SET seen_version=excluded.seen_version,"
                         "saved=excluded.saved,updated_at=excluded.updated_at",
                         (auth.tenant_id, auth.owner_id, run_id, seen_version, saved, to_iso(self.clock.now())))
            return {"run_id": run_id, "version": row["version"], "seen": seen_version == row["version"], "saved": bool(saved)}
