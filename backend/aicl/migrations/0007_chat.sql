CREATE TABLE chat_session (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, turn INTEGER NOT NULL CHECK (turn >= 1),
  slots_json TEXT NOT NULL DEFAULT '{}',
  awaiting TEXT CHECK (awaiting IS NULL OR awaiting IN ('name','instructions','capabilities','confirmation')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX chat_session_tenant ON chat_session (tenant_id, updated_at);
CREATE TABLE chat_message (
  id INTEGER PRIMARY KEY AUTOINCREMENT, chat_session_id TEXT NOT NULL REFERENCES chat_session(id),
  tenant_id TEXT NOT NULL, turn INTEGER NOT NULL CHECK (turn >= 1),
  role TEXT NOT NULL CHECK (role IN ('user','assistant')), text TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX chat_message_session ON chat_message (chat_session_id, id);
