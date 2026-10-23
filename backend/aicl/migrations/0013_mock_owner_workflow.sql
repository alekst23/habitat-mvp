-- Persistent owner-journey fixtures; this is not a production scheduler.
CREATE TABLE mock_workflow_config (
 instance_id TEXT PRIMARY KEY REFERENCES agent_instance(id),
 data_json TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
 next_due TEXT, demo_time TEXT, last_outcome TEXT,
 updated_at TEXT NOT NULL
);
CREATE TABLE mock_workflow_occurrence (
 id TEXT PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES agent_instance(id),
 scheduled_for TEXT NOT NULL, config_version INTEGER NOT NULL,
 state TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL,
 UNIQUE(instance_id, scheduled_for)
);
CREATE TABLE mock_workflow_run (
 id TEXT PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES agent_instance(id),
 occurrence_id TEXT NOT NULL REFERENCES mock_workflow_occurrence(id),
 commerce_run_id TEXT NOT NULL REFERENCES mock_commerce_run(id),
 spec_key TEXT NOT NULL, config_version INTEGER NOT NULL,
 config_json TEXT NOT NULL, spec_json TEXT NOT NULL,
 state TEXT NOT NULL, continuation TEXT NOT NULL DEFAULT 'schedule'
 CHECK (continuation IN ('now','schedule')),
 blocked_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE mock_workflow_purchase (
 purchase_id TEXT PRIMARY KEY REFERENCES mock_commerce_purchase(id),
 workflow_run_id TEXT NOT NULL REFERENCES mock_workflow_run(id)
);
CREATE TABLE mock_workflow_deliverable (
 id TEXT PRIMARY KEY, workflow_run_id TEXT NOT NULL REFERENCES mock_workflow_run(id),
 version INTEGER NOT NULL, content TEXT NOT NULL, criteria_json TEXT NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('needs_work','submitted','accepted','changes_requested')),
 feedback TEXT NOT NULL DEFAULT '', reviewed_at TEXT, created_at TEXT NOT NULL,
 UNIQUE(workflow_run_id,version)
);
CREATE INDEX mock_workflow_run_instance ON mock_workflow_run(instance_id,state);
CREATE INDEX mock_workflow_purchase_job ON mock_workflow_purchase(workflow_run_id);
