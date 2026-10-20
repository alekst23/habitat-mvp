CREATE TABLE create_request (
  tenant_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_digest TEXT NOT NULL,
  instance_id TEXT NOT NULL REFERENCES agent_instance(id), audit_event_id INTEGER NOT NULL,
  created_at TEXT NOT NULL, PRIMARY KEY (tenant_id, idempotency_key)
);
