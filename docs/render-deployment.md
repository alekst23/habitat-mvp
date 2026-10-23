# Habitat on Render

This deployment makes Render responsible for scheduled agent execution. AICL
remains the authority for owner identity, configuration, budgets, inference,
PayPal approval and durable results. It uses one reviewed PocketPlan marketing
agent, not arbitrary uploaded programs.

The repository includes the deployment configuration and worker. A passing local
test or Blueprint schema check is not evidence of a running Render deployment.
Capture the hosted proof below after deploying a complete reviewed revision.

## Services and boundaries

| Service | Responsibility | Credentials and storage |
| --- | --- | --- |
| `habitat-aicl` | HTTPS owner app, machine API, durable schedule/outbox, budget reservations, inference proxy, PayPal verification, Audit and deliverables | Sole SQLite writer at `/data/habitat.sqlite`; persistent disk; owner, model, PayPal and SMTP secrets |
| `habitat-agent-workflow` | Registered `habitat_agent` task: claim saved work, prepare its criteria, request bounded inference, validate the response, submit and finish | Worker token only; no database, owner session, model key or PayPal key |
| `habitat-schedule-dispatch` | Once per minute, ask AICL for due work, start Render tasks and acknowledge their IDs | Scheduler token and Render API key; no model/payment authority |

All three services use the same Render region. The worker and cron connect to
the web service's private `hostport`; public owner navigation uses HTTPS. Machine
requests require distinct bearer credentials and do not use owner-session
cookies. The HTTP client rejects redirects and keeps response bodies and tokens
out of its errors. Only opaque dispatch/run/output identifiers appear in task
arguments, task results and normal worker logs.

A task is intentionally small: it runs the reviewed program and sends model
requests through AICL. The model credential never reaches the worker. Saved
goals, criteria and feedback remain in the AICL snapshot. The worker checks
response structure and exact saved criteria, and AICL independently verifies the
cached response before persistence. Model completion assessments are not
independent semantic verification; the owner still reviews quality.

## Reliable execution and bounded cost

AICL records each scheduled occurrence and its dispatch before sending anything
to Render. The SDK receives a stable `habitat:<dispatch-id>` idempotency key.
Render SDK 1.4 deduplicates matching starts for 24 hours; AICL stops automatic
reoffers before that window expires. A lost acknowledgment never creates a new
dispatch key. Worker requests are bound to the claimed Render task-run ID.

The `habitat_agent` task uses Flex, a 180-second timeout and at most one retry.
Generation results are persisted in AICL before worker validation. A restarted
task reuses known results; an uncertain provider response retains its budget
reservation and is not automatically sent again. A blocked or unresolved AICL
job can finish the Render task in an attention state: infrastructure completion
is not proof of a completed deliverable.

AICL reserves up to six compute minutes before dispatch, covering the configured
task attempt and retry. The internal compute rate is a conservative Flex upper
bound of 6,667 micro-USD per minute. Settlement uses claimed execution elapsed
time within the reservation. This is an **internal wall-time estimate, not a
Render invoice**. It does not include web hosting, cron, storage or all startup
overhead. The inference ceiling defaults to $1 of real model usage for the
server; test PayPal credit cannot raise this ceiling. Do not advertise an exact
match between the Habitat compute ledger and Render's bill.

Pending purchases end the active task. Approval and buyer payment occur in the
owner's independent Audit flow. Eligible continuation becomes a new durable
dispatch, either promptly or at the saved schedule, with current controls
checked again. A worker cannot approve or capture a purchase.

The [Render task documentation](https://render.com/docs/workflows-defining)
describes task limits and retries. [Task triggering](https://render.com/docs/workflows-running)
and the [official SDK releases](https://github.com/render-oss/sdk/releases/tag/python%2Fv1.4.0)
document launch and metadata behavior. Review current
[Workflow pricing](https://render.com/docs/workflows-limits) before enabling a
hosted schedule.

## Deploy the reviewed revision

1. Include the complete app in the deployment revision: the commerce and
   workflow packages, migrations, static assets, machine API, worker,
   `requirements-render.txt`, Dockerfile and `render.yaml`. Local untracked
   files are not available to a Git-based deployment. Run the application and
   Render tests before committing this snapshot; do not deploy the local
   `demo_server`, `sandbox_server`, capture helpers or seeded test routes.
2. Create a Render Blueprint from that repository and choose `render.yaml`.
   It declares a paid web instance with a 1 GB disk, a native Python Workflow,
   and a cron dispatcher. Review resource cost before applying it. Automatic
   deploys are off so an unreviewed commit does not replace the running demo.
3. Enter the requested values privately in Render. All secret values below
   belong on the indicated service, never in source or a recording:

   | Service | Values supplied during creation |
   | --- | --- |
   | Web | `OPENAI_API_KEY`; service PayPal Sandbox `CLIENT_ID`, `CLIENT_SECRET`, `MERCHANT_ID`; the corresponding three `AICL_PAYPAL_PURCHASE_*` values for a separate Sandbox seller; `AICL_SMTP_HOST`, `AICL_SMTP_USERNAME`, `AICL_SMTP_PASSWORD`, `AICL_SMTP_FROM` |
   | Cron | `RENDER_API_KEY` for starting this workspace's tasks |

   The Blueprint generates separate session, identity, encryption, scheduler
   and worker secrets. Its `fromService` references provide only the matching
   machine token to each process. Never rotate identity/encryption keys casually:
   keep protected recovery copies with database backups. The public URL and
   private hostport are derived from Render, and the cron task slug is derived
   from the Workflow service. SMTP uses port 587 by default.
4. Wait for the web health check `/health/ready` and the registered
   `habitat_agent` task. Inspect the Workflow task page; no worker port is
   expected. Ensure the disk is writable by the image's UID 10001 and survives
   redeploy. Migrations run at application startup with the disk mounted.
5. Open the HTTPS app and sign in through a real emailed magic link. Check that
   `/__test__/last-magic-link` is unavailable. Do not expose captured sign-in
   links or a shared demo account to the internet. Configure only the intended
   demo agent before enabling its schedule.

The Blueprint was checked against Render's published JSON schema on 2026-10-22.
Render's own Blueprint validation remains the authority for account-specific
availability. See the [Blueprint reference](https://render.com/docs/blueprint-spec).
A single disk is intentionally attached only to AICL: it cannot be shared with
Workflow instances or Cron, and this SQLite deployment must stay at one web
instance. Disk deployments can briefly interrupt the web app. See
[persistent disks](https://render.com/docs/disks).

Render does not allow a custom shutdown delay on a service with a disk. Before
redeploying AICL, pause agent schedules and suspend the cron dispatcher, then let
in-flight tasks and payment requests finish. If shutdown interrupts a provider
request, retain its unresolved reservation and reconcile against provider evidence;
do not release the hold or resend the operation just because the app restarted.
Resume scheduling after the health check and saved state have been verified.

## First hosted proof

1. Create the PocketPlan agent with inference enabled and use the app marketing
   example. Save the goals, deliverable criteria and schedule. Set positive
   daily and monthly inference **and compute** limits; the compute daily limit
   must cover the six-minute reservation. Add service credit through verified
   PayPal Sandbox checkout. See [PayPal setup](paypal-sandbox.md) for the two
   test sellers and buyer.
2. Enable the schedule and leave the browser idle. The cron dispatcher checks
   for work every minute; the agent's configured cadence controls when work is
   actually due. Observe a real Render task without using the local demo clock.
3. Follow the same dispatch/run identity in Render and Habitat. Show the
   generated campaign plan, configured criteria and inference usage, plus the
   separately labeled compute estimate. Verify the model request used the
   reviewed adapter and that no model key or owner text appears in Render logs.
4. Open Audit independently and review the purchase alongside its source work.
   The worker must already have exited while awaiting the owner's decision.
   Approve the exact quote, complete PayPal Sandbox buyer consent, and observe
   the selected continuation behavior without another automatic payment.
5. Pause the schedule or exhaust its configured budget and confirm no new
   billable generation starts. Retry a completed task with the same dispatch
   and verify no duplicate deliverable/payment/charge. Simulate uncertain
   provider outcomes with isolated tests, not intentional billable failures in
   the hosted demo.
6. Redeploy the web service and verify saved approvals, pending purchases and
   deliverables survive. Keep a database-aware SQLite backup plus protected
   keys; do not copy only a live WAL database's main file. Do not restore over
   existing financial/audit history without a reviewed recovery procedure.

The reviewed model currently generates the campaign plan and performance report.
Ad creative, merchant fulfillment and campaign metrics remain fixtures. PayPal
uses its real **Sandbox** API and test money, not live payments. A delivered
report therefore demonstrates execution and controlled payment; it does not
prove real ad placement or real advertising results.

## Local verification and operator controls

Install the backend requirements in a local virtual environment and install
`requirements-render.txt` to include the actual SDK registration test:

```sh
python -m pip install -r backend/requirements.txt -r requirements-render.txt
PYTHONPATH=backend python -m pytest backend/tests/unit/test_render_worker.py backend/tests/integration/test_render_execution.py -q
```

`python -m render_worker.main` is the Render runtime entry point, not a standalone
local HTTP server. Render provides the SDK's runtime socket and execution mode.
The unit tests exercise the registered task definition without contacting Render.
The dispatcher can target a separately configured local app with `AICL_API_URL`
and a scheduler token, but it **will start real Render tasks** when supplied a
real Render API key. Use the tests for an offline check.

Pause an agent's schedule to stop its new work; suspend the cron service in
Render to stop all automatic dispatch. Existing task runs may still finish, and
already accepted model requests or captured payments cannot be undone by a
pause. Investigate an unresolved dispatch/model outcome from its durable record
and provider evidence; do not delete its hold or mint a replacement dispatch.

For sponsor evidence, keep a concise screen capture of the real scheduled task
and its linked Habitat deliverable, one denied budget attempt, durable recovery
without duplicate effects, and the hosted URL. Revise the video's existing
simulation caption only after this hosted proof is captured. The
[Render sponsor brief](https://paypalaihackathon.devpost.com/details/render)
specifically asks entrants to deploy on Render and use Render Workflows.

## Implementation verification — 2026-10-22

The complete backend suite passed **386 tests**, including the actual Render
SDK 1.4 task registration. Tests exercise the real worker HTTP client against
the authenticated AICL machine routes, with a deterministic model adapter. They
cover immutable configuration, known-response recovery, unresolved charges,
pause and budget gates, credential separation, independent purchase decisions,
and serialized continuations. The existing migration preservation checks also
verify the new append-only compute records.

The `linux/amd64` deployment image built successfully. An isolated container ran
as UID 10001, completed all 18 migrations, served both health checks and hosted
static assets, and returned 404 for test/demo helpers. The database retained its
original import record after a restart. This check used disposable credentials
and did not contact OpenAI, PayPal or Render. The local review summary is saved
in `.ctx/render-verification/verification.json` (ignored operational evidence).

The Render dashboard currently requires sign-in. No cloud resources, hosted
provider transaction, repository push or production deployment was performed
by this verification. The complete source revision and private hosted settings
must be supplied before the first hosted proof above.
