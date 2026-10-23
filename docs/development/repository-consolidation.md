# Local repository consolidation — 2026-10-23

The canonical application checkout in the existing `habitat-ai` workspace is
`habitat-mvp`, on local `main`, using the existing GitLab `showcase` origin.
It continues the former `e11-epic-completion` repository and retains its history.
No remote branch or deployment is changed by this local consolidation.
Merged local branch pointers are retained under
`refs/archive/2026-10-23/heads/`; `main` is the sole local working branch.
Inspect those pointers with `git for-each-ref refs/archive/2026-10-23/heads/`.

## Preserved application work

The starting application commit was `0b0348f` (sidebar username/sign-out).
Its history already contains the older `habitat-mvp/main` at `ca4e172` and
E11 recovery at `5960066`, plus UI refinement and the PayPal/Render work.

Commit `477da4d` preserves all 29 modified and 67 previously untracked source
files from the working tree: assistant, owner requests, browser execution,
migrations, assets, integration code, dependencies, tests and documentation.
Their contents were compared with the pre-move snapshot before committing.
Runtime databases and private configuration remain ignored local files.

## Local backup and archives

The workspace-level backup is
`../.migration-backups/2026-10-23-consolidation-171444/`.
It contains a full pre-consolidation filesystem archive, its SHA-256 digest,
four verified Git bundles, 78 checked SQLite snapshots, inventories and original
Git status/ref metadata. The full archive includes ignored files and Git metadata;
the bundles alone do not preserve working files, reflogs or runtime data.

Its `archived-checkouts/` directory preserves the former `habitat-mvp`,
`ctx-gcp-delivery`, `e11-completion` and `habitat-dev` directories. Linked-worktree
pointers were repaired inside the archive. Eight stale registrations were pruned
only after the complete backup; their branch refs remain preserved.

Google Cloud delivery remains on its archived branch and is not merged into this
application. `habitat-dev` has unrelated Git history and a separate architecture;
its code and local UI commit remain in its archived repository.

## Local paths and runtime

- `../e11-epic-completion` is a compatibility symlink to this checkout.
- `../e11-completion` is a compatibility symlink to its archived checkout so
  already-running interpreters and historical local tools retain their paths.
- This application has its own copied and relocated `.venv` for new commands.
- Workspace diagrams, recordings and documents remain in their original folders
  and are also covered by the full backup.

Use `.venv/bin/python` from this repository for new launches. Compatibility links
can be removed after old sessions and scripts no longer use them. Historical
receipts retain their original paths rather than being rewritten as new evidence.

## Validation

At the preserved source state, local backend validation passed 656 tests with
one skip for the optional Render SDK, which is not installed in the copied
environment. The real-browser backend fixtures used local test websites.
All 269 workflow tests passed. Workflow catalog validation and E11 structural
design validation passed; structural validation does not establish semantic
acceptance. Local test logs are retained with the backup metadata.

All five browser journeys passed from the relocated checkout and its own Python
environment. The existing commerce browser test was updated to follow the
Requests approval/decline flow already implemented in the preserved application;
Audit remains the purchase-history view. Application behavior was not changed
by this test correction.

These are local checks, not a new GitLab pipeline or production release approval.
