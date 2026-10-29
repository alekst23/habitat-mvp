-- Runtime reservations share the canonical budget ledger, but only their owner
-- knows whether an interrupted operation was dispatched. Legacy recovery must
-- never interpret an absent legacy work record as proof of no charge.
CREATE TABLE agent_runtime_hold (
 hold_id TEXT PRIMARY KEY REFERENCES budget_hold(id),
 operation_id TEXT NOT NULL UNIQUE,
 tenant_id TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 instance_id TEXT NOT NULL REFERENCES agent_instance(id),
 created_at TEXT NOT NULL
);
CREATE INDEX agent_runtime_hold_instance ON agent_runtime_hold(instance_id);
CREATE TRIGGER agent_runtime_hold_scope BEFORE INSERT ON agent_runtime_hold
WHEN NOT EXISTS (
 SELECT 1 FROM budget_hold h JOIN agent_instance i ON i.id=h.instance_id
 WHERE h.id=NEW.hold_id AND i.id=NEW.instance_id
 AND i.tenant_id=NEW.tenant_id AND i.owner_id=NEW.owner_id
)
BEGIN SELECT RAISE(ABORT, 'runtime hold scope mismatch'); END;
CREATE TRIGGER agent_runtime_hold_no_update BEFORE UPDATE ON agent_runtime_hold
BEGIN SELECT RAISE(ABORT, 'runtime hold ownership is immutable'); END;
CREATE TRIGGER agent_runtime_hold_no_delete BEFORE DELETE ON agent_runtime_hold
BEGIN SELECT RAISE(ABORT, 'runtime hold ownership is immutable'); END;
