-- Snapshot the supported task inputs independently of later agent or draft edits.
ALTER TABLE mock_commerce_run ADD COLUMN brief_json TEXT NOT NULL DEFAULT
  '{"audience":"Owners exploring controlled agents for everyday work","goal":"Introduce Habitat and invite owners to try the local demo","product_name":"Habitat"}';
ALTER TABLE mock_commerce_account ADD COLUMN draft_brief_json TEXT NOT NULL DEFAULT '{}';
CREATE INDEX mock_commerce_run_current ON mock_commerce_run (instance_id, state);
