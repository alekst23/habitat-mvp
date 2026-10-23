-- All records here are local simulations. No row represents PayPal or real money.
CREATE TABLE mock_commerce_account (
  instance_id TEXT PRIMARY KEY REFERENCES agent_instance(id),
  purchase_enabled INTEGER NOT NULL DEFAULT 0 CHECK (purchase_enabled IN (0,1)),
  purchase_limit_minor INTEGER NOT NULL DEFAULT 0 CHECK (purchase_limit_minor >= 0),
  version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE mock_commerce_run (
  id TEXT PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES agent_instance(id),
  tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, request_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('awaiting_approval','awaiting_checkout','payment_pending',
    'ready_to_resume','completed','declined','cancelled','expired')),
  output TEXT, inference_cost_micro_usd INTEGER NOT NULL DEFAULT 0,
  input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE (tenant_id, request_id)
);
CREATE TABLE mock_commerce_purchase (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES mock_commerce_run(id),
  instance_id TEXT NOT NULL REFERENCES agent_instance(id), tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
  quote_json TEXT NOT NULL, quote_digest TEXT NOT NULL, amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  state TEXT NOT NULL CHECK (state IN ('awaiting_approval','awaiting_checkout','payment_pending',
    'paid','declined','cancelled','expired')),
  quota_state TEXT NOT NULL CHECK (quota_state IN ('held','spent','released')),
  expires_at TEXT NOT NULL, approved_at TEXT, fulfillment_json TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE mock_commerce_order (
  id TEXT PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES agent_instance(id),
  tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
  purpose TEXT NOT NULL CHECK (purpose IN ('service_topup','agent_purchase')),
  request_id TEXT NOT NULL, purchase_id TEXT UNIQUE REFERENCES mock_commerce_purchase(id),
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0), currency TEXT NOT NULL CHECK (currency = 'USD'),
  merchant_id TEXT NOT NULL, merchant_name TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('created','pending','completed','cancelled')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE (tenant_id, purpose, request_id),
  CHECK ((purpose = 'service_topup' AND purchase_id IS NULL AND merchant_id = 'habitat-demo') OR
         (purpose = 'agent_purchase' AND purchase_id IS NOT NULL AND merchant_id = 'demo-template-shop'))
);
CREATE TABLE mock_commerce_receipt (
  id TEXT PRIMARY KEY, order_id TEXT NOT NULL UNIQUE REFERENCES mock_commerce_order(id),
  instance_id TEXT NOT NULL REFERENCES agent_instance(id),
  purpose TEXT NOT NULL CHECK (purpose IN ('service_topup','agent_purchase')),
  capture_id TEXT NOT NULL UNIQUE, merchant_id TEXT NOT NULL, merchant_name TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0), currency TEXT NOT NULL CHECK (currency = 'USD'),
  created_at TEXT NOT NULL
);
CREATE TABLE mock_commerce_ledger (
  id TEXT PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES agent_instance(id),
  kind TEXT NOT NULL CHECK (kind IN ('service_topup','inference_usage')),
  delta_micro_usd INTEGER NOT NULL, reference TEXT NOT NULL UNIQUE,
  receipt_id TEXT UNIQUE REFERENCES mock_commerce_receipt(id), hold_id TEXT UNIQUE REFERENCES budget_hold(id),
  created_at TEXT NOT NULL,
  CHECK ((kind = 'service_topup' AND delta_micro_usd > 0 AND receipt_id IS NOT NULL AND hold_id IS NULL) OR
         (kind = 'inference_usage' AND delta_micro_usd <= 0 AND receipt_id IS NULL AND hold_id IS NOT NULL))
);
CREATE INDEX mock_commerce_purchase_instance ON mock_commerce_purchase (instance_id, quota_state);
CREATE INDEX mock_commerce_ledger_instance ON mock_commerce_ledger (instance_id);
CREATE TRIGGER mock_receipt_no_update BEFORE UPDATE ON mock_commerce_receipt
BEGIN SELECT RAISE(ABORT, 'mock receipt is append-only'); END;
CREATE TRIGGER mock_receipt_no_delete BEFORE DELETE ON mock_commerce_receipt
BEGIN SELECT RAISE(ABORT, 'mock receipt is append-only'); END;
CREATE TRIGGER mock_ledger_no_update BEFORE UPDATE ON mock_commerce_ledger
BEGIN SELECT RAISE(ABORT, 'mock ledger is append-only'); END;
CREATE TRIGGER mock_ledger_no_delete BEFORE DELETE ON mock_commerce_ledger
BEGIN SELECT RAISE(ABORT, 'mock ledger is append-only'); END;
