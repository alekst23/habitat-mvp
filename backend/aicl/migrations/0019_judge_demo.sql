-- Anonymous judge workspaces use ordinary isolated owners and hashed sessions.
-- One entry nonce can provision at most one workspace, including concurrent POSTs.
CREATE TABLE judge_demo_workspace (
 owner_id TEXT PRIMARY KEY REFERENCES owner(id),
 entry_nonce_hash TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL
);
CREATE INDEX judge_demo_created ON judge_demo_workspace(created_at);
