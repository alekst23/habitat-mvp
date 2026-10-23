-- Unknown browser shutdown outcomes keep the owner/agent/site lease exclusive.
PRAGMA defer_foreign_keys = ON;
CREATE TABLE browser_session_next (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    instance_id TEXT NOT NULL REFERENCES agent_instance(id),
    request_id TEXT NOT NULL REFERENCES owner_request(id),
    workflow_run_id TEXT NOT NULL REFERENCES mock_workflow_run(id),
    request_version INTEGER NOT NULL,
    domain TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('owner','worker')),
    parent_session_id TEXT REFERENCES browser_session_next(id),
    state TEXT NOT NULL CHECK(state IN ('starting','active','saving','closing','complete','cancelled','expired','error','revoked')),
    runtime_id TEXT,
    secret_ref TEXT,
    expires_at TEXT NOT NULL,
    credential_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    close_target TEXT CHECK(close_target IN ('complete','cancelled','expired','error','revoked'))
);
INSERT INTO browser_session_next(id,tenant_id,owner_id,instance_id,request_id,workflow_run_id,request_version,domain,mode,parent_session_id,state,runtime_id,secret_ref,expires_at,credential_expires_at,created_at,updated_at)
    SELECT id,tenant_id,owner_id,instance_id,request_id,workflow_run_id,request_version,domain,mode,parent_session_id,state,runtime_id,secret_ref,expires_at,credential_expires_at,created_at,updated_at FROM browser_session;
DROP TABLE browser_session;
ALTER TABLE browser_session_next RENAME TO browser_session;
CREATE UNIQUE INDEX browser_exclusive_lease ON browser_session(tenant_id,owner_id,instance_id,domain)
    WHERE state IN ('starting','active','saving','closing');
CREATE INDEX browser_request_sessions ON browser_session(request_id,created_at);
