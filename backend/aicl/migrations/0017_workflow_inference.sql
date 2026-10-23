-- Pinned model prices must never become the default price for fixture work.
ALTER TABLE price_table_version ADD COLUMN explicit_only INTEGER NOT NULL DEFAULT 0 CHECK (explicit_only IN (0,1));
INSERT INTO price_table_version(version,effective_from,sha256,imported_at,explicit_only)
VALUES ('gpt-6-sol-2026-10-22','2026-10-22T00:00:00.000000Z','70174e72a0b7c1484ca49339e5cae99d74ed3eb09d0bec9f121ef7ccc3aa08d2','2026-10-22T00:00:00.000000Z',1);
INSERT INTO price_rate(version,meter,unit_size,micro_usd) VALUES
 ('gpt-6-sol-2026-10-22','inference.input_tokens',1,2),
 ('gpt-6-sol-2026-10-22','inference.output_tokens',1,10),
 ('gpt-6-sol-2026-10-22','compute.minutes',1,0);

-- One provider attempt per saved job version. Inflight/unknown attempts are never
-- automatically resent. A new occurrence cannot erase their reservation.
CREATE TABLE workflow_inference_attempt (
 id TEXT PRIMARY KEY, workflow_run_id TEXT NOT NULL REFERENCES mock_workflow_run(id),
 version INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','blocked','inflight','unknown','released','settled')),
 hold_id TEXT UNIQUE REFERENCES budget_hold(id),
 feedback TEXT NOT NULL DEFAULT '', max_cost_micro_usd INTEGER NOT NULL DEFAULT 52000,
 cost_micro_usd INTEGER, input_tokens INTEGER, output_tokens INTEGER,
 model TEXT NOT NULL DEFAULT 'gpt-6-sol', response_id TEXT,
 validation_method TEXT NOT NULL DEFAULT 'model_self_assessment_and_structural_checks',
 validation_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
-- A proven no-charge rejection can be retried on a later explicit occurrence,
-- with a fresh identity. All ambiguous/charged attempts remain unique forever.
CREATE UNIQUE INDEX workflow_inference_active_version ON workflow_inference_attempt(workflow_run_id,version) WHERE state != 'released';
CREATE INDEX workflow_inference_state ON workflow_inference_attempt(state);
