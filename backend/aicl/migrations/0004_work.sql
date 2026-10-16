CREATE TABLE work_request_record (
  tenant_id TEXT NOT NULL, work_id TEXT NOT NULL, request_digest TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('pending','succeeded','failed','unknown','released')),
  hold_id TEXT NOT NULL REFERENCES budget_hold(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, work_id)
);
CREATE INDEX work_request_record_hold ON work_request_record (hold_id);
