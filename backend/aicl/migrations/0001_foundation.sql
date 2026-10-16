CREATE TABLE agent_instance (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, template_id TEXT NOT NULL,
  name TEXT NOT NULL, instructions TEXT NOT NULL,
  lifecycle TEXT NOT NULL CHECK (lifecycle IN ('draft','active','paused','archived')),
  gated_reason TEXT, gate_context TEXT, version INTEGER NOT NULL DEFAULT 1,
  inference_daily_micro_usd INTEGER NOT NULL DEFAULT 0, inference_monthly_micro_usd INTEGER NOT NULL DEFAULT 0,
  compute_daily_micro_usd INTEGER NOT NULL DEFAULT 0, compute_monthly_micro_usd INTEGER NOT NULL DEFAULT 0,
  network_domains TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX agent_instance_tenant ON agent_instance (tenant_id);
CREATE TABLE capability_grant (
  instance_id TEXT NOT NULL REFERENCES agent_instance(id), capability TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (instance_id, capability)
);
CREATE TABLE price_table_version (
  version TEXT PRIMARY KEY, effective_from TEXT NOT NULL, sha256 TEXT NOT NULL, imported_at TEXT NOT NULL
);
CREATE TABLE price_rate (
  version TEXT NOT NULL REFERENCES price_table_version(version), meter TEXT NOT NULL,
  unit_size INTEGER NOT NULL CHECK (unit_size > 0), micro_usd INTEGER NOT NULL CHECK (micro_usd >= 0),
  PRIMARY KEY (version, meter)
);
CREATE TRIGGER price_table_version_no_update BEFORE UPDATE ON price_table_version
BEGIN SELECT RAISE(ABORT, 'price_table_version is insert-only'); END;
CREATE TRIGGER price_table_version_no_delete BEFORE DELETE ON price_table_version
BEGIN SELECT RAISE(ABORT, 'price_table_version is insert-only'); END;
CREATE TRIGGER price_rate_no_update BEFORE UPDATE ON price_rate
BEGIN SELECT RAISE(ABORT, 'price_rate is insert-only'); END;
CREATE TRIGGER price_rate_no_delete BEFORE DELETE ON price_rate
BEGIN SELECT RAISE(ABORT, 'price_rate is insert-only'); END;
CREATE TABLE budget_hold (
  id TEXT PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES agent_instance(id), work_id TEXT NOT NULL,
  price_table_version TEXT NOT NULL REFERENCES price_table_version(version),
  est_input_tokens INTEGER NOT NULL, est_output_tokens INTEGER NOT NULL, est_compute_minutes INTEGER NOT NULL,
  inference_micro_usd INTEGER NOT NULL, compute_micro_usd INTEGER NOT NULL,
  window_day TEXT NOT NULL, window_month TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('held','settled','released','unknown')),
  created_at TEXT NOT NULL, state_changed_at TEXT NOT NULL, UNIQUE (instance_id, work_id)
);
CREATE TABLE budget_usage (
  hold_id TEXT PRIMARY KEY REFERENCES budget_hold(id), instance_id TEXT NOT NULL,
  inference_input_tokens INTEGER NOT NULL, inference_output_tokens INTEGER NOT NULL,
  compute_minutes INTEGER NOT NULL, inference_micro_usd INTEGER NOT NULL, compute_micro_usd INTEGER NOT NULL,
  price_table_version TEXT NOT NULL, window_day TEXT NOT NULL, window_month TEXT NOT NULL, recorded_at TEXT NOT NULL
);
CREATE TABLE audit_event (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, event_type TEXT NOT NULL,
  actor_kind TEXT NOT NULL, outcome TEXT NOT NULL, tenant_id TEXT, owner_id TEXT, instance_id TEXT,
  connection_id TEXT, reason TEXT, details TEXT NOT NULL DEFAULT '{}', occurred_at TEXT NOT NULL
);
CREATE INDEX audit_event_tenant ON audit_event (tenant_id, instance_id, seq);
CREATE TRIGGER audit_event_no_update BEFORE UPDATE ON audit_event
BEGIN SELECT RAISE(ABORT, 'audit_event is append-only'); END;
CREATE TRIGGER audit_event_no_delete BEFORE DELETE ON audit_event
BEGIN SELECT RAISE(ABORT, 'audit_event is append-only'); END;
CREATE TABLE pending_action (
  id TEXT PRIMARY KEY, instance_id TEXT NOT NULL, tenant_id TEXT NOT NULL, capability TEXT NOT NULL,
  payload_digest TEXT NOT NULL, preview TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE action_confirmation (
  id TEXT PRIMARY KEY, pending_action_id TEXT NOT NULL UNIQUE REFERENCES pending_action(id),
  instance_id TEXT NOT NULL, capability TEXT NOT NULL, payload_digest TEXT NOT NULL,
  owner_id TEXT NOT NULL, tenant_id TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  used_at TEXT
);
