# Spike: Cloud Browser — Feasibility Findings

**Ticket:** E2-1 (issue #3)  
**Epic:** E2 (issue #2)  
**Date:** 2026-10-06  
**Spike scope:** Evaluate hosted cloud browser options for Playwright recipes with stored sessions; document cost, rate limits, and go/no-go recommendation.

## Summary

**Go/No-Go:** ✅ GO — Browserbase is the recommended option. It supports Playwright natively, stored sessions (contexts), and has a free tier sufficient for development. Browserless is a viable alternative.

---

## Findings

### Options evaluated

1. **Browserbase** (https://www.browserbase.com/)
2. **Browserless** (https://www.browserless.io/)
3. **Playwright Cloud / Microsoft Playwright Testing** (https://playwright.microsoft.com/)

---

### Option 1: Browserbase

**Playwright support:** ✅ Native — Browserbase provides a Playwright-compatible endpoint. Connect via:
```python
from playwright.sync_api import sync_playwright
import browserbase

bb = browserbase.Browserbase(api_key=API_KEY)
session = bb.sessions.create(project_id=PROJECT_ID)

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(session.connect_url)
```

**Stored sessions:** ✅ Supported — Browserbase supports persistent browser contexts ("sessions") that preserve cookies, localStorage, and authentication state across runs. This is the mechanism for storing Reddit Ads login sessions.

**Cost:**
- Free tier: 1,000 session minutes/month, 1 concurrent session
- Hobby: $49/month — 10,000 session minutes, 3 concurrent sessions
- For the hackathon: free tier is sufficient for development; Hobby tier for demo if needed.

**Rate limits:**
- Free tier: 1 concurrent session
- Sessions time out after 60 minutes of inactivity (configurable on paid plans)
- No hard request rate limit documented for Playwright operations

**Session storage for Reddit Ads:**
- Create a Browserbase session, log in to Reddit Ads manually once, save the session ID.
- Subsequent runs reuse the session (cookies preserved) — no re-login required.
- Session expiry: Browserbase sessions persist until explicitly deleted or expired by the browser (Reddit Ads session cookies).

**Verdict:** ✅ Recommended primary option.

---

### Option 2: Browserless

**Playwright support:** ✅ Supported — Browserless provides a WebSocket endpoint compatible with Playwright:
```python
browser = await p.chromium.connect_over_cdp("wss://chrome.browserless.io?token=TOKEN")
```

**Stored sessions:** ⚠️ Partial — Browserless supports persistent user data directories on self-hosted deployments. The cloud offering has limited session persistence; cookies must be managed manually (save/restore via Playwright's `storage_state`).

**Cost:**
- Free tier: 6 hours/month
- Starter: $49/month — 20 hours/month
- For the hackathon: free tier is very limited; Starter is needed for meaningful testing.

**Rate limits:**
- 1 concurrent session on free/Starter
- 30-second default timeout (configurable)

**Verdict:** ⚠️ Viable alternative, but session persistence is more complex than Browserbase.

---

### Option 3: Microsoft Playwright Testing

**Playwright support:** ✅ Native — designed specifically for Playwright test parallelization.

**Stored sessions:** ❌ Not designed for this use case — focused on test execution, not persistent browser sessions for automation.

**Cost:** Pay-per-minute; free tier available for Azure subscribers.

**Verdict:** ❌ Not suitable — designed for test parallelization, not persistent automation sessions.

---

## Recommendation

**Primary:** Browserbase
- Native Playwright support
- Persistent sessions (stored Reddit Ads login)
- Free tier sufficient for development
- Simple API

**Fallback:** Browserless with manual `storage_state` management

## Integration approach for Habitat

- The `web-research-proxy` service will manage Browserbase sessions.
- Reddit Ads browser recipe:
  1. On first use: create a Browserbase session, navigate to Reddit Ads, complete OAuth login, save session ID to secrets-service.
  2. On subsequent uses: retrieve session ID from secrets-service, connect to existing Browserbase session, execute recipe.
  3. If session expired: re-authenticate and update secrets-service.
- The session ID is a secret — stored in secrets-service, never in agent context.

## Go/No-Go Decision

**Cloud browser (Browserbase):** ✅ GO
- Confirmed Playwright support with stored sessions.
- Free tier sufficient for hackathon development.
- Session persistence model is compatible with Habitat's secrets-service architecture.

## Open questions resolved

- **Q3 from spec.md:** Cloud browser service selection → **Browserbase (primary), Browserless (fallback).**
