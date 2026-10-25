# Private Google Sheets waitlist

The secured landing page shows **Join the waitlist** directly beneath **For
hackathon judges** when configured. The form sends an email to Habitat's backend. The backend sends a
JSON request to a Google Apps Script web app, which appends the normalized email
and a UTC signup timestamp to a private spreadsheet. The browser never receives
the webhook secret or spreadsheet ID. Signing up does not create an account,
grant private demo access, verify email ownership, or send email.

Activation requires a Google account owner to authorize the script and publish
its web app, followed by the application's normal approved configuration and
deployment process. The repository's deployment rules still apply. The source
files and local tests do not create a spreadsheet or prove live Google delivery.

## Set up the private destination

1. Create a Google Sheet named **Habitat waitlist**. Keep **Share → General
   access → Restricted**. Only add trusted people who need to manage signups.
2. Open **Extensions → Apps Script** from that spreadsheet. Replace the starter
   code with [waitlist-google-apps-script.gs](../scripts/waitlist-google-apps-script.gs)
   and save it.
3. In the Apps Script editor, select and run `setupBoundWaitlist`. Authorize the
   requested spreadsheet access using the account that owns this waitlist. This
   records the spreadsheet ID in the script's `WAITLIST_SPREADSHEET_ID` property.
   Web requests always use this saved ID: Google documents that active-container
   methods are unavailable when a bound script executes as a web app.
   [Google bound-script documentation](https://developers.google.com/apps-script/guides/bound)
4. In **Project Settings → Script Properties**, add `WAITLIST_TOKEN` with a newly
   generated random secret of 32–128 characters using only letters, digits,
   underscores and hyphens. Store the same secret in your password manager for
   the application configuration. Do not put it in source code, URLs, browser
   JavaScript, screenshots or logs. Script properties are shared application
   configuration, so keep script-editor access limited to trusted operators.
   [Google Properties Service documentation](https://developers.google.com/apps-script/guides/properties)

A standalone Apps Script project also works: set `WAITLIST_SPREADSHEET_ID`
manually to the ID between `/d/` and `/edit` in the Sheet URL, and skip
`setupBoundWaitlist`. The deployment owner must have edit access to that Sheet.

The first accepted submission creates a tab named **Waitlist** with the columns
**Email** and **Signed up at (UTC)**. An existing tab must use those exact first
two headers; unexpected layouts are rejected. Keep this tab dedicated to signups.

## Publish the webhook and activate Habitat

1. After reviewing the script and permissions, the Google owner chooses
   **Deploy → New deployment → Web app**, selects **Execute as: Me** and
   **Who has access: Anyone**, then authorizes and publishes it. If a Workspace
   policy does not allow anonymous web apps, this setup cannot be activated
   until the organization's policy permits it. Owner execution lets the script
   write the private Sheet without requiring visitors to sign into Google.
   [Google web-app deployment documentation](https://developers.google.com/apps-script/guides/web)
2. Copy the deployed URL ending in `/exec`, in this form:
   `https://script.google.com/macros/s/DEPLOYMENT_ID/exec`.
   Use the deployed version rather than the editor-only `/dev` URL.
3. Configure the Habitat web service with these two environment variables:

   | Variable | Value |
   | --- | --- |
   | `AICL_WAITLIST_WEBHOOK_URL` | The deployed Apps Script `/exec` URL |
   | `AICL_WAITLIST_WEBHOOK_TOKEN` | The exact same value as the script property `WAITLIST_TOKEN` |

   Treat both as private server configuration. Keep the token in the hosting
   provider's secret environment settings or an ignored local environment file.
   Configure both together; leaving both empty disables collection. Restart or
   deploy the application through the approved release process to load them.
4. Using an email address you control, submit the public waitlist form. Confirm
   the application shows success and the private **Waitlist** tab contains the
   address and an ISO 8601 UTC timestamp ending in `Z`. Submit the same address
   again, including a case variation, and confirm there is still one data row.
   Remove the test row when finished if it should not remain on the waitlist.

**Anyone** applies to the webhook's ability to receive requests. Keep the Sheet
itself **Restricted**. The script authenticates its shared token before opening
the Sheet, rejects invalid input, and exposes no `doGet` handler or signup-list
response. The backend's secret must stay on the server.

## Storage and operational behavior

The public POST requires a same-origin form submission, limits the request body
to 2 KiB, and discards a filled honeypot. SQLite stores only HMAC-based email/IP
rate counters: 5 submissions per email, 20 per client IP and 100 total per hour.
Counters older than the previous hourly window are removed on subsequent
submissions. The application does not retain cleartext waitlist emails or IPs.
When behind a reverse proxy, configure the server's trusted proxy settings so
its client address is correct; never trust arbitrary visitor-supplied forwarding
headers. Otherwise multiple visitors can share a proxy's per-IP allowance.

Email addresses are trimmed and lowercased. The accepted format is a conventional
ASCII mailbox and dotted domain; international or quoted mailbox forms are not
supported by this small signup form. Leading `=`, `+` and other permitted local
part characters are stored as explicit rich text, so addresses are not evaluated
as spreadsheet formulas. Signup times are UTC strings independent of the Sheet's
display timezone. [Google rich-text builder documentation](https://developers.google.com/apps-script/reference/spreadsheet/rich-text-value-builder)

A script-wide lock serializes duplicate checking and row insertion. The script
flushes writes and checks the saved row before returning `{"ok":true}`; failures
return only `{"ok":false}`. A repeated email gets the same success response
without adding another row. A transport failure after a write can be retried
safely. Google recommends flushing pending spreadsheet changes before releasing
the lock. [Google Lock documentation](https://developers.google.com/apps-script/reference/lock/lock)

Google's ContentService redirects its JSON response to a one-time HTTPS URL on
`script.googleusercontent.com`. The backend follows only the expected Google
content redirect with a GET request and requires a positive JSON receipt. HTTP
200 alone does not prove that a signup was saved.
[Google ContentService documentation](https://developers.google.com/apps-script/guides/content)

After changing the script, update its deployment to a new version. If rotating
the shared secret, update `WAITLIST_TOKEN` and `AICL_WAITLIST_WEBHOOK_TOKEN`
together; submissions fail while they differ. Google service quotas or outages
can prevent collection, so the form should report a retryable error rather than
claim a signup was saved. Review Google execution status without logging request
bodies, secrets, or submitted emails.

## Local verification

From the `habitat-mvp` checkout:

```sh
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/integration/test_waitlist.py -q
node --test tests/waitlist-google-apps-script.test.cjs
```

The backend tests cover the form placement, disabled configuration, origin/input
checks, rate limits, Google receipts, constrained redirects and error states.
The script tests execute the source in a Node VM with a small Spreadsheet/Lock mock.
They verify rejection before Sheet access, normalized duplicate handling,
failure responses and lock release, and literal storage of formula-like emails.
The owner-authorized live submission check above verifies the actual Google
permissions, deployment version and storage behavior.
