-- Personal navigation metadata only: these marks are not approval or accounting.
CREATE TABLE work_review_mark (
 tenant_id TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 run_id TEXT NOT NULL REFERENCES agent_run(id),
 seen_version INTEGER CHECK(seen_version IS NULL OR seen_version > 0),
 saved INTEGER NOT NULL DEFAULT 0 CHECK(saved IN (0,1)),
 updated_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,owner_id,run_id)
);
CREATE TRIGGER work_review_mark_scope_insert BEFORE INSERT ON work_review_mark
WHEN NOT EXISTS (SELECT 1 FROM agent_run r WHERE r.id=NEW.run_id
 AND r.tenant_id=NEW.tenant_id AND r.owner_id=NEW.owner_id)
BEGIN SELECT RAISE(ABORT, 'review mark scope mismatch'); END;
CREATE TRIGGER work_review_mark_scope_update BEFORE UPDATE ON work_review_mark
WHEN NOT EXISTS (SELECT 1 FROM agent_run r WHERE r.id=NEW.run_id
 AND r.tenant_id=NEW.tenant_id AND r.owner_id=NEW.owner_id)
BEGIN SELECT RAISE(ABORT, 'review mark scope mismatch'); END;
CREATE INDEX agent_run_review_order ON agent_run(tenant_id,owner_id,created_at DESC,id DESC);
CREATE INDEX agent_content_review_kind ON agent_content(tenant_id,owner_id,run_id,kind);
