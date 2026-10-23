-- A remote mock capture is a durable saga: never release unknown payment holds.
-- Historical local fixtures keep their transport and existing receipts unchanged.
ALTER TABLE mock_commerce_order ADD COLUMN payment_transport TEXT NOT NULL DEFAULT 'inline_fixture'
  CHECK (payment_transport IN ('inline_fixture', 'http_mock'));
ALTER TABLE mock_commerce_order ADD COLUMN provider_order_id TEXT;
ALTER TABLE mock_commerce_order ADD COLUMN payment_phase TEXT NOT NULL DEFAULT 'not_started'
  CHECK (payment_phase IN ('not_started','inflight','unknown','created','pending','completed','cancelled'));
ALTER TABLE mock_commerce_order ADD COLUMN payment_binding_json TEXT;
ALTER TABLE mock_commerce_order ADD COLUMN payment_attempt_id TEXT;
CREATE UNIQUE INDEX mock_payment_provider_order ON mock_commerce_order(provider_order_id)
  WHERE provider_order_id IS NOT NULL;
