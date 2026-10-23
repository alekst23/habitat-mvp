# Private browser runtime

This service gives the AICL broker an ephemeral Chromium browser for an owner
sign-in handoff. It contains no model keys, PayPal credentials, owner database or
persistent browser profiles. Every session gets a fresh Chromium process and
context. Browser state is exported only to the trusted broker for encrypted
storage; the model must never receive the state or owner handoff input.

The HTTP API requires `Authorization: Bearer <BROWSER_SERVICE_TOKEN>` on every
route except `/health/ready`. The token must contain at least 32 characters. Bind
this service to private networking; the Habitat owner UI proxies its controls.
Do not expose the raw browser service, Playwright or CDP to users.

## Run in Docker

Build from the repository root:

```sh
docker build -f browser-service/Dockerfile -t habitat-browser .
```

Supply a token through your local environment or secret manager, then run:

```sh
docker run --rm --init \
  --security-opt seccomp=browser-service/seccomp_profile.json \
  -e BROWSER_SERVICE_TOKEN \
  -p 127.0.0.1:8090:8090 \
  habitat-browser
```

The pinned `seccomp_profile.json` is copied unchanged from
[Playwright v1.63.0](https://github.com/microsoft/playwright/blob/v1.63.0/utils/docker/seccomp_profile.json).
It is the upstream Docker profile recommended for sandboxed Chromium, including
the required user namespace system calls. Chromium runs as `pwuser` with
`chromium_sandbox=True`. There is no `--no-sandbox`, privileged-container or
`SYS_ADMIN` fallback. Startup probes Chromium and refuses readiness if its
sandbox cannot start. The standard Docker profile failed this check locally;
the supplied Playwright profile passed. Render must independently pass this
readiness check; its native service configuration does not offer this Docker
`--security-opt` setting. A compatible browser host is required if Render's
host policy does not permit Chromium's sandbox.

Production traffic passes through a local CONNECT proxy. The proxy allows only
HTTPS port 443, resolves every destination, rejects mixed/public-private DNS
results, and connects directly to the validated public IP. Chromium's implicit
loopback proxy bypass, QUIC and non-proxied WebRTC UDP are disabled. Downloads,
service workers, and remote WebSockets are unavailable in this MVP. Sites whose
login requires WebSockets, native dialogs, or hardware-backed authenticators may
need another browser implementation.

## Service contract

| Endpoint | Purpose |
| --- | --- |
| `POST /sessions` | Create/idempotently retrieve a session from `{idempotency_key,url,storage_state?,mode,ttl_seconds?}` |
| `GET /sessions/{id}/frame` | Owner-only JPEG base64 frame and current URL/title; 1280×720 |
| `POST /sessions/{id}/input` | Owner-only click, text, key or scroll input |
| `POST /sessions/{id}/navigate` | Worker-only navigation to a public HTTPS URL |
| `GET /sessions/{id}/page` | Worker-only bounded visible text, current URL and title |
| `POST /sessions/{id}/snapshot` | Trusted-broker-only browser state and current URL; does not close |
| `DELETE /sessions/{id}` | Idempotently close; acknowledges only after browser shutdown |
| `DELETE /session-keys/{key}` | Cancel an unknown or in-flight creation and fence retries for 30 minutes |

Default session TTL is 600 seconds; maximum is 900. `BROWSER_MAX_SESSIONS`
defaults to one, with a supported range of 1–8. Expired sessions are terminated.
Failed termination retains capacity and prevents claiming that handoff ended.
Cancellation by idempotency key waits for an in-flight creation to finish and
close, so the broker must allow at least 60 seconds or retry an uncertain cancel.
The cancel fence lasts 30 minutes in this ephemeral runtime; broker retries must
stop at their own lease expiry (at most 15 minutes).
Restarted services lose live sessions; the broker can restore encrypted saved
state into a new session. Browser snapshot completion is **not proof that a
provider authenticated the owner**. The resumed job must verify that the intended
operation is accessible.

After each successful worker page operation, AICL exports a fresh snapshot and
atomically replaces its encrypted saved state before closing the browser. Later
jobs restore the latest cookies, local storage and IndexedDB. The runtime itself
does not retain a profile between sessions; refresh does not extend the owner's
24-hour access grant. See [the broker flow](../docs/cloud-browser.md) for failure,
revocation and persistence behavior.

## Isolated local acceptance test

The opt-in test creates a temporary test login website, enters only a fixture
password through the real browser API, saves its session cookie, closes the
owner browser, and proves a new worker browser can read the protected page:

```sh
BROWSER_REAL_TEST=1 PYTHONPATH=backend python -m pytest \
  backend/tests/unit/test_browser_runtime.py \
  backend/tests/unit/test_browser_runtime_network.py \
  backend/tests/unit/test_browser_runtime_real.py \
  backend/tests/integration/test_browser_writeback_real.py -q
```

The test requires the pinned Playwright Python package and matching Chromium.
Its direct fixture transport requires **all three** of `BROWSER_ENVIRONMENT=test`,
`BROWSER_TEST_MODE=1`, and an exact `BROWSER_TEST_FIXTURE_ORIGIN`; it cannot be
enabled in production and permits only that origin. It still uses Chromium's
sandbox. No production service should use these test settings.
