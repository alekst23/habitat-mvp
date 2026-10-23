-- Browser state is encrypted in secret_blob; this table contains only opaque references.
CREATE TABLE browser_session (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    instance_id TEXT NOT NULL REFERENCES agent_instance(id),
    request_id TEXT NOT NULL REFERENCES owner_request(id),
    workflow_run_id TEXT NOT NULL REFERENCES mock_workflow_run(id),
    request_version INTEGER NOT NULL,
    domain TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('owner','worker')),
    parent_session_id TEXT REFERENCES browser_session(id),
    state TEXT NOT NULL CHECK(state IN ('starting','active','saving','complete','cancelled','expired','error','revoked')),
    runtime_id TEXT,
    secret_ref TEXT,
    expires_at TEXT NOT NULL,
    credential_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX browser_exclusive_lease ON browser_session(tenant_id,owner_id,instance_id,domain)
    WHERE state IN ('starting','active','saving');
CREATE INDEX browser_request_sessions ON browser_session(request_id,created_at);
