-- One versioned editable configuration shared by owner controls and assistant.
CREATE TABLE agent_workspace (
 id TEXT PRIMARY KEY,
 tenant_id TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 session_id TEXT NOT NULL UNIQUE REFERENCES assistant_session(id),
 instance_id TEXT UNIQUE REFERENCES agent_instance(id),
 version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
 draft_json TEXT NOT NULL CHECK(json_valid(draft_json)),
 published_json TEXT CHECK(published_json IS NULL OR json_valid(published_json)),
 source_instance_version INTEGER,
 source_workflow_version INTEGER,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX agent_workspace_owner ON agent_workspace(tenant_id,owner_id,updated_at);
CREATE TRIGGER agent_workspace_scope_insert BEFORE INSERT ON agent_workspace
WHEN NOT EXISTS (SELECT 1 FROM assistant_session s WHERE s.id=NEW.session_id
 AND s.tenant_id=NEW.tenant_id AND s.owner_id=NEW.owner_id)
 OR (NEW.instance_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM agent_instance i
 WHERE i.id=NEW.instance_id AND i.tenant_id=NEW.tenant_id AND i.owner_id=NEW.owner_id))
BEGIN SELECT RAISE(ABORT, 'workspace scope mismatch'); END;
CREATE TRIGGER agent_workspace_scope_update BEFORE UPDATE OF tenant_id,owner_id,session_id,instance_id ON agent_workspace
WHEN NOT EXISTS (SELECT 1 FROM assistant_session s WHERE s.id=NEW.session_id
 AND s.tenant_id=NEW.tenant_id AND s.owner_id=NEW.owner_id)
 OR (NEW.instance_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM agent_instance i
 WHERE i.id=NEW.instance_id AND i.tenant_id=NEW.tenant_id AND i.owner_id=NEW.owner_id))
BEGIN SELECT RAISE(ABORT, 'workspace scope mismatch'); END;

CREATE TABLE agent_workspace_run (
 workspace_id TEXT NOT NULL REFERENCES agent_workspace(id),
 run_id TEXT NOT NULL UNIQUE REFERENCES agent_run(id),
 created_at TEXT NOT NULL,
 PRIMARY KEY(workspace_id,run_id)
);
CREATE TRIGGER agent_workspace_run_scope BEFORE INSERT ON agent_workspace_run
WHEN NOT EXISTS (SELECT 1 FROM agent_workspace w JOIN agent_run r ON r.id=NEW.run_id
 WHERE w.id=NEW.workspace_id AND w.instance_id=r.instance_id
 AND w.tenant_id=r.tenant_id AND w.owner_id=r.owner_id)
BEGIN SELECT RAISE(ABORT, 'workspace run scope mismatch'); END;

CREATE TABLE agent_workspace_schedule (
 workspace_id TEXT PRIMARY KEY REFERENCES agent_workspace(id),
 enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
 next_due TEXT,
 last_outcome TEXT,
 updated_at TEXT NOT NULL
);
