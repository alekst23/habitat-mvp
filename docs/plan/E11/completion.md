# E11 implementation and completion evidence

This record separates implemented code, ticket integration, candidate checks and
whole-epic acceptance. It supplements the original design/review history; it does
not replace the acceptance manifest or authorize a merge or deployment.

## Integrated implementation

| Ticket | Delivered behavior | Source and integration |
|---|---|---|
| E11-1 | Application/SQLite foundation, instance lifecycle, capabilities, budget reservation/settlement, price versions, audit and confirmation primitives | Source `279eb2b51734375e38a05a9833c96594d7411b9c`; integrated at `e03888e1c7a6996a0bba76269c5e921c35327921` (MR !48) |
| E11-2 | Canonical creation and app tools, owner operations, fake OAuth/secret broker, allow-list policy, dispatch gate and simulated work/reconciliation | Source `1e86671774206eb0cb7eb4c97867fc91a8c6a401`; integrated at `924835f36cb80eb89602e0ce4908a8f33f950bac` (MR !59) |
| E11-3 | Magic-link sign-in, sessions/CSRF, workspace and creation wizard | Source `eb8ef67447cb6c77995ebf28917d5d06e647f6b3`; integrated at `f696424d4535459575d02befca6239e0a8dbe649` (MR !74) |
| E11-4 | Scripted chat creation, allow-listed tools, chat persistence and canonical-service equivalence | Source `31a0a623ce6e1cb680b59da98f05b9fd22f3c5f7`; integrated at `6f276d91fbf517295db009263c194ee3315b4328` (MR !75) |
| E11-5 | Owner management views/forms, connections, usage/gating/audit, simulated-work confirmation and cross-surface/wiring proof | Source `5960066639a243e617c17b42630655a7135045fc`; integrated at `ce3ddcce189ff923464c216859e6c8b8efaad56e` (MR !76) |

## Historical checkpoint

The earlier E11-5 source `55b8c8eaf92cf8095f9ae6189a2702ac5fc9f4c8` includes the browser locator repair for the wizard's inference
checkbox. The recovered Development checkpoint reports verified implementation and
independent review at that candidate. [Pipeline 2959521499](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2959521499)
passed its verify, browser and E11-5 acceptance jobs; all three browser journeys
passed. The overall pipeline failed because the source-security adapter was not
configured. This is ticket-scoped evidence for the recorded source, not a pass for
subsequent documentation/foundation changes or the assembled epic.

The continuation source is [issue #11 checkpoint 4036669857](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/issues/11#note_4036669857):
40/60 actions used and one of three E11-5 repair attempts used. Preserve cumulative
history and counters; starting a new session does not reset them. Do not use the
older E2 `.ctx/session.json` or October 6 verify report as E11 evidence.

## Reconciled E11-1 through E11-4 receipts

The original review bodies, merged MRs, source/integration ancestry and retained
application/acceptance artifacts were independently checked during continuation.
These exact-SHA records support the restored ticket integration states:

| Ticket | Source application pipeline | Post-integration application pipeline | Independent source review |
|---|---|---|---|
| E11-1 | [2953437016](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2953437016) | [2954829815](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2954829815) | [Ready](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/issues/11#note_4025550508) |
| E11-2 | [2956291204](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2956291204) | [2957796410](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2957796410) | [Ready](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/issues/11#note_4033617895) |
| E11-3 | [2958641778](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2958641778) | [2959001096](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2959001096) | [Ready](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/issues/11#note_4035017893) |
| E11-4 | [2959108569](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2959108569) | [2959386324](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2959386324) | [Ready](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/issues/11#note_4036328305) |

Their application and scoped acceptance checks passed; required browser evidence
passed for E11-3 and E11-4. Their overall pipelines failed because source security
was unconfigured. E11-2 through E11-4 post-integration pipelines also retained the
expected failing whole-epic scope gate while the ticket marker was selected.
These historical failures are preserved; a later security pass is not attributed
to an earlier SHA. Current complete delivery evidence is recorded separately below.

## Codex continuation — 2026-10-18

The continuation repairs six independently reproduced defects: executor state
lost on restart, cross-tenant executor outcome collisions, dispatch ignoring a
persisted gate after budget rollover, owner-policy changes racing reservation,
cross-origin magic-link sign-in, and OAuth accepting grants beyond the requested
scopes. The simulator now journals starts/outcomes
by hold ID, authorization is rechecked inside the reservation transaction, and
sign-in confirmation requires the configured origin. The backend dependency lock
contains patched versions and is used by both verification and browser jobs.

On recovered application candidate `cb114ccaec3d57466f3755daf2a4bb96b5928bf0`,
local checks passed: 71 backend tests and all three browser journeys. The pre-final local
workflow suite passed 267 tests, including failure-oriented source/package adapter
checks. Independent repair recheck passed 21 focused tests; the additional OAuth repair
passed eight connection tests and independent recheck. The full backend suite
then passed 72 tests at application commit `5eca333`; package adapter changes
were checked separately. The local dependency
audit found no known vulnerabilities; Bandit found no errors or medium/high
findings (five low findings retained); the local secret scan found no secrets.
These are local development/review results, not GitLab CI acceptance receipts.

The scoped delivery adapters build a Docker archive and CycloneDX SBOM as CI
artifacts, scan the exact archived image, and validate its production-auth runtime
composition with networking disabled and temporary secrets/storage. Source SAST
blocks medium or higher findings; dependency, secret and container scans block
all findings. Missing tools, incomplete coverage or digest mismatches block the
pipeline. Configuration validation does not apply configuration: cloud hosts,
TLS ingress, SMTP delivery, permanent secrets and persistent-volume operations
remain unproven. No registry/cloud credentials or deployment job are added.

## Verified continuation and E11-5 integration

[Pipeline 2959692439](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2959692439) passed all ten mandatory jobs at
`5960066639a243e617c17b42630655a7135045fc`. Independently downloaded reports confirm
72 backend tests, three browser journeys and E11-5.AC1 acceptance. The pinned
manifest SHA-256 is `7950f2341e00c03f4e59beb2b82c79c885bbfd3b1d38025e26c1292994975dba`.
Source security retained five low SAST findings, with no blocking source findings
and no dependency or secret findings. Container scanning found no vulnerabilities;
the CycloneDX SBOM contains 67 components. Package, scan and configuration receipts
share archive digest `sha256:1eb02ea20618b322fda3d14aa2d11d097b4944f7619a96ca35cf5293f855301e`.
The configuration receipt confirms production authentication, disabled test routes,
fake providers and validation with networking disabled; `applied` is false.

The independent [ticket review](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/issues/11#note_4036851846) returned ready with
no unresolved findings. [MR !76](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/76) merged the reviewed
source into `ctx/epic-i11` at `ce3ddcce189ff923464c216859e6c8b8efaad56e`.
[Post-integration pipeline 2959700441](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2959700441) passed application verification
(job 17262061829), browser (17262061828) and scoped acceptance (17262061830) at
that exact integration SHA. The downloaded artifacts passed the acceptance
validator with the unchanged manifest hash. E11-5's workflow status is done.
The inherited E11-5 marker correctly fails the whole-epic scope job; no overall
post-integration pipeline pass is claimed.

The continuation also repaired two packaging/scanner compatibility findings:
loaded Docker image IDs are resolved and rebound to the scanned config bytes
before execution, and Trivy source reports accept both linked-worktree filesystem
and full-checkout repository forms while checking target and repository commit.
These repairs preserve blocking findings, source identity and artifact-digest gates.

## Final whole-epic handoff

All five implementations are now in the epic. The post-documentation candidate
must select committed acceptance scope `E11`, then pass fresh backend, browser,
all five acceptance criteria and all mandatory security/package/configuration
checks. A separate independent whole-epic review must cover that exact SHA,
including the merge of current workflow history from the default branch.

[MR !45](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/45) is the durable location for the final candidate,
current pipeline and independent whole-epic review. Read those current records to
establish readiness; this document does not pre-approve a later commit. Recording
final review in the MR/issue avoids a status-only commit that would change the
reviewed SHA. MR !45 remains draft/open, the parent issue stays open, and the
default-branch merge and deployment remain separate controlled actions.

## Scope and operating evidence

Use the [application guide](../../aicl-mvp.md) to run the local fake-backed
application. E11 does not include PayPal/funding, real model/provider execution,
an autonomous agent runner, arbitrary uploaded code, external MCP, live spend or
deployment. SMTP delivery is implemented, but a local test using captured mail
is not evidence that a particular SMTP account or deployment is configured.

Final assembled-epic verification and review belong to the exact candidate linked
from MR !45. Ticket integration and configuration validation do not establish
release readiness or deployment.
