-- The owner assistant has its own sessions, proposals and operator-funded usage.
-- It never borrows agent credit or records owner approval through model output.
CREATE TABLE assistant_session (
 id TEXT PRIMARY KEY,
 tenant_id TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX assistant_sessions_owner ON assistant_session(tenant_id,owner_id,updated_at);
CREATE TABLE assistant_turn (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES assistant_session(id),
 request_id TEXT NOT NULL,
 user_text TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('running','completed','failed','unknown')),
 reply TEXT NOT NULL DEFAULT '',
 error TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(session_id,request_id)
);
CREATE UNIQUE INDEX assistant_one_running_turn ON assistant_turn(session_id) WHERE state='running';
CREATE TABLE assistant_message (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 session_id TEXT NOT NULL REFERENCES assistant_session(id),
 turn_id TEXT REFERENCES assistant_turn(id),
 role TEXT NOT NULL CHECK(role IN ('user','assistant')),
 text TEXT NOT NULL,
 metadata_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL
);
CREATE INDEX assistant_messages_session ON assistant_message(session_id,id);
CREATE TABLE assistant_proposal (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES assistant_session(id),
 tenant_id TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 version INTEGER NOT NULL CHECK(version > 0),
 kind TEXT NOT NULL CHECK(kind IN ('create','schedule')),
 data_json TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','committed','superseded')),
 instance_id TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX assistant_pending_proposal ON assistant_proposal(session_id) WHERE state='pending';
CREATE TABLE assistant_tool_event (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 session_id TEXT NOT NULL REFERENCES assistant_session(id),
 turn_id TEXT NOT NULL REFERENCES assistant_turn(id),
 name TEXT NOT NULL,
 state TEXT NOT NULL,
 result_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE assistant_inference_attempt (
 id TEXT PRIMARY KEY,
 turn_id TEXT NOT NULL REFERENCES assistant_turn(id),
 tenant_id TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('held','settled','rejected','unknown')),
 reserved_micro_usd INTEGER NOT NULL CHECK(reserved_micro_usd >= 0),
 cost_micro_usd INTEGER,
 input_tokens INTEGER,
 output_tokens INTEGER,
 response_id TEXT,
 model TEXT,
 price_version TEXT NOT NULL,
 reason TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX assistant_attempts_turn ON assistant_inference_attempt(turn_id);
