CREATE TABLE connection (
  id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, tenant_id TEXT NOT NULL, provider TEXT NOT NULL,
  display_name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active','reauthorization_required','revoked')),
  granted_scopes TEXT NOT NULL, secret_ref TEXT,
  provider_revoke_status TEXT NOT NULL DEFAULT 'not_applicable'
    CHECK (provider_revoke_status IN ('not_applicable','succeeded','failed')),
  created_at TEXT NOT NULL, revoked_at TEXT, version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX connection_owner ON connection (tenant_id, owner_id);
CREATE TABLE connection_secret (
  connection_id TEXT NOT NULL REFERENCES connection(id), field TEXT NOT NULL, secret_ref TEXT NOT NULL,
  PRIMARY KEY (connection_id, field)
);
CREATE TABLE connection_attachment (
  id TEXT PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES agent_instance(id), capability TEXT NOT NULL,
  connection_id TEXT NOT NULL REFERENCES connection(id), owner_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
  created_at TEXT NOT NULL, detached_at TEXT
);
CREATE UNIQUE INDEX connection_attachment_active ON connection_attachment (instance_id, capability)
  WHERE detached_at IS NULL;
CREATE TABLE oauth_state (
  state_hash TEXT PRIMARY KEY, owner_id TEXT NOT NULL, session_id TEXT NOT NULL, provider TEXT NOT NULL,
  display_name TEXT NOT NULL, scopes TEXT NOT NULL, pkce_verifier_ciphertext BLOB NOT NULL, created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL, used_at TEXT
);
CREATE TABLE secret_blob (
  ref TEXT PRIMARY KEY, field TEXT NOT NULL, nonce BLOB NOT NULL, ciphertext BLOB NOT NULL, destroyed_at TEXT
);
