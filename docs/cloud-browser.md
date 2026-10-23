# Cloud sign-in through Requests

An agent can ask for access to a service it encounters during a job. The request
names the service domain, explains the intended access and links to the job that
needs it. Habitat does not need a separate "Connect Snapchat" button or a catalog
entry for every website.

The owner responds in **Requests**, alongside questions, scoped permission
requests and purchase approvals. Sign-in provides a browser session for the saved
job and that agent's later scheduled jobs for up to 24 hours. It does not approve
a purchase, authorize payment or expand the agent's configured capabilities.

## Owner and worker flow

1. The owner configures a website, purchase objective, proposed spending cap,
   deliverable criteria and schedule. When scheduled work has no reusable access,
   the trusted worker submits an authentication request for its current job. AICL
   saves the request, pauses that job and lets the existing worker finish. The
   worker is not kept running while the owner is away.
2. The owner opens the request and starts its cloud sign-in session. Habitat
   displays the actual remote browser page inside the authenticated owner flow.
   The owner enters credentials and MFA directly into that browser, not into
   agent chat or a clarification response.
3. The owner finishes the handoff and chooses immediate continuation or the next
   scheduled run. AICL saves encrypted browser state, closes the interactive
   browser and retains the session's owner, agent, request, domain and expiry.
4. A later authorized worker can restore that state into a new isolated browser
   and recheck the requested service. Current lifecycle controls, schedule, job
   ownership, budget reservation and session validity still apply.
5. After each successful browser page operation, AICL snapshots the updated
   cookies, local storage and IndexedDB and replaces the encrypted saved state.
   The next operation or scheduled job restores this latest snapshot, including
   any rotated session cookies or removed storage entries.
6. If authentication has expired or the service still requires a challenge, the
   job needs another owner sign-in request. A completed handoff is evidence that
   the owner supplied a session, not universal proof that a website accepted it.
7. The reviewed worker uses the observed account page as bounded source material
   for its purchase recommendation. The model must cite exact observed excerpts
   for account access and the recommendation, keep the amount within the owner's
   configured cap, and satisfy the saved deliverable criteria. If access is
   uncertain it asks a clarification question; if login is still needed it creates
   another sign-in request. These checks do not independently verify model claims.
8. A submitted deliverable and its immutable purchase proposal appear for owner
   review, linked to the source job and that exact deliverable version. The owner
   can approve or decline in **Requests**. This records a decision only: no
   checkout, PayPal order, payment, external campaign draft or ad publication is
   created by this workflow.

Browser state can include credentials such as session cookies and local storage.
It is encrypted in AICL storage and decrypted only by the browser broker for the
private runtime. It is never included in model inputs, owner-answer snapshots,
worker API responses, activity details or source control. The browser process
necessarily holds this state in memory while using the site.

Write-back uses the same persistent AICL database and encryption key as the owner
handoff. The new encrypted blob, parent session reference and destruction of the
old blob commit together. The broker rechecks the request, session, exclusive
lease and worker authority before saving; revocation, expiry or a new sign-in
request during the operation prevents an old worker from replacing saved access.
Snapshot or storage failure returns an error and retains the prior snapshot.
If browser shutdown fails after saving, the exclusive closing lease still blocks
reuse until shutdown is confirmed.

Refreshing state does not extend the original 24-hour access grant. Website
sessions may expire sooner, and an accepted snapshot does not establish that the
website still considers it authenticated. State survives application restarts
when the database and encryption key are retained; the browser process itself
does not persist. Open tabs, partially completed forms, JavaScript memory and
sessionStorage are not captured by this storage-state mechanism. A job that fails
before a successful browser operation does not write back; a later job failure
does not undo snapshots already saved by its completed browser operations.

## Implemented worker boundary

The restricted machine API exposes:

```text
POST /internal/render/jobs/{dispatch_id}/browser/page
{
  "task_run_id": "the claimed Render task",
  "workflow_run_id": "the saved job",
  "request_id": "the completed sign-in request",
  "url": "https://the-requested-domain.example/protected-page"
}
```

`render_worker.client.AICLClient.browser_page` calls this endpoint. The scheduler
token and owner cookies do not authorize it. Tenant and owner identity come from
the saved dispatch, never from the request payload. A worker cannot use a request
belonging to another agent or owner. The target job must belong to its claimed
dispatch; the sign-in request can originate from an earlier job of the same agent.

A claimed attempt includes safe `snapshot.browser_requests` metadata for completed
sign-in handoffs with unexpired saved state: request ID, requested domain, access
description, expiry and `access_verified: false`. A newly created continuation or
scheduled worker can discover these saved requests without retaining the earlier
process. Their presence does not guarantee that the website will accept the
session; the broker checks expiry and revocation again when the worker calls the
page tool, and the worker must check the website's response.

The endpoint requires a running, claimed dispatch, a resolved authentication
request, no outstanding owner response, active agent controls, an enabled schedule
and an unexpired held compute reservation. It rechecks these controls inside the
write-back transaction and again before returning the browser result. The broker
also rejects expired or revoked browser state and
concurrent owner control. The broker closes the browser and releases its worker
lease when the read ends. If creation or closure has an unknown outcome, the
exclusive lease remains held until the runtime confirms shutdown.

Only the requested HTTPS domain can be used as the worker's navigation target.
The runtime applies its network policy to navigation and subresources. Responses
contain bounded page title, text and location, with `access_verified: false`. The
caller must interpret a service-appropriate access check. URL query strings and
fragments are removed at the machine boundary; no cookie jar, storage state, screenshot,
raw browser endpoint or debugging connection is returned.

This tool reads a page. It has no click, form submission, checkout, ad publication
or purchase-approval capability. Website navigation itself can have server-side
effects, so it should only target an appropriate viewing page and must not be
treated as a general guarantee that every HTTP GET is harmless. Page text is
untrusted source material, not new authority for an agent.

## Configuring the scheduled browser workflow

On a new agent's **Workflow** page, choose **Use browser purchase workflow**.
The editable starting brief is a mobile-game advertising proposal; Snapchat is
only its default website, not a special account connector. Under **Website &
purchase scope**, set the public HTTPS account page to review, the exact purchase
objective, and the maximum proposed amount in USD. Supply the game, audience and
campaign constraints in the goal and context, then review the deliverable's
completion criteria. Save the configuration, enable the schedule, and set the
agent's inference, budget, funding and purchase-allowance controls.

The saved configuration uses `scenario: "browser_purchase"` and a `browser_task`
object with `service_url`, `objective`, `max_amount_minor` (integer USD cents) and
`currency: "USD"`. The sole reviewed deliverable key is `purchase_proposal`.
The website must be an appropriate viewing page, not a checkout or action URL;
never put passwords, login codes or tokens into the URL or configuration.

The scheduled implementation requires `AICL_WORKFLOW_EXECUTION_MODE=render`,
`AICL_INFERENCE_MODE=openai`, the configured model adapter, and the private browser
service settings below. Scheduler and worker authentication, compute reservations
and spend ceilings remain as described in [Render deployment](render-deployment.md).
A fixture-only local writing mode cannot run this browser workflow and fails
closed instead of fabricating a browser result. The local acceptance harness uses
the same dispatch and continuation code with controlled browser/model fixtures.

The worker calls its authenticated browser-preparation endpoint before model
generation. Preparation either saves a sign-in request and releases the worker,
or reads the configured website through the broker and persists bounded observed
page evidence for that specific inference attempt. The model cannot supply its
own browser evidence or call the proposal service directly. Replays reuse saved
provider results, while source checks, session validity and current controls are
checked again before a proposal is saved. Changed authorization does not erase
an inference charge that already occurred.

Requests display the proposed amount as a **proposed budget**, not a verified
merchant quote, alongside the observed excerpts and source deliverable. Requesting
changes to the work supersedes its pending proposal, so the old version cannot
be approved while a revision is prepared. A revised submitted deliverable gets a
new proposal; earlier evidence and decisions remain available in history.
An approved proposal and its source work cannot be silently revised. Approval
never resumes a checkout or grants payment authority.

## Current scope and remaining integration

The reviewed worker now completes the bounded scheduled path: request sign-in,
resume with saved access, read a configured account page, prepare a supported
recommendation, and stop at owner proposal review. Account access is a model
assessment backed by exact page excerpts, not a provider-specific verification.
Login-required and uncertain results are routed back to Requests. Runtime outages
leave the attempt retryable on a later schedule rather than claiming login failed.

This remains a read-only page tool. It does not autonomously discover arbitrary
websites, click controls, fill campaign forms, submit an external advertising
draft, or discover and execute a payment. Those capabilities need a separately
reviewed action boundary and provider-compatible checks. The local fixture tests
demonstrate pause, handoff, continuation and proposal creation; they do **not**
demonstrate a live Snapchat login, campaign creation, purchase or ad delivery.

The separate browser service has fixed hosting costs and bounded session lifetimes
and concurrency. The current Render job hold accounts for the reviewed worker's
compute, not an independently metered browser-provider charge. Adding a metered
browser provider requires a separate price bound and reservation before dispatch.

The application, browser broker and private runtime must be deployed together
before cloud sign-in is available on Render. An absent or unreachable runtime
keeps the request pending and displays a useful failure; it does not report a
successful login. Local fixture validation is not evidence of a deployed Render
service or compatibility with a particular third-party site's MFA and bot checks.

## Operational references

- [Playwright authentication state](https://playwright.dev/python/docs/auth):
  persisted state is sensitive; session storage and device-bound login behavior
  require additional consideration.
- [Playwright Docker guidance](https://playwright.dev/python/docs/docker):
  browser and client versions must match, and untrusted browsing needs a dedicated
  non-root user and appropriate sandbox configuration.
- [Render private services](https://render.com/docs/private-services): the browser
  runtime should be reachable from AICL over the private network, without a public
  debugging or browser-control endpoint.

Keep browser control behind Habitat authentication and CSRF checks. Do not enable
access logging of input payloads, session snapshots or remote browser responses.
The runtime should receive only its own service token and ephemeral session
material, not AICL's database, PayPal credentials or model API key.

## Running the browser service

The browser is a separate process and Docker image, not a dependency of the AICL
Alpine image. `requirements-browser.txt` pins the Python package to the version
of Chromium in `browser-service/Dockerfile`. Start one Uvicorn worker and one
service instance: live session routing is process-local. The default capacity is
one browser, with a ten-minute handoff lease. Saved access expires after 24 hours.

A compatible Docker host can run the image as follows (the private env file
contains `BROWSER_SERVICE_TOKEN`, a distinct random secret of at least 32 ASCII
characters):

```sh
docker build -f browser-service/Dockerfile -t habitat-browser:local .
docker run --rm --init --name habitat-browser --shm-size=1g \
  --security-opt seccomp=browser-service/seccomp_profile.json \
  --env-file /absolute/path/to/private-browser.env \
  -p 127.0.0.1:8090:8090 habitat-browser:local
```

The version-pinned seccomp profile comes from Playwright's official repository.
It permits the user-namespace operations needed by Chromium's sandbox. The image
runs as `pwuser`; startup launches a sandboxed browser as a readiness probe.
Do not use `--privileged`, `SYS_ADMIN`, root, or `--no-sandbox` to bypass a failed
probe. Browser subprocesses receive a minimal environment without the runtime's
service token, AICL secrets or provider keys.

For local AICL development, set both of these in its private configuration:

```dotenv
AICL_BROWSER_SERVICE_URL=http://127.0.0.1:8090
AICL_BROWSER_SERVICE_TOKEN=<same private runtime token>
```

Both settings are empty by default. Requests still work when the browser feature
is disabled; sign-in requests remain pending. The URL must be a clean private
Render HTTP origin, or loopback in development/test. Do not expose this service's
API, browser debugging ports, state snapshots or input endpoints publicly.

## Render rollout

`render.browser.yaml` is a separate, optional Blueprint for a private Docker
service in Oregon with one 1-CPU/2-GB instance. It does not alter or deploy the
existing AICL application. Fixed browser hosting charges are additional to the
existing application and workflow costs.

1. Confirm that the selected Render host supports Chromium's sandbox. The
   application refuses to start if it does not. The local Docker test required
   the supplied seccomp profile; Render's documented Blueprint fields do not
   expose a custom Docker seccomp flag. A successful local Docker check therefore
   does **not** certify Render compatibility. Use a compatible isolated host if
   that sandbox requirement cannot be satisfied.
2. Deploy the private service from the reviewed revision only after that host
   prerequisite is resolved. Keep `BROWSER_ENVIRONMENT=production`,
   `BROWSER_TEST_MODE=0`, `BROWSER_MAX_SESSIONS=1`, one Uvicorn worker and one
   service instance. It needs no persistent disk or payment/model credentials.
3. Set `AICL_BROWSER_SERVICE_URL=http://<private-service-host>:8090` and
   `AICL_BROWSER_SERVICE_TOKEN` to its generated `BROWSER_SERVICE_TOKEN` on the
   AICL service. Keep the token out of client-side code and agent configuration.
4. Deploy AICL and the workflow worker from the same reviewed revision. AICL
   applies migrations `0024_browser_sessions`, `0025_browser_close_leases`,
   `0026_browser_attempt_evidence` and `0027_browser_purchase_proposals` to its
   existing encrypted store.
5. Exercise a tenant-isolated test sign-in, session handoff, subsequent scheduled
   read, revocation and restart recovery. A third-party provider's CAPTCHA,
   passkey, device-binding or bot checks may still prevent its login.

For an end-to-end local Chromium test after installing the browser requirements:

```sh
python -m playwright install chromium
BROWSER_REAL_TEST=1 PYTHONPATH=backend python -m pytest \
  backend/tests/unit/test_browser_runtime_real.py \
  backend/tests/integration/test_browser_writeback_real.py -q
```

This fixture uses fictional credentials and a loopback server. Its exact-origin
transport exception requires `BROWSER_ENVIRONMENT=test` and cannot be enabled in
production. The normal browser transport pins public DNS results through an HTTPS
CONNECT proxy, rejects private/mixed addresses, blocks WebSockets and service
workers, and disables direct QUIC and non-proxied WebRTC. Its scope is the browser
network boundary, not a claim that arbitrary website content is trustworthy.
