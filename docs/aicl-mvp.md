# Running and using the AICL MVP

E11 provides a server-rendered FastAPI application backed by SQLite. Its owner
controls and audit records are implemented. Its built-in chat, Gmail/Reddit OAuth
and work executor use deterministic fakes. “Work succeeded” in this prototype
means a simulated outcome was recorded; it does not mean a model was called, an
email was sent or a Reddit post was created.

## Local demonstration

Follow the [README setup](../README.md#run-locally). The test server binds only to
`127.0.0.1:4173`, creates a temporary database below `backend/.ctx/tmp/`, supplies
test secrets and captures sign-in mail in memory. Its `__test__` endpoints are
available only with both `AICL_ENVIRONMENT=test` and `AICL_TEST_MODE=1`. Do not use
this composition as a hosted service. Restarting clears the demonstration state.

1. Request a magic link on the landing/sign-in page. Open
   `/__test__/last-magic-link?email=demo%40example.test` for the address used, then
   open the returned URL and confirm sign-in. Links expire and are single use;
   logout revokes the session.
2. Choose **Create with wizard** or **Create with chat**. Both create the same
   Default instance from a name, instructions and enabled capabilities. Chat is a
   guided scripted conversation, not an LLM. Creation leaves the instance in
   `draft` with all four budget limits at zero.
3. Open the instance from the workspace. Enable the desired capability, set
   positive daily and monthly limits for both inference and compute, and activate
   the instance. The displayed amounts are USD control limits, not funded cash.
4. Use the simulated-work form. An enabled, authorized request reserves its
   estimate, records the simulated measured usage and settles the reservation.
   Reload the detail page to see the new usage and redacted audit entries.
5. In **Connections**, connect fake Gmail or Reddit, then explicitly attach the
   connection to the appropriate enabled capability on the instance. The fake
   consent redirect exercises the application flow without contacting the provider.
   A `gmail.send` or `reddit.post` request needs an owner confirmation bound to its
   payload. Reload after the initial denial to see the pending action, confirm it,
   then resubmit the same payload. It cannot approve itself or reuse a consumed
   confirmation for new work.
6. Try an exhausted limit or a revoked connection. The page shows the denial and
   persisted gate. Fix the control and use **Re-check and clear** when needed; it
   cannot clear a still-invalid control. Pause prevents new work, archive is final,
   and historical activity remains visible.

For `network.fetch`, add exact HTTPS hostnames in the instance's domain controls;
wildcards and private/reserved destinations are denied. Authorization is exercised
with a fake resolver and executor; an owner-added host absent from the fake
resolver table still fails resolution. This does not prove transport-level
enforcement for a future real HTTP client.

## Persistent local configuration and sign-in mail

The `.env.example` values are placeholders and startup rejects them. There is no
automatic dotenv loader. For persistent local development, create an ignored
configuration file, keep the database and keys together, and load it into the
environment before starting the app. This command writes new secrets to the file
without printing them and refuses to overwrite an existing file:

```sh
python - <<'PY'
import base64
import os
import secrets
from pathlib import Path

destination = Path('.ctx/local.env')
destination.parent.mkdir(exist_ok=True)
values = Path('.env.example').read_text()
values = values.replace('CHANGE_ME_32_BYTES_MINIMUM', secrets.token_urlsafe(32))
values = values.replace('CHANGE_ME_IDENTITY_32_BYTES_MIN', secrets.token_urlsafe(32))
values = values.replace('CHANGE_ME_BASE64_32_BYTES', base64.b64encode(secrets.token_bytes(32)).decode())
fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as output:
    output.write(values)
PY
```

Edit `.ctx/local.env` to configure an SMTP host, port and sender. Set username and
password when the server requires authentication. Quote shell-sensitive values in
this local file. The current sender uses STARTTLS before login when a username is
configured; it does not implement implicit TLS/SMTPS. Use a development mailbox
or an SMTP service you intend to send through. Failed delivery gives the same
generic sign-in response and records an audit event, so a successful request page
alone does not prove mail arrived.

```sh
set -a
source .ctx/local.env
set +a
PYTHONPATH=backend python - <<'PY'
import os
import uvicorn
from aicl.app import create_app
from aicl.settings import Settings

uvicorn.run(create_app(Settings.from_env(os.environ)), host='127.0.0.1', port=4173)
PY
```

This development composition uses SMTP and persistent SQLite; it does not expose
captured-link or seeded-session endpoints. `AICL_PUBLIC_BASE_URL` must match the
browser origin because the application checks origin and CSRF. Nonlocal URLs must
use HTTPS. Keep all three mode settings (`AICL_PROVIDER_MODE`,
`AICL_EXECUTOR_MODE`, `AICL_CHAT_MODEL_MODE`) at `fake`; other values fail startup.
Changing the environment to `production` does not enable real providers, and the
fake OAuth authorization page is absent in that environment.

The [architecture configuration table](design/architecture.md) lists settings and
their owners. `AICL_IDENTITY_HMAC_KEY` determines stable owner identity, so changing
it can make existing records inaccessible. The encryption key protects connection
secrets; changing it without a migration makes stored credentials unreadable.
Keep keys private and stable for a persistent database. Use one application
process: reconciliation and cleanup run in-process, and multi-worker deployment
has not been implemented or accepted.

## Pages and first-party endpoints

All owner data is selected from authenticated session identity. Mutation requests
use the session cookie, a matching origin and CSRF token. Instance management
forms include the current `expected_version`; a stale form receives a conflict
and should be reloaded before retrying.

| Surface | Route | Purpose |
|---|---|---|
| Landing/sign-in | `/`, `/auth/sign-in` | Request and confirm an emailed link |
| Workspace | `/workspace` | Owner's instances and creation links |
| Wizard | `/agents/new` | Canonical Default instance creation |
| Chat | `/chat`, `POST /chat/messages` | Scripted creation with the same canonical service |
| Instance | `/instances/{instance_id}` | Lifecycle, capabilities, limits, domains, attachments, usage, gates and audit |
| Connections | `/connections` | Fake OAuth connection setup and revocation |
| Web-app tools | `POST /app-tools/{name}` | Only `list_templates`, `create_instance`, `read_instance` |
| Simulated work | `POST /instances/{instance_id}/work-requests` | Validate and dispatch a simulated capability request |
| Confirmation | `POST /pending-actions/{pending_action_id}/confirm` | Owner approval for a specific pending action |
| OAuth | `POST /connections/oauth/begin`, `GET /connections/oauth/callback` | Connection consent and callback handling |

The first-party JSON endpoints accept `X-CSRF-Token`; HTML forms carry
`csrf_token`. Creation tools do not accept tenant, owner, credential or confirmation
arguments. These routes are not a public MCP server. For exact request and result
contracts, use the [control-plane](design/aicl-control-plane/technical.md),
[connections/work](design/connection-network-policy/technical.md) and
[experience](design/aicl-experience/technical.md) specifications. FastAPI's `/docs`
and `/openapi.json` expose the registered routes, but hand-parsed JSON payloads
are not fully described by their generated OpenAPI schemas.

Sign-in confirmation (`POST /auth/verify`) also requires an `Origin` header matching
the configured public URL's scheme and authority, even before a session exists.
Browser forms send it automatically. Missing or foreign origins and explicitly
cross-site requests are denied without consuming the link; scripted clients must
send the expected origin as well.

## Checks and operating limits

From the repository root with the virtual environment active:

```sh
PYTHONPATH=backend:backend/tests:scripts python -m pytest backend/tests -p ctx_pytest_ac -q
npm ci
npx playwright install chromium
npx playwright test --config .gitlab/ctx/playwright.config.ts --reporter=list
```

The local browser command selects the console reporter; the default CI reporter
requires genuine GitLab source/job identity and a clean candidate to write
acceptance evidence. Do not manufacture CI variables to make a local run look like
a pipeline. The browser command starts its own local test server; stop a manual server on port
4173 first. Backend checks exercise real SQLite and fake provider boundaries.
Browser checks cover real application sign-in, wizard/chat creation and owner
management, while mail and external providers remain fake. Local passing checks
are useful development evidence, not GitLab pipeline or whole-epic acceptance.

Budget reservations, usage, audit records and the simulator's executor journal are
persisted in SQLite. The journal is keyed by globally unique hold ID, commits a
start before a simulated effect, and retains unknown outcomes across restart. An
absent-entry lookup records a terminal “not started” result before a hold can be
released, preventing a delayed dispatch from starting afterward. Migration from
the older process-memory executor keeps unresolved existing operations unknown;
missing historical evidence is not treated as proof of no work. Such holds remain
blocked until a definite outcome is available. Real providers still require their
own idempotency, authoritative outcome recovery and transport controls before
billable or external actions can be enabled.

Back up persistent SQLite consistently while the app is stopped, together with a
separately protected copy of its keys; do not copy only the main file from a live
WAL database. This prototype has no accepted deployment, restore drill, monitoring
service or production payment path. PayPal/funding, live model/tool integrations,
an autonomous runner and external MCP are follow-on work outside E11. Current
ticket and epic acceptance status is recorded [with the E11 evidence](plan/E11/completion.md).
