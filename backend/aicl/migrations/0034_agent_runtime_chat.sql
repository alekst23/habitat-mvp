-- Owner chat links one admitted run. Ownership is resolved from authenticated
-- assistant session and run records, never from client-supplied tenant IDs.
CREATE TABLE agent_chat_run (
 session_id TEXT PRIMARY KEY REFERENCES assistant_session(id),
 run_id TEXT NOT NULL UNIQUE REFERENCES agent_run(id),
 created_at TEXT NOT NULL
);
CREATE TRIGGER agent_chat_run_scope BEFORE INSERT ON agent_chat_run
WHEN NOT EXISTS (
 SELECT 1 FROM assistant_session s JOIN agent_run r ON r.id=NEW.run_id
 WHERE s.id=NEW.session_id AND s.tenant_id=r.tenant_id AND s.owner_id=r.owner_id
)
BEGIN SELECT RAISE(ABORT, 'chat run scope mismatch'); END;
ALTER TABLE agent_step ADD COLUMN receipt_metadata_json TEXT NOT NULL DEFAULT '{}'
 CHECK(json_valid(receipt_metadata_json));
