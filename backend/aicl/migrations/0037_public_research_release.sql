-- Explicit owner releases of exact public research requests. Draft/model edits
-- have no authority. Preserve old disclosures and approvals after revocation.
CREATE TABLE workspace_public_research_release (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES agent_workspace(id),
 tenant_id TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 instance_id TEXT NOT NULL REFERENCES agent_instance(id),
 version INTEGER NOT NULL CHECK(version > 0),
 disclosure_digest TEXT NOT NULL,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 binding_json TEXT NOT NULL CHECK(json_valid(binding_json)),
 tools_json TEXT NOT NULL CHECK(json_valid(tools_json)),
 approved_at TEXT NOT NULL,
 revoked_at TEXT,
 UNIQUE(workspace_id,version)
);
CREATE UNIQUE INDEX workspace_public_research_current
 ON workspace_public_research_release(workspace_id) WHERE revoked_at IS NULL;
CREATE TRIGGER workspace_public_research_scope BEFORE INSERT ON workspace_public_research_release
WHEN NOT EXISTS (SELECT 1 FROM agent_workspace w JOIN agent_instance i ON i.id=NEW.instance_id
 WHERE w.id=NEW.workspace_id AND w.tenant_id=NEW.tenant_id AND w.owner_id=NEW.owner_id
 AND i.tenant_id=NEW.tenant_id AND i.owner_id=NEW.owner_id
 AND (w.instance_id IS NULL OR w.instance_id=NEW.instance_id))
BEGIN SELECT RAISE(ABORT, 'public research release scope mismatch'); END;
CREATE TRIGGER workspace_public_research_immutable BEFORE UPDATE ON workspace_public_research_release
WHEN NEW.id IS NOT OLD.id OR NEW.workspace_id IS NOT OLD.workspace_id
 OR NEW.tenant_id IS NOT OLD.tenant_id OR NEW.owner_id IS NOT OLD.owner_id
 OR NEW.instance_id IS NOT OLD.instance_id OR NEW.version IS NOT OLD.version
 OR NEW.disclosure_digest IS NOT OLD.disclosure_digest OR NEW.payload_json IS NOT OLD.payload_json
 OR NEW.binding_json IS NOT OLD.binding_json OR NEW.tools_json IS NOT OLD.tools_json
 OR NEW.approved_at IS NOT OLD.approved_at OR OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL
BEGIN SELECT RAISE(ABORT, 'public research releases are immutable'); END;
CREATE TRIGGER workspace_public_research_no_delete BEFORE DELETE ON workspace_public_research_release
BEGIN SELECT RAISE(ABORT, 'public research release history is required'); END;
