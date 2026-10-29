-- Nonproduction durable-agent persistence. Content is scoped, not encrypted.
-- Content precedes its first run in the admission transaction, so its run scope
-- is checked by the repository rather than a circular foreign key.
CREATE TABLE agent_content (
 id TEXT PRIMARY KEY,
 tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, run_id TEXT NOT NULL,
 kind TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 digest TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(id,run_id), UNIQUE(id,tenant_id,owner_id,run_id)
);
CREATE TRIGGER agent_content_no_update BEFORE UPDATE ON agent_content
BEGIN SELECT RAISE(ABORT, 'agent content is immutable'); END;
CREATE TRIGGER agent_content_no_delete BEFORE DELETE ON agent_content
BEGIN SELECT RAISE(ABORT, 'agent content is immutable'); END;

CREATE TABLE agent_run (
 id TEXT PRIMARY KEY,
 tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
 instance_id TEXT NOT NULL REFERENCES agent_instance(id),
 request_key TEXT NOT NULL, request_digest TEXT NOT NULL,
 definition_ref TEXT NOT NULL, checkpoint_ref TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('queued','running','waiting_owner','blocked','paused','completed','failed','cancelled')),
 reason TEXT,
 version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
 owner_cursor INTEGER NOT NULL DEFAULT 0 CHECK(owner_cursor >= 0),
 applied_cursor INTEGER NOT NULL DEFAULT 0 CHECK(applied_cursor >= 0 AND applied_cursor <= owner_cursor),
 decision_count INTEGER NOT NULL DEFAULT 0 CHECK(decision_count >= 0),
 action_count INTEGER NOT NULL DEFAULT 0 CHECK(action_count >= 0),
 draft_count INTEGER NOT NULL DEFAULT 0 CHECK(draft_count >= 0),
 invalid_count INTEGER NOT NULL DEFAULT 0 CHECK(invalid_count >= 0),
 lease_owner TEXT, lease_until TEXT,
 fence INTEGER NOT NULL DEFAULT 0 CHECK(fence >= 0),
 limits_json TEXT NOT NULL CHECK(json_valid(limits_json)),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 CHECK((lease_owner IS NULL) = (lease_until IS NULL)),
 UNIQUE(tenant_id,instance_id,request_key),
 FOREIGN KEY(definition_ref,tenant_id,owner_id,id) REFERENCES agent_content(id,tenant_id,owner_id,run_id),
 FOREIGN KEY(checkpoint_ref,tenant_id,owner_id,id) REFERENCES agent_content(id,tenant_id,owner_id,run_id)
);
CREATE INDEX agent_run_owner ON agent_run(tenant_id,owner_id,instance_id,status);

CREATE TABLE agent_step (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_run(id),
 sequence INTEGER NOT NULL CHECK(sequence > 0),
 kind TEXT NOT NULL CHECK(kind IN ('decision','tool')),
 origin_decision_id TEXT, action_ordinal INTEGER CHECK(action_ordinal >= 0),
 tool_name TEXT, tool_version TEXT,
 input_ref TEXT NOT NULL, output_ref TEXT,
 state TEXT NOT NULL CHECK(state IN ('prepared','dispatching','received','applied','superseded','unknown')),
 base_version INTEGER NOT NULL CHECK(base_version > 0),
 owner_cursor INTEGER NOT NULL CHECK(owner_cursor >= 0),
 hold_id TEXT REFERENCES budget_hold(id), usage_json TEXT CHECK(usage_json IS NULL OR json_valid(usage_json)),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(run_id,sequence), UNIQUE(id,run_id),
 FOREIGN KEY(input_ref,run_id) REFERENCES agent_content(id,run_id),
 FOREIGN KEY(output_ref,run_id) REFERENCES agent_content(id,run_id),
 FOREIGN KEY(origin_decision_id,run_id) REFERENCES agent_step(id,run_id)
);
CREATE UNIQUE INDEX agent_step_action_identity ON agent_step(origin_decision_id,action_ordinal)
 WHERE origin_decision_id IS NOT NULL AND action_ordinal IS NOT NULL;
CREATE INDEX agent_step_pending ON agent_step(run_id,state,sequence);

CREATE TABLE agent_event (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_run(id),
 sequence INTEGER NOT NULL CHECK(sequence > 0),
 kind TEXT NOT NULL, request_key TEXT NOT NULL, payload_ref TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(run_id,sequence), UNIQUE(run_id,request_key),
 FOREIGN KEY(payload_ref,run_id) REFERENCES agent_content(id,run_id)
);
CREATE TRIGGER agent_event_no_update BEFORE UPDATE ON agent_event
BEGIN SELECT RAISE(ABORT, 'agent events are append-only'); END;
CREATE TRIGGER agent_event_no_delete BEFORE DELETE ON agent_event
BEGIN SELECT RAISE(ABORT, 'agent events are append-only'); END;

CREATE TABLE agent_wakeup (
 run_id TEXT PRIMARY KEY REFERENCES agent_run(id),
 generation INTEGER NOT NULL CHECK(generation > 0),
 available_at TEXT NOT NULL
);
