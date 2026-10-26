-- Dashboard layouts and bounded, operator-funded Studio analyst requests.
CREATE TABLE studio_layout (
 tenant_id TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 state_json TEXT,
 version INTEGER NOT NULL CHECK(version > 0),
 updated_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,owner_id)
);
CREATE TABLE studio_ai_request (
 id TEXT NOT NULL,
 tenant_id TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 request_hash TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('running','completed','failed','unknown')),
 reserved_micro_usd INTEGER NOT NULL CHECK(reserved_micro_usd >= 0),
 cost_micro_usd INTEGER,
 input_tokens INTEGER,
 output_tokens INTEGER,
 model TEXT NOT NULL,
 price_version TEXT NOT NULL,
 response_id TEXT,
 result_json TEXT,
 reason TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,owner_id,id)
);
CREATE UNIQUE INDEX studio_ai_one_running ON studio_ai_request(tenant_id,owner_id) WHERE state='running';
