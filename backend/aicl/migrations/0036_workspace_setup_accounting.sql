-- Provider usage remains immutable history for the global operator allowance.
-- Activation assigns settled setup usage to agent credit once; a reset waives
-- only identified uncharged settled attempts, never an unresolved reservation.
CREATE TABLE workspace_setup_reset (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES agent_workspace(id),
 request_id TEXT NOT NULL,
 reason TEXT NOT NULL,
 tenant_id TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(workspace_id,request_id)
);
CREATE TABLE workspace_setup_charge (
 attempt_id TEXT PRIMARY KEY REFERENCES assistant_inference_attempt(id),
 workspace_id TEXT NOT NULL REFERENCES agent_workspace(id),
 instance_id TEXT NOT NULL REFERENCES agent_instance(id),
 cost_micro_usd INTEGER NOT NULL CHECK(cost_micro_usd >= 0),
 created_at TEXT NOT NULL
);
CREATE INDEX workspace_setup_charge_instance ON workspace_setup_charge(instance_id);
CREATE TABLE workspace_setup_waiver (
 attempt_id TEXT PRIMARY KEY REFERENCES assistant_inference_attempt(id),
 workspace_id TEXT NOT NULL REFERENCES agent_workspace(id),
 reset_id TEXT NOT NULL REFERENCES workspace_setup_reset(id),
 cost_micro_usd INTEGER NOT NULL CHECK(cost_micro_usd >= 0),
 created_at TEXT NOT NULL
);
CREATE INDEX workspace_setup_waiver_workspace ON workspace_setup_waiver(workspace_id);
CREATE TRIGGER workspace_setup_reset_scope BEFORE INSERT ON workspace_setup_reset
WHEN NOT EXISTS (SELECT 1 FROM agent_workspace w WHERE w.id=NEW.workspace_id
 AND w.tenant_id=NEW.tenant_id AND w.owner_id=NEW.owner_id)
BEGIN SELECT RAISE(ABORT, 'setup reset scope mismatch'); END;
CREATE TRIGGER workspace_setup_charge_scope BEFORE INSERT ON workspace_setup_charge
WHEN NOT EXISTS (SELECT 1 FROM agent_workspace w JOIN assistant_turn t ON t.session_id=w.session_id
 JOIN assistant_inference_attempt a ON a.turn_id=t.id WHERE w.id=NEW.workspace_id
 AND w.instance_id=NEW.instance_id AND a.id=NEW.attempt_id AND a.state='settled'
 AND a.tenant_id=w.tenant_id AND a.owner_id=w.owner_id AND a.cost_micro_usd=NEW.cost_micro_usd)
 OR EXISTS (SELECT 1 FROM workspace_setup_waiver WHERE attempt_id=NEW.attempt_id)
BEGIN SELECT RAISE(ABORT, 'setup charge scope or outcome mismatch'); END;
CREATE TRIGGER workspace_setup_waiver_scope BEFORE INSERT ON workspace_setup_waiver
WHEN NOT EXISTS (SELECT 1 FROM agent_workspace w JOIN assistant_turn t ON t.session_id=w.session_id
 JOIN assistant_inference_attempt a ON a.turn_id=t.id JOIN workspace_setup_reset r ON r.id=NEW.reset_id
 WHERE w.id=NEW.workspace_id AND r.workspace_id=w.id AND a.id=NEW.attempt_id AND a.state='settled'
 AND a.tenant_id=w.tenant_id AND a.owner_id=w.owner_id AND a.cost_micro_usd=NEW.cost_micro_usd)
 OR EXISTS (SELECT 1 FROM workspace_setup_charge WHERE attempt_id=NEW.attempt_id)
BEGIN SELECT RAISE(ABORT, 'setup waiver scope or outcome mismatch'); END;
CREATE TRIGGER workspace_setup_charge_no_update BEFORE UPDATE ON workspace_setup_charge
BEGIN SELECT RAISE(ABORT, 'setup charge is append-only'); END;
CREATE TRIGGER workspace_setup_charge_no_delete BEFORE DELETE ON workspace_setup_charge
BEGIN SELECT RAISE(ABORT, 'setup charge is append-only'); END;
CREATE TRIGGER workspace_setup_waiver_no_update BEFORE UPDATE ON workspace_setup_waiver
BEGIN SELECT RAISE(ABORT, 'setup waiver is append-only'); END;
CREATE TRIGGER workspace_setup_waiver_no_delete BEFORE DELETE ON workspace_setup_waiver
BEGIN SELECT RAISE(ABORT, 'setup waiver is append-only'); END;
CREATE TRIGGER workspace_setup_reset_no_update BEFORE UPDATE ON workspace_setup_reset
BEGIN SELECT RAISE(ABORT, 'setup reset is append-only'); END;
CREATE TRIGGER workspace_setup_reset_no_delete BEFORE DELETE ON workspace_setup_reset
BEGIN SELECT RAISE(ABORT, 'setup reset is append-only'); END;
