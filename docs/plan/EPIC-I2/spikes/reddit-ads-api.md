# Spike: Reddit Ads API — Feasibility Findings

**Ticket:** E2-1 (issue #3)  
**Epic:** E2 (issue #2)  
**Date:** 2026-10-06  
**Spike scope:** Confirm API access requirements, OAuth scopes, campaign/budget API availability, and fallback path.

## Summary

**Go/No-Go:** ⚠️ CONDITIONAL GO — API access requires a developer app plus a separate approval step for Ads API access. The browser-recipe fallback is the safer first path and should be built in parallel.

---

## Findings

### 1. API access requirements

Source: https://ads.reddit.com/api/v3/docs and https://www.reddit.com/dev/api/

- Reddit Ads API (v3) requires a **Reddit developer app** (created at https://www.reddit.com/prefs/apps).
- Beyond the developer app, **Ads API access requires a separate approval** from Reddit's Ads API team. Teams must submit a request form; approval is not automatic and can take days to weeks.
- The approval gate is documented at https://ads.reddit.com/api/v3/docs under "Getting Started". Reddit states: "Access to the Reddit Ads API is not available to all advertisers by default."
- **Risk:** Approval may not arrive before the hackathon deadline. The browser-recipe fallback must be ready.

### 2. OAuth scopes available

- Reddit uses OAuth 2.0 with the following scopes relevant to Ads:
  - `ads:read` — read ad account data, campaigns, ad groups, ads, reports
  - `ads:write` — create and modify campaigns, ad groups, ads, budgets
  - `identity` — read the authenticated user's identity
- Scopes are requested during the OAuth authorization flow. The `ads:write` scope is required for campaign creation and budget-setting.
- Scope documentation: https://www.reddit.com/dev/api/oauth

### 3. Campaign creation and budget-setting via API

- **Yes, available via API** — once Ads API access is approved:
  - `POST /api/v3/campaigns` — create a campaign with lifetime budget, daily budget, objective
  - `POST /api/v3/adgroups` — create ad groups with targeting and bid
  - `POST /api/v3/ads` — create ads
  - Budget fields: `total_budget_cents` (lifetime), `daily_budget_cents` (daily cap)
- The API uses integer cent values for budgets, which aligns with Habitat's micro-dollar ledger model.
- Campaign status can be set to `PAUSED` at creation — this is the correct approach for judge mode.

### 4. Sandbox / test environment

- Reddit Ads API does **not** have a dedicated sandbox environment. All API calls operate against the live Ads platform.
- For testing: create campaigns in `PAUSED` state with minimal budgets. Reddit does not charge for paused campaigns.
- For judge mode: campaigns should be created as `PAUSED` and never activated, satisfying the "no real ad spend" requirement.

### 5. Rate limits

- Reddit Ads API rate limits are not fully published but are documented as: 60 requests/minute per OAuth token for most endpoints.
- Batch endpoints exist for some operations.

---

## Go/No-Go Decision

**Primary path (Reddit Ads API):** CONDITIONAL GO
- Requires Ads API approval from Reddit — submit the request immediately.
- If approval arrives before T-I6 (Marketing agent and action broker), use the API path.
- If approval does not arrive, use the browser-recipe fallback.

**Fallback path (browser recipe):** GO
- Use Playwright with a stored Reddit Ads session to create/pause campaigns via the web UI.
- This path does not require Ads API approval.
- Requires a cloud browser service (see cloud-browser.md findings).
- The browser recipe must be built regardless, as the API approval timeline is uncertain.

## Recommendation

1. Submit Reddit Ads API access request immediately.
2. Build the browser-recipe connector for T-I6 as the primary implementation path.
3. If API access is granted before T-I6 completes, add the API connector as an alternative.
4. Judge mode: always use `PAUSED` campaign state; never activate live spend.

## Open questions resolved

- **Q6 from spec.md:** Reddit Ads API vs. browser recipe → **Browser recipe is the primary path; API is conditional on approval.**
