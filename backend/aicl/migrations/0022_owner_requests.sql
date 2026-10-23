-- Durable questions and access decisions. Purchases retain their canonical tables.
CREATE TABLE owner_request (
 id TEXT PRIMARY KEY,
 tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
 instance_id TEXT NOT NULL REFERENCES agent_instance(id),
 workflow_run_id TEXT NOT NULL REFERENCES mock_workflow_run(id),
 kind TEXT NOT NULL CHECK(kind IN ('clarification','authentication','permission')),
 title TEXT NOT NULL, reason TEXT NOT NULL, details_json TEXT NOT NULL,
 dedupe_key TEXT NOT NULL, paused_state TEXT NOT NULL,
 continuation TEXT NOT NULL CHECK(continuation IN ('now','schedule')),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','resolved','declined')),
 version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
 response_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, resolved_at TEXT,
 UNIQUE(workflow_run_id,kind,dedupe_key)
);
CREATE INDEX owner_request_inbox ON owner_request(tenant_id,owner_id,status,created_at);
CREATE INDEX owner_request_job ON owner_request(workflow_run_id,status);
