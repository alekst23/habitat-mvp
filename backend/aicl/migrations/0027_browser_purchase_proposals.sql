-- Observed browser evidence and an owner-reviewed recommendation, never an order.
CREATE TABLE browser_purchase_proposal (
 id TEXT PRIMARY KEY,
 tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
 instance_id TEXT NOT NULL REFERENCES agent_instance(id),
 workflow_run_id TEXT NOT NULL REFERENCES mock_workflow_run(id),
 deliverable_id TEXT NOT NULL UNIQUE REFERENCES mock_workflow_deliverable(id),
 seller TEXT NOT NULL, domain TEXT NOT NULL,
 amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
 currency TEXT NOT NULL CHECK(currency = 'USD'),
 description TEXT NOT NULL, rationale TEXT NOT NULL, evidence_json TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','approved','declined','superseded')),
 version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, decided_at TEXT
);
CREATE INDEX browser_purchase_proposal_inbox ON browser_purchase_proposal(tenant_id,owner_id,state,created_at);
CREATE INDEX browser_purchase_proposal_job ON browser_purchase_proposal(workflow_run_id);
CREATE TRIGGER browser_purchase_proposal_snapshot_immutable BEFORE UPDATE ON browser_purchase_proposal
WHEN NEW.id != OLD.id OR NEW.tenant_id != OLD.tenant_id OR NEW.owner_id != OLD.owner_id
 OR NEW.instance_id != OLD.instance_id OR NEW.workflow_run_id != OLD.workflow_run_id
 OR NEW.deliverable_id != OLD.deliverable_id
 OR NEW.seller != OLD.seller OR NEW.domain != OLD.domain OR NEW.amount_minor != OLD.amount_minor
 OR NEW.currency != OLD.currency OR NEW.description != OLD.description OR NEW.rationale != OLD.rationale
 OR NEW.evidence_json != OLD.evidence_json OR NEW.created_at != OLD.created_at
BEGIN SELECT RAISE(ABORT, 'purchase proposal evidence is immutable'); END;
