-- Close access issued by the former public demo before enabling the private link.
-- A zero-duration workspace is expired for both browser and machine work guards.
-- Keep owners, agents, audit history and all accounting records intact.
UPDATE judge_demo_workspace SET expires_at = created_at;
UPDATE session SET revoked_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE revoked_at IS NULL AND owner_id IN (SELECT owner_id FROM judge_demo_workspace);
