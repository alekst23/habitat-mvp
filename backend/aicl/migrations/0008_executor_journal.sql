CREATE TABLE executor_journal (
  hold_id TEXT PRIMARY KEY REFERENCES budget_hold(id),
  status TEXT NOT NULL CHECK (status IN ('started','succeeded','failed','not_started','unknown')),
  input_tokens INTEGER, output_tokens INTEGER, compute_minutes INTEGER,
  CHECK ((status IN ('succeeded','failed') AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL
          AND compute_minutes IS NOT NULL AND input_tokens >= 0 AND output_tokens >= 0 AND compute_minutes >= 0)
         OR (status IN ('started','not_started','unknown') AND input_tokens IS NULL
             AND output_tokens IS NULL AND compute_minutes IS NULL))
);
-- Previous versions kept executor state only in process memory. An existing pending
-- or unknown operation cannot safely be declared not-started after upgrade.
INSERT INTO executor_journal (hold_id, status)
SELECT h.id, 'unknown' FROM budget_hold h
WHERE h.state IN ('held','unknown') AND EXISTS
  (SELECT 1 FROM work_request_record w WHERE w.hold_id = h.id);
