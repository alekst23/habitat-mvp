-- Bind each checkout to its original provider and Sandbox payee; preserve all receipts.
-- Deferral allows rebuilding the referenced table within the migration transaction.
PRAGMA defer_foreign_keys = ON;
CREATE TABLE mock_commerce_order_next (
  id TEXT PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES agent_instance(id),
  tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
  purpose TEXT NOT NULL CHECK (purpose IN ('service_topup','agent_purchase')),
  request_id TEXT NOT NULL, purchase_id TEXT UNIQUE REFERENCES mock_commerce_purchase(id),
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0), currency TEXT NOT NULL CHECK (currency = 'USD'),
  merchant_id TEXT NOT NULL, merchant_name TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('created','pending','completed','cancelled')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  payment_transport TEXT NOT NULL DEFAULT 'inline_fixture' CHECK (payment_transport IN ('inline_fixture','http_mock','paypal_sandbox')),
  provider_order_id TEXT,
  provider_merchant_id TEXT, paypal_approval_url TEXT,
  payment_phase TEXT NOT NULL DEFAULT 'not_started'
    CHECK (payment_phase IN ('not_started','inflight','unknown','created','pending','completed','cancelled')),
  payment_binding_json TEXT, payment_attempt_id TEXT,
  buyer_id TEXT CHECK (buyer_id IN ('demo-buyer','demo-buyer-alt')),
  buyer_required INTEGER NOT NULL DEFAULT 0 CHECK (buyer_required IN (0,1)),
  UNIQUE (tenant_id, purpose, request_id),
  CHECK ((purpose = 'service_topup' AND purchase_id IS NULL AND merchant_id = 'habitat-demo') OR
         (purpose = 'agent_purchase' AND purchase_id IS NOT NULL AND
          merchant_id IN ('demo-template-shop','launchpad-ads-demo')))
);
INSERT INTO mock_commerce_order_next (
  id,instance_id,tenant_id,owner_id,purpose,request_id,purchase_id,amount_minor,currency,
  merchant_id,merchant_name,state,created_at,updated_at,payment_transport,provider_order_id,
  payment_phase,payment_binding_json,payment_attempt_id,buyer_id,buyer_required
) SELECT id,instance_id,tenant_id,owner_id,purpose,request_id,purchase_id,amount_minor,currency,
  merchant_id,merchant_name,state,created_at,updated_at,payment_transport,provider_order_id,
  payment_phase,payment_binding_json,payment_attempt_id,buyer_id,buyer_required
  FROM mock_commerce_order;
DROP TABLE mock_commerce_order;
ALTER TABLE mock_commerce_order_next RENAME TO mock_commerce_order;
CREATE UNIQUE INDEX mock_payment_provider_order ON mock_commerce_order(provider_order_id)
  WHERE provider_order_id IS NOT NULL;

-- SQLite retains deferred DROP-table counters even after an identical parent is
-- restored. Validate every actual FK before clearing only those stale counters.
-- The CHECK aborts the transaction on any broken link; no receipt is rewritten.
CREATE TEMP TABLE paypal_migration_integrity (violations INTEGER CHECK (violations = 0));
INSERT INTO paypal_migration_integrity SELECT COUNT(*) FROM pragma_foreign_key_check;
DROP TABLE paypal_migration_integrity;
PRAGMA defer_foreign_keys = OFF;
