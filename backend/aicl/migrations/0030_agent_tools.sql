-- Provider-hosted web search is a priced inference tool. Old requests retain
-- zero tool use, and the new version never becomes the fixture price default.
ALTER TABLE budget_hold ADD COLUMN est_web_search_calls INTEGER NOT NULL DEFAULT 0 CHECK (est_web_search_calls >= 0);
ALTER TABLE budget_usage ADD COLUMN web_search_calls INTEGER NOT NULL DEFAULT 0 CHECK (web_search_calls >= 0);
ALTER TABLE workflow_inference_attempt ADD COLUMN web_search_calls INTEGER NOT NULL DEFAULT 0 CHECK (web_search_calls >= 0);
ALTER TABLE workflow_inference_attempt ADD COLUMN tool_trace_json TEXT;

INSERT INTO price_table_version(version,effective_from,sha256,imported_at,explicit_only)
VALUES ('gpt-6-sol-web-2026-10-25','2026-10-25T00:00:00.000000Z','b906acbbeea3d5b1e6125369da92bc78923f053459a208faf8cc0ec7bf2652fa','2026-10-25T00:00:00.000000Z',1);
INSERT INTO price_rate(version,meter,unit_size,micro_usd) VALUES
 ('gpt-6-sol-web-2026-10-25','inference.input_tokens',1,2),
 ('gpt-6-sol-web-2026-10-25','inference.output_tokens',1,10),
 ('gpt-6-sol-web-2026-10-25','compute.minutes',1,0),
 ('gpt-6-sol-web-2026-10-25','inference.web_search_calls',1,10000);
