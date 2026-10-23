-- A remembered buyer is an owner preference, not permission to charge a merchant.
CREATE TABLE mock_payment_profile (
  tenant_id TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  buyer_id TEXT NOT NULL CHECK (buyer_id IN ('demo-buyer','demo-buyer-alt')),
  updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, owner_id)
);
-- Preserve historical orders and their frozen provider payloads with a null buyer.
ALTER TABLE mock_commerce_order ADD COLUMN buyer_id TEXT
  CHECK (buyer_id IN ('demo-buyer','demo-buyer-alt'));
ALTER TABLE mock_commerce_order ADD COLUMN buyer_required INTEGER NOT NULL DEFAULT 0
  CHECK (buyer_required IN (0,1));
