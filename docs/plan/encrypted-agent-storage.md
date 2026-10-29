# Encrypted agent storage implementation plan

Status: deferred to the production release, October 26, 2026. This proposed plan
is retained while [durable agent sessions](../design/durable-agent-execution.md)
take priority. Current application data is disposable and can be deleted/recreated.
No implementation, data deletion, reset, key provisioning or deployment has occurred.

The runtime can proceed with a scoped content repository and a nonproduction
SQLite adapter using disposable public or synthetic data. It does not depend on
ESC-1/2 being implemented. Preserve opaque `ContentRef` identities and transactional
publication so the encrypted implementation can replace the adapter later.
Complete and verify this storage plan before the production release, including a
production configuration guard that rejects the unencrypted runtime adapter.

Implements [Agent data and trust](../design/agent-data-trust.md#storage-operational-access-and-deletion).
See the [architecture diagram](../design/diagrams/agent-secure-storage-architecture.png)
and the [fresh-start procedure](../development/encrypted-content-reset.md).

## Production storage rollout: start with an empty protected database

Build the new storage format, change every active content path to use it, then
initialize a fresh database and recreate the required agents/test data. We do not
need to preserve existing IDs, conversations, outputs, approvals or demo balances.
The new format does not need to read old plaintext rows.

This removes the legacy transformer, resumable backfill, schema/row mapping,
content/accounting parity comparisons, source/target generation switching,
migration rollback, old-format compatibility readers and migration receipt inbox.
Inactive historical content, including old Studio AI rows, can be discarded.
Do not build those mechanisms speculatively.

Retain the active read/write inventory: deleting old data does not stop the app
from creating new plaintext copies. Definitions, conversation history, plans,
owner requests, tool evidence, cached results and outputs must all use the same
content store. Existing transactional, authorization and cost invariants apply to
newly created work. Resetting application data does not cancel external operations;
stop/drain actual workers and paid requests before resetting their records.

Keep SQLite and the current single control-plane writer. Processor policy and
blind inference remain separate. Real KMS and deployment/recovery evidence are
required before claiming confidential hosted storage; fake keys prove contracts
only. The control-plane process is trusted: a Python module does not isolate its
KMS privileges. External workers, cron and backup identities get no unwrap access.

## Starting points

- [Database](../../backend/aicl/db.py) provides WAL and nested write transactions.
  Keep its unit-of-work convention and prepare encryption outside its write lock.
- [Application startup](../../backend/aicl/app.py) performs migrations, price
  imports and startup hooks. Add a format/key readiness guard; startup must never
  silently reset an incompatible, missing or undecryptable persistent database.
- [Secret storage](../../backend/aicl/connections/ports.py) encrypts credentials
  already. Keep that lifecycle and key material separate from the content store.
- Existing SQL JSON expressions, direct row reads and sorting need adjustment;
  encryption cannot be implemented only at the HTTP boundary.

## Minimum content-store contract


Implement `backend/aicl/content/` with small typed contracts, a service, an AES-GCM
codec, a SQLite repository and a key-service adapter. These are proposed modules.
Wire them through the existing `Ports`, `build_ports`, `wiring` and `AppContext`
composition; do not create a second global database or silently choose test keys.

```text
ContentScope(tenant, owner, scope_kind, scope_id)  # derived and checked by server
ContentRef(object_id, version)                  # reference, not access authority

prepare_put(auth, scope, kind, payload, expected_version, operation_id)
    -> PreparedContent                         # encrypt/wrap outside write UoW
publish_prepared(conn, auth, prepared, expected_parent_version)
    -> ContentRef                              # join caller's write UoW
get(auth, scope, ref, purpose) -> payload
get_many(auth, scope, refs, purpose) -> bounded authorized payloads
tombstone(conn, auth, scope, object_id, operation_id) -> deletion receipt

KeyService.wrap / unwrap(data_key, tenant_key_version, authenticated_context)
```

`PreparedContent` contains ciphertext, a wrapped key and validated identity/version
bindings; it is not a grant or a published reference. The business service prepares
outside `Database.transaction()`, then calls `publish_prepared`, updates its parent
pointer with a version check, and writes the operation receipt inside the same
transaction. Publication never commits independently. The store/adapter rejects
preparation or KMS-backed reads inside an active write transaction. Tombstoning
joins the caller's transaction and creates the lifecycle-journal outbox atomically;
its receipt distinguishes local revocation from independently durable deletion.

Use immutable payload versions and explicit schema/codec versions. The proposed
physical split keeps object lifecycle separate from versioned ciphertext:

| Record | Minimum fields and constraints |
| --- | --- |
| `content_object` | Opaque ID, authenticated tenant/owner, immutable scope and kind, current version, retention-policy reference, expiry and deletion state |
| `content_version` | Object/version unique key, ciphertext, nonce, wrapped data key, trusted wrapping-key reference/version, crypto/codec version, created time; scoped foreign-key constraints |
| `content_write_receipt` | Scoped operation ID, resulting reference and business version, allowing retries without a second logical write; no raw payload/hash preview |
| `content_lifecycle_event` | Append-only object IDs, deletion/revocation sequence and safe reason codes; durable recovery-journal delivery status |
| `storage_control` | Storage format, fresh dataset ID, initialization state and minimum reader/writer compatibility; no source/target migration state |

Final migration numbers are allocated at implementation time. Do not assume an
unused sequence number or edit previously applied migrations.

The service must enforce these rules:

1. Derive tenant identity from authenticated context; resolve the parent object
   and owner before accessing content. Internal machine work uses validated saved
   dispatch scope, never an arbitrary caller-supplied tenant/run. Do not expose a
   generic decrypt endpoint or turn the shared worker bearer into content authority.
2. Generate a fresh 256-bit data key per new payload version. Use the existing
   `cryptography` AES-GCM API, a fresh 96-bit nonce and canonical authenticated
   metadata binding tenant, scope, object/version, kind and codec/crypto version.
   Do not roll custom cryptography or upgrade dependencies just to add this module.
   See the [AES-GCM contract](https://cryptography.io/en/latest/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM).
3. Perform KMS/network work outside SQLite write transactions. Internally prepare
   ciphertext, then recheck current scope, deletion state and expected
   version inside the short transaction that publishes content, its parent pointer
   and the idempotency receipt. A prepared write grants no lasting authority.
   Refactor existing transaction-scoped row-to-DTO paths so they do not trigger
   KMS-backed reads while holding the writer lock; pre-read and validate versions,
   or return the already-authorized prepared value after commit.
4. For a retry, reuse the committed receipt and verify the original logical input
   through protected content. A different payload under the same operation ID is
   a conflict. A failed preparation can be discarded; never reuse a data-key/nonce
   pair for different plaintext. Versioned ciphertext stays immutable; rewrapping
   only changes key-envelope metadata under its own checked revision and audit.
5. Fail closed on missing keys, invalid tags, expired/deleted content, unsupported
   format or mismatched bindings. Never fall back to a plaintext column, another
   tenant key or a discarded database. Foreign references return a non-disclosing error.
6. Bound sizes, batch counts and decoded structures per content kind using the
   current input contracts. Keep plaintext and unwrapped keys operation-local;
   no shared plaintext cache, content tracing or raw exception logging.
   Recheck access/deletion immediately before returning assembled reads. Validate
   operation IDs as opaque identifiers, not user-provided descriptive strings.
7. Start with ciphertext BLOBs for existing bounded text/JSON. Introduce a blob
   adapter only when a stored binary/size requirement needs it, using immutable
   ciphertext before transactional pointer publication. Do not add a plaintext
   upload/screenshot path while that adapter is absent.

## Active persistence coverage

Convert current code paths, not historical data. Each active field must be protected
content, a justified typed operational projection, or a separately managed secret.
Do not leave plaintext duplicates for display, SQL filtering, diagnostics or replay.

| Active family | Code entry points | Required adaptation |
| --- | --- | --- |
| Definition name/instructions/network domains | [instances](../../backend/aicl/control/instances.py), [creation](../../backend/aicl/creation/service.py) | Content references; authorized display/sort/policy reads; retain optimistic versions. |
| Legacy chat slots/messages and assistant turns/messages | [chat](../../backend/aicl/chat/service.py), [assistant](../../backend/aicl/chat/assistant_service.py) | Protect both active chat modes, duplicate turn/reply values, metadata and error paths; retain request replay checks. |
| Assistant proposals/tool history and owner questions/answers | [tools](../../backend/aicl/chat/assistant_tools.py), [requests](../../backend/aicl/owner_requests/service.py) | Protect descriptions/results/JSON; project only validated control IDs/enums; keep approval/version/dedupe behavior. |
| Workflow configuration, run snapshots, deliverables and feedback | [workflow](../../backend/aicl/workflow/service.py), [inference](../../backend/aicl/workflow/inference_service.py) | Protect all versions, criteria, tool traces and private diagnostics; replace content-bearing SQL JSON reads. |
| Commerce briefs/output copies, quotes/fulfillment and order descriptions/bindings | [commerce](../../backend/aicl/commerce/service.py) | Eliminate duplicate plaintext; keep typed amount/currency/settlement facts and exact approval/payment semantics for new work. |
| Worker dispatch configuration and cached results | [Render](../../backend/aicl/render/service.py) | Encrypt replay receipts without regenerating work; retain settlement/idempotency semantics. |
| Browser evidence, purchase proposals and session domains | [workflow](../../backend/aicl/browser/workflow.py), [proposals](../../backend/aicl/browser/proposals.py), [sessions](../../backend/aicl/browser/service.py) | Protect page text/URLs/recommendations and domain values; retain domain lease uniqueness. Cookie state remains in the secret store. |
| Studio layout and reporting projections | [state](../../backend/aicl/studio/state.py), [data](../../backend/aicl/studio/data.py) | Protect arbitrary layout JSON and read upstream content through authorized repositories. Do not restore the removed Studio AI endpoint. |
| Action previews, audit details/reasons and sensitive bindings | [gate](../../backend/aicl/work/gate.py), [audit](../../backend/aicl/control/audit.py) | Safe enum/ID metadata or protected references; a field-name allowlist is not sufficient. New accounting/audit facts remain append-only. |
| Connection/OAuth/session display names | Existing connection/auth services | Explicit protected-content disposition; keep tokens, identity HMACs and encrypted credentials in their dedicated formats. |

System audit records without a tenant use a restricted system scope. Names, URLs
and arbitrary JSON are not safe operational projections. Use bounded authorized
reads rather than a global decrypted cache or a plaintext full-text index.

For exact-match browser-domain leases, keep the domain encrypted and use a
versioned tenant/owner-scoped HMAC lookup token under a separate KMS-protected
purpose key. This reveals equality within that scope; it is not general search.
Compute tokens before the write transaction. Serialize lease checks/insertion
across active key versions under a checked key-set revision, including during
rotation, so two tokens cannot create two leases for one domain. New payment and
approval bindings retain their exact protocol semantics rather than being replaced
by these lookup tokens.

## Four implementation packages

This replaces the earlier seven-package migration plan; none had been implemented.
All four packages are deferred. When this work resumes, local implementation can
proceed without selecting or provisioning a hosted key service first.

| ID | Deliverable | Acceptance |
| --- | --- | --- |
| ESC-1 | Content/key contracts, AES-GCM codec, SQLite records, scoped reads, prepare/publish writes, idempotency and tombstones; fake KMS | Authorized restart/round trip; wrong tenant/scope denied; tampering and key failure rejected; parent/content/receipt atomicity; no plaintext in storage or diagnostics. |
| ESC-2 | Composition, explicit empty initialization, format/key readiness and one complete agent-definition integration | Create, read, edit and restart against a fresh protected database; another owner is denied. Initialization refuses nonempty data and does not reset it automatically. |
| ESC-3 | Convert every active writer/reader in the inventory, including both chat modes, workflow/commerce copies, worker receipts and UI projections | Newly created conversations, work and outputs function end to end; replay/approval/accounting behavior is preserved; no alternate plaintext path remains. |
| ESC-4 | Real KMS/identities, storage/log/backup hardening, recovery verification and the short reset/recreate rollout | Staging proves role denial, key outage/rotation/recovery and encrypted persistence. Old worker identities cannot act on the fresh dataset. Restore/deletion claims match demonstrated controls. |

After ESC-2, conversation paths and execution/reporting paths can be converted in
parallel. Real KMS integration can proceed in parallel once ESC-1 contracts are
stable. Assign one owner to schema/composition changes and keep one shared content
service. There is no migration workstream.

### First storage PR when resumed: ESC-1

The first PR remains narrowly scoped: content service, additive schema and focused
tests. It does not delete data, change live traffic or provision infrastructure.
Use real AES-GCM with a fake KMS capable of tenant denial, outage and rotation.

Prove authorized reads after restart, cross-tenant/same-owner cross-scope denial,
tamper rejection, replay/conflict, stale versions, revocation races and failure
between encryption and publication. Reject preparation inside a write transaction;
prove parent update failure rolls back content and its receipt. Cover nested
savepoints and `commit_on_error` so denial audits cannot publish prepared content.
Inspect SQLite/WAL and captured diagnostics using synthetic private markers.

The next integration test creates a confidential agent definition, restarts the
app, then reads/edits it through the authorized application. This establishes the
pattern for every remaining path.

## Initialization and rollout

Use an explicit fresh-initialization operation and the
[reset procedure](../development/encrypted-content-reset.md). Recreate required
agents/settings through normal application services; seed only public catalog,
price data and clearly marked synthetic fixtures. Do not import old database files,
private content or old workflow identities.

Continue normal versioned schema migrations for the new format. Append reviewed
schema changes; do not rewrite applied historical migration files. Empty-table
rebuilds may remove obsolete plaintext columns. A nonempty legacy database must
fail with an explicit reset-required status, not be partially converted or erased
by application startup.

Before the one-time reset, stop cron, workers and all application writers; address
any actual external operation still in flight. Initialize on a clean database/file
set, excluding the old WAL/SHM files. Start with external dispatch disabled, verify
newly created data, then enable ordinary work. Old dispatch IDs are not reissued;
late requests for the discarded dataset cannot create or approve new work.

No compatibility with the discarded dataset is required. Once new data is worth
keeping, ordinary deployments must preserve it: an incompatible release fails
closed rather than restoring old plaintext or resetting the current database.

## Verification and continuing security

Use fresh two-tenant synthetic fixtures. Reuse existing integration tests for
creation, chat, workflow, owner requests, browser/Render and Studio, updated to use
content references. Keep meaningful crypto, authorization, transaction/retry,
lease-rotation and restart tests. Remove migration-specific fixtures, parity tests,
WAL-copy tests and source/target cutover simulations from this work's scope.

Inspect active DB/WAL, logs, queues, scratch files, blobs and backups for private
canaries. Measure KMS requests/read latency and payload size; use bounded
operation-local batching, not plaintext cross-request caching. One browser journey
can prove creation/history/output rendering and another owner's denial.

For newly created data, keep encrypted backups, key recovery, retention and
revocation/deletion. Test key rotation without loss of content. When restoring an
older backup, current deletion/revocation state must be reapplied before access;
if it cannot be established, restore remains closed. Paid work after restore also
requires complete accounting/dispatch history, or affected balances/dispatch stay
blocked. These are continuing recovery requirements, not reasons to build a legacy
migration engine. Do not claim instant erasure while recoverable backup keys remain.

Hosted choices still needed: KMS and verified host authentication, permitted roles,
key/backup recovery custody and retention for newly created content. These do not
block the first PR. Fake-key modes must never silently serve confidential hosted
traffic.

The durable execution loop defines the scoped repository and `ContentRef` seam
now; it does not wait for ESC-1/2. When secure storage resumes, include every new
runtime content path in the active inventory and replace the nonproduction
adapter. Preserve reference, transaction and replay semantics across that change.
The disposable-data reset removes the need to backfill prototype checkpoints;
reassess that assumption if any data must be retained before the production cutover.
