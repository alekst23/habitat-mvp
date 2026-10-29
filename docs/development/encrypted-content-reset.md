# Fresh initialization for encrypted content storage

Status: proposed, October 25, 2026. The user confirmed current application data is
disposable. This replaces the legacy migration workstream in the
[implementation plan](../plan/encrypted-agent-storage.md). No data has been deleted
or recreated as part of planning.

Deferred with secure storage to the production release, October 26, 2026. This
reset is not a prerequisite for the current durable-session work.

## Scope

Initialize a new protected database and recreate needed agents/settings. Existing
conversations, outputs, IDs, approvals and demo balances do not need preservation.
Do not build a backfill tool, compatibility reader, parity verifier, generation
switch or migration receipt inbox.

The reset is a deliberate operation against an identified disposable environment,
not a behavior of application startup. An unavailable key, malformed ciphertext,
missing database or unsupported format must never cause automatic deletion or
silent reinitialization.

## Procedure to implement and rehearse

1. **Prepare the new release.** Complete active-path coverage and validate the
   content store and key configuration with synthetic fixtures. The fresh schema
   has protected references and no writable legacy plaintext path.
2. **Stop activity.** Suspend cron and stop application writers, startup/background
   hooks and workers. Finish or stop actual external operations before discarding
   their local records. If an already billed/uncertain operation still needs
   reconciliation, retain its minimal identity/evidence outside the reset target
   until resolved; disposable demo data does not cancel external effects.
3. **Reset the identified data set.** Remove or retire that environment's old
   database, WAL/SHM, content blobs and disposable scratch files together. Account
   for old snapshots/backups; a new empty database does not erase those copies.
   No old-data backup is required merely to preserve content the user has declared
   disposable. Do not delete deployment secrets, external accounts or unrelated
   storage as part of this operation.
4. **Initialize explicitly.** Create a clean database using reviewed schema
   migrations and a fresh dataset ID. Refuse nonempty targets. Do not import old
   rows or reuse old dispatch/attempt identities. Seed only public catalog/price
   records and explicitly synthetic fixtures. Recreate agents and reconnect any
   required accounts through their normal flows.
5. **Verify before dispatch.** With paid/background work disabled, create/read/edit
   an agent, add messages and an output, restart and read them again. Verify
   another tenant cannot read them, the persisted representation is encrypted and
   diagnostics do not include content. Reject late requests for old dispatch IDs;
   no stale worker request may create a new record or authorize new work.
6. **Enable ordinary work.** Enable only the newly configured schedules and
   capabilities. New work retains the existing reservation, approval, idempotency
   and unknown-outcome rules. Do not replay discarded schedules or approvals.

Use ordinary service shutdown and a clean initialization path for this one-time
reset; a general online migration/admission subsystem is unnecessary.

## Security after the reset

Keep keys separate from database/backup access, scope every decrypt operation,
encrypt before persistence and protect logs, caches and temporary files. A fresh
database removes historical conversion work, not these ongoing requirements.

Once new content must be retained, normal code deployments cannot reset it. Retain
format compatibility and fail closed on incompatibility. Backups need encryption,
separate key recovery and tested restoration. Restoring an old backup must not
resurrect deleted/revoked access or silently discard newer accounting history;
leave affected access/paid dispatch blocked when freshness cannot be established.

For the initial clean start, report only what was actually verified: fresh schema,
key access, active-path encryption and disposal of the identified old copies.
Do not equate removing a live file with secure erasure from every snapshot or disk.
