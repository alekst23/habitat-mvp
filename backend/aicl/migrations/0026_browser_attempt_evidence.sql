-- Bounded website observations are separate from encrypted authentication state.
CREATE TABLE browser_attempt_evidence (
 attempt_id TEXT PRIMARY KEY REFERENCES workflow_inference_attempt(id),
 workflow_run_id TEXT NOT NULL REFERENCES mock_workflow_run(id),
 request_id TEXT NOT NULL REFERENCES owner_request(id),
 evidence_json TEXT NOT NULL,
 observed_at TEXT NOT NULL
);
