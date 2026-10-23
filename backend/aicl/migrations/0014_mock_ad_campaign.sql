-- Fixed local advertising fixtures. Money is prepaid once; daily consumption is
-- tracked separately from the commerce ledger and never creates another charge.
CREATE TABLE mock_ad_campaign (
 id TEXT PRIMARY KEY,
 instance_id TEXT NOT NULL REFERENCES agent_instance(id),
 offer_id TEXT NOT NULL,
 workflow_run_id TEXT NOT NULL REFERENCES mock_workflow_run(id),
 total_cap_minor INTEGER NOT NULL CHECK (total_cap_minor > 0),
 daily_cap_minor INTEGER NOT NULL CHECK (daily_cap_minor > 0),
 duration_days INTEGER NOT NULL DEFAULT 3 CHECK (duration_days > 0),
 started_at TEXT, completed_at TEXT, created_at TEXT NOT NULL,
 UNIQUE(instance_id, offer_id)
);
CREATE TABLE mock_ad_day (
 id TEXT PRIMARY KEY,
 campaign_id TEXT NOT NULL REFERENCES mock_ad_campaign(id),
 day_key TEXT NOT NULL,
 day_number INTEGER NOT NULL,
 reported_at TEXT NOT NULL,
 spend_minor INTEGER NOT NULL CHECK (spend_minor >= 0),
 impressions INTEGER NOT NULL, clicks INTEGER NOT NULL, installs INTEGER NOT NULL,
 workflow_run_id TEXT NOT NULL REFERENCES mock_workflow_run(id),
 UNIQUE(campaign_id, day_key), UNIQUE(campaign_id, day_number)
);
