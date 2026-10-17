CREATE TABLE owner (
  id TEXT PRIMARY KEY, email_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE magic_link (
  token_hash TEXT PRIMARY KEY, email_hash TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  used_at TEXT, requested_ip_hash TEXT NOT NULL
);
CREATE INDEX magic_link_email ON magic_link (email_hash, created_at);
CREATE INDEX magic_link_ip ON magic_link (requested_ip_hash, created_at);
CREATE TABLE session (
  id_hash TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES owner(id), created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE link_rate_window (
  scope TEXT NOT NULL CHECK (scope IN ('email','ip')), key_hash TEXT NOT NULL, window_start TEXT NOT NULL,
  PRIMARY KEY (scope, key_hash, window_start)
);
