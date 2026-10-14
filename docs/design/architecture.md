# AICL shared architecture context

AICL manages configurable instances of predefined templates. Default is the initial template. It receives no direct credentials and cannot bypass the AICL control plane.

## Shared boundaries

- Authenticated server sessions derive owner and tenant identity (`AuthContext`, tenant equals owner in the MVP); client tenant fields are ignored or rejected.
- A canonical instance-creation service (E11-2) is used by the wizard, first-party web-app tools, and built-in chat.
- Connections and encrypted credentials remain outside agent context and outside every tool, chat and UI result. A capability may use a connection only after explicit owner attachment, and only the credential broker applies it.
- One dispatch gate (`WorkAuthorization`, E11-2) is the only path to inference, compute, provider or network use. It combines lifecycle, capability, per-action confirmation, connection, network and budget checks in a fixed fail-closed order.
- The budget controller reserves estimated USD (integer micro-USD) before inference or compute, settles measured token/minute usage using the applied versioned price table, and fails closed.
- Network authorization uses capability-owned fixed allow-lists plus owner-added exact HTTPS domains only for `network.fetch`, with an SSRF guard.
- Real providers, real inference and real compute are not enabled; the only composition is deterministic fake ports and startup rejects anything else.

## Application stack and layout (design choice, E11-1 establishes it)

This is a design choice for the application foundation, kept small and consistent with the repository: Python 3.12 (the repository's workflow language), FastAPI with Uvicorn, Jinja2 server-rendered pages with minimal vanilla JS, SQLite via the standard `sqlite3` module (WAL, foreign keys on) with plain SQL migration files, pydantic v2 for contracts, pytest as the `backend/` verify runner, and Playwright 1.63.0 (exact pin, as the browser harness requires) for browser journeys. No ORM and no front-end build step. Python dependencies are pinned in `backend/requirements.txt`; the only Node dependency is `@playwright/test` 1.63.0 in the root `package.json` with a committed `package-lock.json`. No new secret is introduced by this design.

```text
backend/
  requirements.txt            pinned runtime and test dependencies
  aicl/
    app.py                    create_app(settings): the only composition root
    settings.py               loads and validates the configuration table
    db.py, migrations/*.sql   connection, transaction helper, forward-only migrations
    control/                  E11-1: auth ports, instances, budget, price table, audit, confirmations
    creation/                 E11-2: create_instance, InstanceOperations, tool registry
    connections/, network/, work/    E11-2: connections, OAuth port, secret store, broker, SSRF guard, gate, executor port and fake
    web/                      E11-3, E11-4, E11-5: routes, templates, session auth, chat, pages
    test_server.py            test composition entry point (test mode only)
  tests/
    unit/                     pure logic: cost math, transitions, host rules, state machine
    integration/              real SQLite and the real services with fake leaf ports; HTTP through TestClient
tests/browser/                Playwright journeys (the existing harness location)
.env.example                  safe placeholders only
```

Persistence and transactions: one SQLite file; every write operation is one `BEGIN IMMEDIATE` transaction that includes its audit append; a lock timeout is `unavailable` and denies. `UPDATE` and `DELETE` are blocked by triggers on the audit, price-table and usage tables. Migrations run at startup, are forward-only and recorded in a `schema_migration` table.

### Test layers (lean)

Unit tests cover pure functions only. Integration tests run the real services against a temporary SQLite database with fake leaf ports and a controllable `Clock`; one test proves several scenarios and ACs (for example one reservation test proves F1-S3, F1-S10 and F1-S12 together). Browser tests are limited to the production-wired journeys listed in the experience document and each carries `ac` annotations. No test duplicates an assertion across layers, no live network or provider is used, and no coverage quota applies.

### Commands, fixtures and Playwright startup

`python -m aicl.test_server` starts `create_app` with the test settings (below), a temporary database under `.ctx/tmp/`, the fake ports, a seeded price table, the capture mail sender, a fixed clock option (`GET /__test__/clock`, test mode only) and seeded fixture owners, then serves on `127.0.0.1:4173`. `npm run start:test` (script in the root `package.json`) runs exactly `python -m aicl.test_server` with `PYTHONPATH=backend`, so the existing Playwright configuration works unchanged. Fixtures are created through the real sign-in using the captured link (`/__test__/last-magic-link`); there are no password or bypass accounts and no test-only login route. Each journey uses a fresh email address; the database is deleted when the server stops.

These are the argv arrays a later maintainer-authorized foundation change would place in `.gitlab/ctx/commands.yml` (this design does not edit that file; see the access note in the epic). Each needs the stack above installed with `python -m pip install -r backend/requirements.txt` in the runner image and must write its evidence to `CTX_OUTPUT`:

| Adapter | argv (no shell) | Notes |
|---|---|---|
| `verify` | `["python", "-m", "pytest", "backend/tests", "-q", "--junitxml=.ctx/tmp/backend-junit.xml"]` plus a reviewed small evidence writer that converts the JUnit file to the `verify` evidence schema (`source_sha`, `report_url`, `tests_total`, `passed`) | The runner and evidence writer are the maintainer-reviewed part |
| browser | `["npx", "--no-install", "playwright", "test", "--config", ".gitlab/ctx/playwright.config.ts"]` (the `ctx:browser` job already runs this after `npm ci`) | Needs `package-lock.json`, `npm run start:test` and Python dependencies in the Playwright image or an added install step; both are foundation items |
| other adapters (`source-security`, `package`, `artifact-security`, `configure`) | unchanged and out of scope | The application has no deployment target |

## Consolidated configuration

One table for the whole application. Owner is the ticket that implements the variable. "Required" means startup fails when missing or invalid; every secret is required and has no default. `.env.example` contains only the placeholders shown, never a real value.

| Variable | Owner | Required | Startup vs runtime | Safe default / `.env.example` value |
|---|---|---|---|---|
| `AICL_ENVIRONMENT` | E11-3 | yes | Startup: one of `development`, `test`, `production`; anything else fails | `development` |
| `AICL_TEST_MODE` | E11-3 | no | Startup: `1` only valid with `AICL_ENVIRONMENT=test`; otherwise fails startup | `0` |
| `AICL_PUBLIC_BASE_URL` | E11-2 | yes | Startup: absolute URL, `https` unless environment is `test` or `development` on localhost | `http://127.0.0.1:4173` |
| `AICL_DATABASE_URL` | E11-1 | yes | Startup: `sqlite:///path` must be writable; migration failure fails startup | `sqlite:///.ctx/tmp/aicl.db` |
| `AICL_SESSION_SECRET` | E11-3 | yes (secret) | Startup: at least 32 bytes; no default | placeholder `CHANGE_ME_32_BYTES_MINIMUM` is rejected at startup |
| `AICL_SECRET_ENCRYPTION_KEY` | E11-2 | yes (secret) | Startup: base64 of 32 bytes; at use a failed decrypt denies | placeholder `CHANGE_ME_BASE64_32_BYTES` is rejected at startup |
| `AICL_PRICE_TABLE_PATH` | E11-1 | yes | Startup: valid, effective table required; at use a missing price denies | `backend/aicl/price_table.example.json` |
| `AICL_SESSION_TTL_SECONDS` | E11-3 | no | Startup: integer 300 to 604800 | `28800` |
| `AICL_MAGIC_LINK_TTL_SECONDS` | E11-3 | no | Startup: integer 60 to 3600 | `900` |
| `AICL_SMTP_HOST`, `AICL_SMTP_PORT`, `AICL_SMTP_USERNAME`, `AICL_SMTP_PASSWORD`, `AICL_SMTP_FROM` | E11-3 | host and from required unless test composition | Startup: missing host fails unless `AICL_TEST_MODE=1` and environment `test`; delivery failure at runtime is silent to the requester and audited | empty |
| `AICL_CONFIRMATION_TTL_SECONDS` | E11-1 | no | Startup: integer 30 to 3600 | `300` |
| `AICL_RECONCILE_INTERVAL_SECONDS` | E11-1 | no | Startup: integer 5 to 3600 | `60` |
| `AICL_HOLD_STALE_SECONDS` | E11-2 | no | Startup: integer 60 to 86400 | `900` |
| `AICL_EXECUTOR_TIMEOUT_SECONDS` | E11-2 | no | Startup: integer 1 to 300 | `30` |
| `AICL_PROVIDER_MODE` | E11-2 | no | Startup: only `fake` accepted; any other value fails with "provider enablement is not recorded" | `fake` |
| `AICL_EXECUTOR_MODE` | E11-2 | no | Startup: only `fake` accepted | `fake` |
| `AICL_CHAT_MODEL_MODE` | E11-4 | no | Startup: only `fake` accepted | `fake` |

Rules: secrets and the SMTP password are read from the environment only, never from files in the repository, and never logged or echoed (startup errors name the variable, not the value). The deny-at-use rows are the runtime behavior stated in each feature document (unavailable budget state, missing price, unavailable secret, missing policy); every other row is validated at startup. Test mode needs both `AICL_TEST_MODE=1` and `AICL_ENVIRONMENT=test`, and the capture route and in-memory mail list exist only in that composition.

## Non-goals

No PayPal or payment capture, public MCP API, BYOA sandbox, arbitrary user code, direct provider credentials, provider enablement, deployment, or live spend.
