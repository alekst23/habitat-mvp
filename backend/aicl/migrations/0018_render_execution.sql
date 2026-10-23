-- The web service alone owns this database. Render workers use scoped APIs.
CREATE TABLE render_dispatch (
 id TEXT PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES agent_instance(id),
 scheduled_for TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('schedule','continuation')),
 continuation_run_id TEXT REFERENCES mock_workflow_run(id),
 config_json TEXT NOT NULL, state TEXT NOT NULL,
 hold_id TEXT UNIQUE REFERENCES budget_hold(id),
 task_run_id TEXT, occurrence_id TEXT REFERENCES mock_workflow_occurrence(id),
 created_at TEXT NOT NULL, offered_at TEXT, started_at TEXT, completed_at TEXT,
 reason TEXT, UNIQUE(instance_id,scheduled_for,kind)
);
CREATE INDEX render_dispatch_state ON render_dispatch(state,created_at);
CREATE TABLE render_dispatch_attempt (
 dispatch_id TEXT NOT NULL REFERENCES render_dispatch(id),
 attempt_id TEXT NOT NULL REFERENCES workflow_inference_attempt(id),
 result_json TEXT, completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0,1)),
 PRIMARY KEY(dispatch_id,attempt_id)
);
-- Estimate based on AICL-observed elapsed runtime at the maximum Flex rate.
-- It is an internal allowance, not a Render billing receipt.
CREATE TABLE render_compute_usage (
 dispatch_id TEXT PRIMARY KEY REFERENCES render_dispatch(id),
 instance_id TEXT NOT NULL REFERENCES agent_instance(id),
 hold_id TEXT NOT NULL UNIQUE REFERENCES budget_hold(id),
 elapsed_seconds INTEGER NOT NULL, charged_minutes INTEGER NOT NULL,
 cost_micro_usd INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TRIGGER render_compute_no_update BEFORE UPDATE ON render_compute_usage
BEGIN SELECT RAISE(ABORT, 'compute usage is append-only'); END;
CREATE TRIGGER render_compute_no_delete BEFORE DELETE ON render_compute_usage
BEGIN SELECT RAISE(ABORT, 'compute usage is append-only'); END;
INSERT INTO price_table_version(version,effective_from,sha256,imported_at,explicit_only)
VALUES ('render-flex-bound-2026-10-22','2026-10-22T00:00:00.000000Z','d7c1899322d588d54bfffefa42682230d77d78f2e2be72d44c13a9d83f36796c','2026-10-22T00:00:00.000000Z',1);
INSERT INTO price_rate(version,meter,unit_size,micro_usd) VALUES
 ('render-flex-bound-2026-10-22','inference.input_tokens',1,0),
 ('render-flex-bound-2026-10-22','inference.output_tokens',1,0),
 ('render-flex-bound-2026-10-22','compute.minutes',1,6667);
